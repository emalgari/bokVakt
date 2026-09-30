"""Application configuration.

Everything is local-first: data lives under FIRMA_DATA_DIR (default ./data).
No cloud services, no external APIs, no telemetry.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "Firmabok"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


# All mutable state lives here: SQLite DB, uploads, backups.
DATA_DIR = _env_path("FIRMA_DATA_DIR", BASE_DIR / "data")
DB_PATH = _env_path("FIRMA_DB_PATH", DATA_DIR / "firma.db")
UPLOAD_DIR = _env_path("FIRMA_UPLOAD_DIR", DATA_DIR / "uploads")
BACKUP_DIR = _env_path("FIRMA_BACKUP_DIR", DATA_DIR / "backups")

DATABASE_URL = os.environ.get("FIRMA_DATABASE_URL", f"sqlite:///{DB_PATH}")

# Upload limits
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}
ALLOWED_LOGO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
}

# Session lifetime
SESSION_DAYS = int(os.environ.get("FIRMA_SESSION_DAYS", "14"))

# Where the app binds when started via `firma-run` / helper scripts.
HOST = os.environ.get("FIRMA_HOST", "127.0.0.1")
PORT = int(os.environ.get("FIRMA_PORT", "8000"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, UPLOAD_DIR / "logos", UPLOAD_DIR / "receipts", BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
