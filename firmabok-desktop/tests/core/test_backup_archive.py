"""Phase 1: single-file .bokvakt backups — create/restore/encrypt/prune.

New file; no existing test is modified. Restoring replaces the live DB file,
so after every restore the pooled engine connections are disposed and a fresh
session is used (`fresh()`), mirroring the real-world "restart the app" step.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import make_income
from firmabok import __version__
from firmabok.core import backup as backupmod
from firmabok.core import config
from firmabok.core.db import get_engine, get_session_factory
from firmabok.core.errors import BackupError
from firmabok.core.models import Customer, IncomeEntry

PASSWORD = "backup-lösenord-123"
NAME_RE = re.compile(r"^bokVakt-backup-\d{4}-\d{2}-\d{2}-\d{2}\d{2}\.bokvakt$")


def fresh(db):
    """After a restore the DB file has been swapped: drop pooled connections
    and return a new session bound to the new file."""
    get_engine().dispose()
    db.close()
    return get_session_factory()()


@pytest.fixture(autouse=True)
def _clean_dirs(db):
    config.ensure_dirs()
    safety = config.brand_state_dir() / "safety-backups"
    if safety.exists():
        for f in safety.glob(f"*{backupmod.ARCHIVE_SUFFIX}"):
            f.unlink()
    yield


def _zip_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def _manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("manifest.json"))


# ---------------------------------------------------------------------------
# Creation & format
# ---------------------------------------------------------------------------

def test_default_name_and_zip_contents(db):
    p = backupmod.create_backup_archive(encrypt=False)
    assert p.parent == config.BACKUP_DIR
    assert NAME_RE.match(p.name), p.name
    names = _zip_names(p)
    assert "app.db" in names and "manifest.json" in names
    m = _manifest(p)
    assert m["format"] == "bokvakt-archive"
    assert m["format_version"] == 1
    assert m["app"] == "bokVakt"
    assert m["app_version"] == __version__
    assert m["encrypted"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", m["db_sha256"])
    # The DB member is a genuine SQLite file.
    with zipfile.ZipFile(p) as zf:
        assert zf.read("app.db")[:16] == b"SQLite format 3\x00"


def test_settings_json_included_when_present(db):
    config.settings().set("language", "en")
    config.settings().save()
    try:
        p = backupmod.create_backup_archive(encrypt=False)
        assert "settings.json" in _zip_names(p)
    finally:
        config.settings().set("language", "sv")
        config.settings().save()


def test_encrypted_archive_is_sealed_not_a_zip(db):
    p = backupmod.create_backup_archive(encrypt=True, password=PASSWORD)
    blob = p.read_bytes()
    assert blob.startswith(backupmod.ARCHIVE_MAGIC)
    assert not blob.startswith(b"PK")
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(p)
    header_len = int.from_bytes(blob[len(backupmod.ARCHIVE_MAGIC):
                                     len(backupmod.ARCHIVE_MAGIC) + 2], "big")
    header = json.loads(blob[len(backupmod.ARCHIVE_MAGIC) + 2:
                             len(backupmod.ARCHIVE_MAGIC) + 2 + header_len])
    assert header["kdf"] == "argon2id" and header["cipher"] == "aes-256-gcm"


def test_create_encrypted_requires_password(db):
    with pytest.raises(BackupError) as exc:
        backupmod.create_backup_archive(encrypt=True)
    assert exc.value.key == "backup.password_required"


def test_same_minute_collision_gets_suffix(db):
    when = datetime(2026, 1, 2, 3, 4)
    a = backupmod.create_backup_archive(encrypt=False, when=when)
    b = backupmod.create_backup_archive(encrypt=False, when=when)
    assert a != b and a.exists() and b.exists()
    assert b.name == a.stem + "-2" + backupmod.ARCHIVE_SUFFIX


# ---------------------------------------------------------------------------
# Restore round-trips
# ---------------------------------------------------------------------------

def test_roundtrip_plain_data_matches(db):
    c = Customer(name="Arkiv Kund AB", city="Stockholm")
    db.add(c)
    db.commit()
    make_income(db, date(2026, 5, 4), "1500.00", description="Arkivrörelse")
    config.settings().set("language", "en")
    config.settings().save()
    p = backupmod.create_backup_archive(encrypt=False)

    # Diverge from the archived state.
    db.query(IncomeEntry).delete()
    db.query(Customer).delete()
    db.add(Customer(name="Efter-ändring AB"))
    db.commit()
    config.settings().set("language", "sv")
    config.settings().save()

    safety = backupmod.restore_backup_archive(p)
    assert Path(safety).is_file()

    s = fresh(db)
    try:
        assert [x.name for x in s.query(Customer).all()] == ["Arkiv Kund AB"]
        entry = s.query(IncomeEntry).one()
        assert entry.net_amount == Decimal("1500.00")
        assert entry.description == "Arkivrörelse"
        assert config.settings().get("language") == "en"
    finally:
        config.settings().set("language", "sv")
        config.settings().save()
        s.close()


def test_roundtrip_encrypted(db):
    db.add(Customer(name="Krypterad Kund"))
    db.commit()
    p = backupmod.create_backup_archive(encrypt=True, password=PASSWORD)

    db.query(Customer).delete()
    db.commit()

    backupmod.restore_backup_archive(p, password=PASSWORD)
    s = fresh(db)
    try:
        assert [x.name for x in s.query(Customer).all()] == ["Krypterad Kund"]
    finally:
        s.close()


def test_restore_wrong_password_rejected_and_data_untouched(db):
    db.add(Customer(name="Orörd Kund"))
    db.commit()
    p = backupmod.create_backup_archive(encrypt=True, password=PASSWORD)
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(p, password="fel-lösenord")
    assert exc.value.key == "backup.wrong_password"
    # Live data was not touched and no safety backup was written.
    assert db.query(Customer).filter_by(name="Orörd Kund").count() == 1
    safety_files = list((config.brand_state_dir() / "safety-backups")
                        .glob(f"*{backupmod.ARCHIVE_SUFFIX}"))
    assert safety_files == []


def test_restore_encrypted_without_password(db):
    p = backupmod.create_backup_archive(encrypt=True, password=PASSWORD)
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(p)
    assert exc.value.key == "backup.password_required"


def test_restore_missing_file(db):
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(config.BACKUP_DIR / "finns-inte.bokvakt")
    assert exc.value.key == "backup.not_found"


def test_restore_foreign_file_rejected(db, tmp_path):
    junk = tmp_path / "junk.bokvakt"
    junk.write_bytes(b"this is not a backup at all")
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(junk)
    assert exc.value.key == "backup.not_archive"


def test_restore_checksum_mismatch_rejected(db, tmp_path):
    p = backupmod.create_backup_archive(encrypt=False)
    tampered = tmp_path / "tampered.bokvakt"
    with zipfile.ZipFile(p) as src, zipfile.ZipFile(tampered, "w") as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "app.db":
                data = b"corrupted-db-bytes"
            dst.writestr(item, data)
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(tampered)
    assert exc.value.key == "backup.checksum"


def test_restore_tampered_ciphertext_rejected(db, tmp_path):
    p = backupmod.create_backup_archive(encrypt=True, password=PASSWORD)
    blob = bytearray(p.read_bytes())
    blob[-1] ^= 0xFF  # flip a ciphertext/tag bit
    tampered = tmp_path / "tampered.bokvakt"
    tampered.write_bytes(bytes(blob))
    with pytest.raises(BackupError) as exc:
        backupmod.restore_backup_archive(tampered, password=PASSWORD)
    assert exc.value.key == "backup.wrong_password"


# ---------------------------------------------------------------------------
# Safety backup
# ---------------------------------------------------------------------------

def test_safety_backup_created_before_restore_and_is_restorable(db):
    # State A → archive; state B live; restore A; safety must hold B.
    db.add(Customer(name="A Kund"))
    db.commit()
    archive_a = backupmod.create_backup_archive(encrypt=False)

    db.query(Customer).delete()
    db.add(Customer(name="B Kund"))
    db.commit()

    safety_dir = config.brand_state_dir() / "safety-backups"
    safety = backupmod.restore_backup_archive(archive_a)

    assert Path(safety).is_file()
    assert Path(safety).parent == safety_dir
    assert Path(safety).name.startswith(backupmod.SAFETY_PREFIX)
    assert Path(safety).suffix == backupmod.ARCHIVE_SUFFIX
    assert _manifest(Path(safety))["kind"] == "safety"

    s = fresh(db)
    try:
        assert [x.name for x in s.query(Customer).all()] == ["A Kund"]
        # The safety archive brings state B back.
        backupmod.restore_backup_archive(safety)
        s2 = fresh(s)
        try:
            assert [x.name for x in s2.query(Customer).all()] == ["B Kund"]
        finally:
            s2.close()
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Listing & pruning
# ---------------------------------------------------------------------------

def test_list_backups_metadata(db, tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    plain = backupmod.create_backup_archive(d / "bokVakt-backup-2026-01-02-0304.bokvakt",
                                            encrypt=False, when=datetime(2026, 1, 2, 3, 4))
    sealed = backupmod.create_backup_archive(d / "bokVakt-backup-2026-01-02-0506.bokvakt",
                                             encrypt=True, password=PASSWORD,
                                             when=datetime(2026, 1, 2, 5, 6))
    listed = backupmod.list_backup_archives(d)
    assert [m["name"] for m in listed] == [sealed.name, plain.name]  # newest first
    by_name = {m["name"]: m for m in listed}
    assert by_name[sealed.name]["encrypted"] is True
    assert by_name[sealed.name]["created_at"] == "2026-01-02T05:06:00"  # from name
    assert by_name[plain.name]["encrypted"] is False
    assert by_name[plain.name]["created_at"] == "2026-01-02T03:04:00"   # from manifest
    assert by_name[plain.name]["app_version"] == __version__            # from manifest
    assert by_name[plain.name]["size_bytes"] == plain.stat().st_size


def test_list_ignores_legacy_and_foreign_files(db):
    legacy = backupmod.create_backup()  # legacy directory backup
    foreign = config.BACKUP_DIR / "notes.txt"
    foreign.write_text("not a backup", encoding="utf-8")
    try:
        names = [m["name"] for m in backupmod.list_backup_archives()]
        assert legacy.name not in names
        assert "notes.txt" not in names
    finally:
        foreign.unlink()


def test_prune_keeps_last_n(db, tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    paths = [backupmod.create_backup_archive(
        d / f"bokVakt-backup-2026-01-02-03{m:02d}.bokvakt", encrypt=False,
        when=datetime(2026, 1, 2, 3, m))
        for m in (1, 2, 3, 4)]
    legacy_dir = d / "firma-backup-20250101-000000"  # legacy dirs are never touched
    legacy_dir.mkdir()

    deleted = backupmod.prune_old_backups(d, 2)
    assert sorted(str(x) for x in deleted) == sorted(str(x) for x in paths[:2])
    remaining = sorted(p.name for p in d.glob(f"*{backupmod.ARCHIVE_SUFFIX}"))
    assert remaining == [paths[2].name, paths[3].name]
    assert legacy_dir.exists()

    deleted_all = backupmod.prune_old_backups(d, 0)
    assert sorted(str(x) for x in deleted_all) == sorted(str(x) for x in paths[2:])
    assert list(d.glob(f"*{backupmod.ARCHIVE_SUFFIX}")) == []

    with pytest.raises(BackupError) as exc:
        backupmod.prune_old_backups(d, -1)
    assert exc.value.key == "backup.prune_invalid_keep"


# ---------------------------------------------------------------------------
# Attachments (uploads)
# ---------------------------------------------------------------------------

def test_attachments_included_and_restored(db):
    receipt = config.UPLOAD_DIR / "receipts" / "kvitto.txt"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("kvitto", encoding="utf-8")
    p = backupmod.create_backup_archive(encrypt=False, include_attachments=True)
    assert any(n.startswith("uploads/") for n in _zip_names(p))
    assert _manifest(p)["uploads_files"] == 1

    receipt.unlink()
    assert not receipt.exists()
    backupmod.restore_backup_archive(p)
    s = fresh(db)
    try:
        assert receipt.exists() and receipt.read_text(encoding="utf-8") == "kvitto"
    finally:
        s.close()


def test_attachments_excluded_leaves_uploads_untouched(db):
    receipt = config.UPLOAD_DIR / "receipts" / "behåll.txt"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text("behåll", encoding="utf-8")
    db.add(Customer(name="Före Kund"))
    db.commit()
    p = backupmod.create_backup_archive(encrypt=False, include_attachments=False)
    assert not any(n.startswith("uploads/") for n in _zip_names(p))

    s = fresh(db)
    try:
        s.query(Customer).delete()
        s.commit()
        backupmod.restore_backup_archive(p)
        s2 = fresh(s)
        try:
            # DB restored, uploads untouched.
            assert [x.name for x in s2.query(Customer).all()] == ["Före Kund"]
            assert receipt.exists()
        finally:
            s2.close()
    finally:
        s.close()
