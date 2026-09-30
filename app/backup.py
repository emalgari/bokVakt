"""Local backup / restore for the SQLite database and uploads folder.

CLI:
    python -m app.backup backup            # create a timestamped backup
    python -m app.backup list              # list existing backups
    python -m app.backup restore <name>    # restore (stop the app first!)

Backups are plain directories under data/backups/ containing:
    firma.db          (consistent copy via the SQLite online backup API)
    uploads/          (logos, receipts)
    manifest.json     (timestamp, sizes, sha256 of the DB)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from . import config


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
        raise FileNotFoundError(f"Backup '{name}' finns inte eller är ofullständig.")
    manifest = {}
    mf = src / "manifest.json"
    if mf.exists():
        manifest = json.loads(mf.read_text(encoding="utf-8"))
    if manifest.get("db_sha256") and manifest["db_sha256"] != _sha256(src / "firma.db"):
        raise ValueError("Kontrollsumma (sha256) stämmer inte — backupen kan vara skadad.")

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
