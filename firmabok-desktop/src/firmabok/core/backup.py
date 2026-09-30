"""Local backup / restore for the SQLite database and uploads folder.

Two independent systems live in this module (both offline, both local):

1. Legacy directory backups (below, unchanged): timestamped folders under
   data/backups/ used by the Data page and Ctrl+B.
2. Single-file ``.bokvakt`` archives (Phase 1 foundation, at the bottom of
   this module): ``create_backup_archive`` / ``restore_backup_archive`` /
   ``list_backup_archives`` / ``prune_old_backups`` — one file containing
   app.db + uploads + settings.json + manifest.json, optionally sealed with
   AES-256-GCM using an Argon2id-derived key. Restore ALWAYS writes an
   unencrypted safety archive to $XDG_STATE_HOME/bokVakt/safety-backups/
   before touching live data.

CLI (legacy directory backups):
    python -m app.backup backup            # create a timestamped backup
    python -m app.backup list              # list existing backups
    python -m app.backup restore <name>    # restore (stop the app first!)

Backups are plain directories under data/backups/ containing:
    firma.db          (consistent copy via the SQLite online backup API)
    uploads/          (logos, receipts)
    manifest.json     (timestamp, sizes, sha256 of the DB)
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from argon2.low_level import Type as ArgonType
from argon2.low_level import hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .. import __version__
from . import config
from .errors import BackupError


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def create_backup(dest: Path | None = None) -> Path:
    config.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = dest or (config.BACKUP_DIR / f"firma-backup-{stamp}")
    target.mkdir(parents=True, exist_ok=True)

    db_target = target / "firma.db"
    src = sqlite3.connect(str(config.DB_PATH))
    dst = sqlite3.connect(str(db_target))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()

    if config.UPLOAD_DIR.exists():
        shutil.copytree(config.UPLOAD_DIR, target / "uploads", dirs_exist_ok=True)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "db_sha256": _sha256(db_target),
        "db_bytes": db_target.stat().st_size,
        "app_version": "1.0.0",
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


def list_backups() -> list[dict]:
    config.ensure_dirs()
    out = []
    for d in sorted(config.BACKUP_DIR.iterdir(), reverse=True):
        if not d.is_dir() or not (d / "firma.db").exists():
            continue
        manifest = {}
        mf = d / "manifest.json"
        if mf.exists():
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
        size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        out.append({"name": d.name, "path": d, "created_at": manifest.get("created_at", ""),
                    "db_bytes": manifest.get("db_bytes", 0), "total_bytes": size})
    return out


def restore_backup(name: str) -> Path:
    """Restore a backup over the live data. STOP THE APP FIRST."""
    src = config.BACKUP_DIR / name
    if not src.is_dir() or not (src / "firma.db").exists():
        raise BackupError("backup.not_found", name=str(name))
    manifest = {}
    mf = src / "manifest.json"
    if mf.exists():
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    if manifest.get("db_sha256") and manifest["db_sha256"] != _sha256(src / "firma.db"):
        raise BackupError("backup.checksum")

    config.ensure_dirs()
    # Safety copy of the current state before overwriting
    safety = create_backup(config.BACKUP_DIR / f"pre-restore-{datetime.now():%Y%m%d-%H%M%S}")

    # Replace DB (including WAL/SHM sidecars)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy2(src / "firma.db", config.DB_PATH)

    # Replace uploads
    if (src / "uploads").exists():
        if config.UPLOAD_DIR.exists():
            shutil.rmtree(config.UPLOAD_DIR)
        shutil.copytree(src / "uploads", config.UPLOAD_DIR)

    return safety


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("backup", "list", "restore"):
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "backup":
        path = create_backup()
        print(f"Backup skapad: {path}")
        return 0
    if cmd == "list":
        for b in list_backups():
            print(f"{b['name']}  ({b['created_at']}, {b['total_bytes']/1e6:.1f} MB)")
        return 0
    if cmd == "restore":
        if len(argv) < 2:
            print("Ange backup-namn: python -m app.backup restore <name>")
            return 2
        safety = restore_backup(argv[1])
        print(f"Återställning klar. Föregående data sparad i: {safety}")
        print("Starta om applikationen nu.")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))


# ---------------------------------------------------------------------------
# One-time import (first-run wizard)
# ---------------------------------------------------------------------------

def inspect_db(path: str) -> dict[str, int]:
    """Row counts of an existing Firmabok database (read-only)."""
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = {}
    try:
        for t in ("customers", "income_entries", "expenses", "invoices",
                  "owner_transactions", "vat_reports"):
            try:
                out[t] = src.execute(f"select count(*) from {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = 0
    finally:
        src.close()
    return out


def _coerce_for(col_type, value: str):
    """SQLite returns TEXT for Date/DateTime columns; convert back so
    SQLAlchemy type checks pass."""
    from datetime import date as _date
    from datetime import datetime as _datetime

    import sqlalchemy as sa
    if col_type is None:
        return value
    if isinstance(col_type, sa.DateTime):
        try:
            return _datetime.fromisoformat(value)
        except ValueError:
            return value
    if isinstance(col_type, sa.Date):
        try:
            return _date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(col_type, sa.Boolean):
        return bool(int(value)) if value.isdigit() else value
    return value


def import_from_db(path: str, db) -> dict[str, int]:
    """One-time import of rows from another Firmabok DB (web app or desktop)
    into the current session. INSERT OR IGNORE preserves keys; target tables
    should be empty (the wizard enforces this)."""
    from . import models  # noqa: F401
    from .db import Base

    counts = inspect_db(path)
    if any(counts.values()):
        pass  # allowed — wizard guarantees target is empty
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    imported: dict[str, int] = {}
    order = ["customers", "expense_categories", "invoice_series", "invoices",
             "invoice_lines", "income_entries", "expenses", "owner_transactions",
             "vat_reports", "audit_log", "attachments"]
    try:
        for tname in order:
            table = Base.metadata.tables.get(tname)
            if table is None:
                continue
            try:
                cur = src.execute(f"select * from {tname}")
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            except sqlite3.Error:
                continue
            tcols = {c.name for c in table.columns}
            use = [c for c in cols if c in tcols]
            col_types = {c.name: c.type for c in table.columns}
            n = 0
            for row in rows:
                values = dict(zip(cols, row, strict=False))
                coerced = {}
                for k in use:
                    v = values[k]
                    if isinstance(v, str):
                        v = _coerce_for(col_types.get(k), v)
                    coerced[k] = v
                db.execute(table.insert().prefix_with("OR IGNORE").values(**coerced))
                n += 1
            imported[tname] = n
        # company profile: copy only when the target profile is still blank
        from .models import CompanyProfile
        target = db.get(CompanyProfile, 1)
        try:
            scur = src.execute("select * from company_profile where id=1")
            srow = scur.fetchone()
            scols = [d[0] for d in scur.description] if srow else []
        except sqlite3.Error:
            srow = None
        if srow is not None and target is not None and not target.company_name:
            values = dict(zip(scols, srow, strict=False))
            skip = {"id", "simplified_vat_mode"}
            for k, v in values.items():
                if k in skip or not hasattr(target, k):
                    continue
                setattr(target, k, v)
            imported["company_profile"] = 1
        db.flush()
    finally:
        src.close()
    return imported


# ---------------------------------------------------------------------------
# Single-file encrypted backups — ".bokvakt" archives (Phase 1 foundation).
# Pure Python, no Qt. The legacy directory backups above are untouched and
# remain in use by the Data page / Ctrl+B until a later phase migrates the UI.
#
# File format
# -----------
# unencrypted : plain ZIP with members app.db, settings.json (when present),
#               manifest.json and uploads/** (when include_attachments).
# encrypted   : MAGIC + u16 header length + JSON header + AES-256-GCM(ZIP).
#               key   = Argon2id(password, random 16-byte salt,
#                                t=3, m=64 MiB, p=4, 32-byte output)
#               nonce = 12 random bytes; the JSON header is bound as GCM
#               additional authenticated data, so any tampering with the
#               header or ciphertext fails decryption (backup.wrong_password /
#               backup.corrupt — never silent bad data).
# ---------------------------------------------------------------------------

ARCHIVE_SUFFIX = ".bokvakt"
ARCHIVE_PREFIX = f"{config.BRAND_NAME}-backup-"          # bokVakt-backup-
SAFETY_PREFIX = f"{config.BRAND_NAME}-safety-backup-"   # bokVakt-safety-backup-
ARCHIVE_MAGIC = b"BOKVAKT\x00"
ARCHIVE_FORMAT_VERSION = 1
ARCHIVE_FORMAT_NAME = "bokvakt-archive"
KDF_TIME_COST, KDF_MEMORY_COST, KDF_PARALLELISM = 3, 65536, 4
KDF_KEY_LEN = 32          # AES-256
DEFAULT_KEEP_BACKUPS = 5

_NAME_STAMP_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})?")


def safety_backup_dir() -> Path:
    """$XDG_STATE_HOME/bokVakt/safety-backups/ (created on demand).
    FIRMABOK_STATE_DIR overrides the base dir (tests / portable use)."""
    d = config.brand_state_dir() / "safety-backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_archive_path(when: datetime | None = None) -> Path:
    """bokVakt-backup-YYYY-MM-DD-HHMM.bokvakt inside config.BACKUP_DIR."""
    stamp = (when or datetime.now()).strftime("%Y-%m-%d-%H%M")
    return config.BACKUP_DIR / f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"


def _unique_archive_path(p: Path) -> Path:
    """Never overwrite an existing backup: append -2, -3, … on collision."""
    if not p.exists():
        return p
    for n in range(2, 1000):
        cand = p.with_name(f"{p.stem}-{n}{p.suffix}")
        if not cand.exists():
            return cand
    raise BackupError("backup.target_exists", path=str(p))


def _derive_key(password: str, salt: bytes, time_cost: int,
                memory_cost: int, parallelism: int) -> bytes:
    return hash_secret_raw(secret=password.encode("utf-8"), salt=salt,
                           time_cost=time_cost, memory_cost=memory_cost,
                           parallelism=parallelism, hash_len=KDF_KEY_LEN,
                           type=ArgonType.ID)


def _seal(payload: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "v": ARCHIVE_FORMAT_VERSION, "kdf": "argon2id", "cipher": "aes-256-gcm",
        "time_cost": KDF_TIME_COST, "memory_cost": KDF_MEMORY_COST,
        "parallelism": KDF_PARALLELISM,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = _derive_key(password, salt, KDF_TIME_COST, KDF_MEMORY_COST, KDF_PARALLELISM)
    ct = AESGCM(key).encrypt(nonce, payload, header_bytes)
    return ARCHIVE_MAGIC + len(header_bytes).to_bytes(2, "big") + header_bytes + ct


def _unseal(blob: bytes, password: str | None) -> bytes:
    hlen = int.from_bytes(blob[len(ARCHIVE_MAGIC):len(ARCHIVE_MAGIC) + 2], "big")
    header_bytes = blob[len(ARCHIVE_MAGIC) + 2:len(ARCHIVE_MAGIC) + 2 + hlen]
    try:
        header = json.loads(header_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("backup.corrupt") from exc
    if (header.get("v") != ARCHIVE_FORMAT_VERSION or header.get("kdf") != "argon2id"
            or header.get("cipher") != "aes-256-gcm"):
        raise BackupError("backup.unsupported_version", version=str(header.get("v")))
    if not password:
        raise BackupError("backup.password_required")
    try:
        salt = base64.b64decode(header["salt"], validate=True)
        nonce = base64.b64decode(header["nonce"], validate=True)
        key = _derive_key(password, salt, int(header["time_cost"]),
                          int(header["memory_cost"]), int(header["parallelism"]))
        return AESGCM(key).decrypt(nonce, blob[len(ARCHIVE_MAGIC) + 2 + hlen:], header_bytes)
    except InvalidTag as exc:
        # GCM auth failure = wrong password OR tampered file — never guess,
        # never return partial data.
        raise BackupError("backup.wrong_password") from exc
    except (KeyError, ValueError, TypeError) as exc:
        raise BackupError("backup.corrupt") from exc


def _zip_dir(stage: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(stage).as_posix())
    return buf.getvalue()


def _safe_extract(payload: bytes, dest: Path) -> None:
    """Extract a ZIP payload, rejecting absolute paths / '..' traversal."""
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        root = dest.resolve()
        for name in zf.namelist():
            if not (dest / name).resolve().is_relative_to(root):
                raise BackupError("backup.corrupt")
        zf.extractall(dest)


def _read_archive_manifest(stage: Path) -> dict:
    try:
        manifest = json.loads((stage / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError("backup.corrupt") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != ARCHIVE_FORMAT_NAME:
        raise BackupError("backup.corrupt")
    return manifest


def create_backup_archive(target_path: Path | str | None = None, *, encrypt: bool = True,
                          password: str | None = None, include_attachments: bool = True,
                          kind: str = "backup", when: datetime | None = None) -> Path:
    """Create a single-file .bokvakt backup (SQLite DB + uploads + settings +
    manifest.json). Returns the written path.

    * ``target_path`` None → ``default_archive_path()`` (BACKUP_DIR,
      ``bokVakt-backup-YYYY-MM-DD-HHMM.bokvakt``); a ``.bokvakt`` suffix is
      appended when missing; an existing file is never overwritten (-2, -3…).
    * ``encrypt=True`` (default) requires ``password`` → the ZIP payload is
      sealed with AES-256-GCM under an Argon2id-derived key.
    * ``include_attachments=False`` omits the uploads/ folder.
    * ``kind`` lands in the manifest ("backup" | "safety").
    * ``when`` fixes the name stamp / manifest timestamp (tests, schedules).
    The DB snapshot uses the SQLite online backup API (consistent even while
    the app is running); the file is staged next to the target and moved into
    place atomically.
    """
    config.ensure_dirs()
    if encrypt and not password:
        raise BackupError("backup.password_required")
    target = Path(target_path) if target_path else default_archive_path(when)
    if target.suffix.lower() != ARCHIVE_SUFFIX:
        target = target.with_name(target.name + ARCHIVE_SUFFIX)
    target = _unique_archive_path(target)

    with tempfile.TemporaryDirectory(prefix="bokvakt-backup-") as stage_raw:
        stage = Path(stage_raw)
        db_target = stage / "app.db"
        src = sqlite3.connect(str(config.DB_PATH))
        dst = sqlite3.connect(str(db_target))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()
        if config.settings_path().exists():
            shutil.copy2(config.settings_path(), stage / "settings.json")
        uploads_files = 0
        if include_attachments and config.UPLOAD_DIR.exists():
            shutil.copytree(config.UPLOAD_DIR, stage / "uploads")
            uploads_files = sum(1 for f in (stage / "uploads").rglob("*") if f.is_file())
        manifest = {
            "format": ARCHIVE_FORMAT_NAME,
            "format_version": ARCHIVE_FORMAT_VERSION,
            "kind": kind,
            "created_at": (when or datetime.now()).isoformat(timespec="seconds"),
            "app": config.BRAND_NAME,
            "app_version": __version__,
            "encrypted": bool(encrypt),
            "include_attachments": bool(include_attachments),
            "db_sha256": _sha256(db_target),
            "db_bytes": db_target.stat().st_size,
            "uploads_files": uploads_files,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        payload = _zip_dir(stage)

    if encrypt:
        payload = _seal(payload, password or "")
    part = Path(str(target) + ".part")
    part.write_bytes(payload)
    os.replace(part, target)
    return target


def restore_backup_archive(backup_path: Path | str, password: str | None = None) -> Path:
    """Restore a .bokvakt archive over the live data. Returns the path of the
    safety backup that was taken first.

    Safe-by-construction order:
      1. read + decrypt (when sealed) + extract + verify manifest/checksum —
         live data is untouched, a wrong password or corrupt file changes
         nothing (``backup.wrong_password`` / ``backup.corrupt`` /
         ``backup.checksum``);
      2. write an UNENCRYPTED safety archive of the current state into
         ``safety_backup_dir()`` (readable even if the password is later
         forgotten; the directory is private to the user);
      3. replace app.db (+ -wal/-shm sidecars), uploads/ (only when the
         archive contains them) and settings.json (atomically; the settings
         singleton is reloaded).
    Restart the app afterwards (open DB sessions still point at the old file).
    """
    src = Path(backup_path)
    if not src.is_file():
        raise BackupError("backup.not_found", name=src.name)
    blob = src.read_bytes()
    if blob.startswith(ARCHIVE_MAGIC):
        payload = _unseal(blob, password)
    elif blob.startswith(b"PK\x03\x04"):
        payload = blob  # unencrypted archive
    else:
        raise BackupError("backup.not_archive", name=src.name)

    with tempfile.TemporaryDirectory(prefix="bokvakt-restore-") as stage_raw:
        stage = Path(stage_raw)
        try:
            _safe_extract(payload, stage)
        except zipfile.BadZipFile as exc:
            raise BackupError("backup.corrupt", name=src.name) from exc
        manifest = _read_archive_manifest(stage)
        db_file = stage / "app.db"
        if not db_file.is_file():
            raise BackupError("backup.corrupt", name=src.name)
        if manifest.get("db_sha256") and manifest["db_sha256"] != _sha256(db_file):
            raise BackupError("backup.checksum")

        # 2. Safety backup of the CURRENT state — always, before any change.
        safety = create_backup_archive(
            safety_backup_dir()
            / f"{SAFETY_PREFIX}{datetime.now():%Y-%m-%d-%H%M%S}{ARCHIVE_SUFFIX}",
            encrypt=False, include_attachments=True, kind="safety")

        # 3. Replace live data.
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(config.DB_PATH) + suffix)
            if p.exists():
                p.unlink()
        shutil.copy2(db_file, config.DB_PATH)
        if (stage / "uploads").exists():
            if config.UPLOAD_DIR.exists():
                shutil.rmtree(config.UPLOAD_DIR)
            shutil.copytree(stage / "uploads", config.UPLOAD_DIR)
        else:
            config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        if (stage / "settings.json").exists():
            config.settings_path().parent.mkdir(parents=True, exist_ok=True)
            tmp = Path(str(config.settings_path()) + ".tmp")
            shutil.copy2(stage / "settings.json", tmp)
            os.replace(tmp, config.settings_path())
            config.reload_settings()  # drop the cached singleton
    return safety


def _stamp_from_name(name: str) -> str:
    """ISO-ish created_at parsed from the file name stamp (works for encrypted
    archives whose manifest cannot be read without the password)."""
    m = _NAME_STAMP_RE.search(name)
    if not m:
        return ""
    y, mo, d, h, mi, s = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s or '00'}"


def list_backup_archives(directory: Path | str | None = None) -> list[dict]:
    """Metadata for every .bokvakt archive in ``directory`` (default
    config.BACKUP_DIR), newest first. Encrypted archives expose file-level
    metadata only (created_at parsed from the name); unencrypted archives
    also expose manifest fields (kind, app_version, created_at). Legacy
    directory backups are ignored."""
    d = Path(directory) if directory else config.BACKUP_DIR
    out: list[dict] = []
    if not d.is_dir():
        return out
    for f in d.glob(f"*{ARCHIVE_SUFFIX}"):
        if not f.is_file():
            continue
        st = f.stat()
        meta: dict = {
            "name": f.name, "path": f, "size_bytes": st.st_size,
            "modified_at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "created_at": "", "encrypted": False, "kind": "", "app_version": "",
        }
        with f.open("rb") as fh:
            magic = fh.read(len(ARCHIVE_MAGIC))
        if magic == ARCHIVE_MAGIC:
            meta["encrypted"] = True
        else:
            try:
                with zipfile.ZipFile(f) as zf:
                    manifest = json.loads(zf.read("manifest.json"))
                for k in ("created_at", "kind", "app_version"):
                    if isinstance(manifest, dict) and manifest.get(k):
                        meta[k] = manifest[k]
            except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError,
                    UnicodeDecodeError):
                pass  # listed with name-level metadata only
        meta["created_at"] = (meta["created_at"] or _stamp_from_name(f.name)
                              or meta["modified_at"])
        out.append(meta)
    out.sort(key=lambda m: m["created_at"], reverse=True)
    return out


def prune_old_backups(directory: Path | str | None = None,
                      keep_last_n: int = DEFAULT_KEEP_BACKUPS) -> list[Path]:
    """Delete the oldest .bokvakt archives in ``directory`` (default
    config.BACKUP_DIR) so that only the newest ``keep_last_n`` remain.
    Returns the deleted paths. Legacy directory backups are never touched.
    keep_last_n=0 deletes every archive; negative values are rejected."""
    if keep_last_n < 0:
        raise BackupError("backup.prune_invalid_keep", keep=str(keep_last_n))
    archives = list_backup_archives(directory)  # newest first
    doomed = [Path(m["path"]) for m in archives[int(keep_last_n):]]
    for p in doomed:
        p.unlink(missing_ok=True)
    return doomed
