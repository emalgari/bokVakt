"""XDG-compliant configuration for Firmabok Desktop.

Locations (Base Directory Specification):
  config  $XDG_CONFIG_HOME/firmabok/settings.json
  data    $XDG_DATA_HOME/firmabok/app.db, .../uploads/, .../backups/
  state   $XDG_STATE_HOME/firmabok/logs/, .../firmabok.lock

Environment overrides (tests / portable use): FIRMABOK_CONFIG_DIR,
FIRMABOK_DATA_DIR, FIRMABOK_STATE_DIR. Nothing is ever written inside the
Nix store or the repository.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "firmabok"

DEFAULTS: dict[str, Any] = {
    "language": "sv",
    "locale_override": "",          # "" = follow language
    "window_geometry": "",          # base64 QByteArray
    "window_state": "",
    "last_page": "dashboard",
    "accent": "",                   # "" = theme default
    "wizard_completed": False,
    "auth": {"enabled": False, "password_hash": "", "password_salt": "", "username": ""},
}


def _xdg(env: str, fallback_sub: str) -> Path:
    raw = os.environ.get(env)
    base = Path(raw).expanduser() if raw else Path.home() / fallback_sub
    return base / APP_NAME


def config_dir() -> Path:
    return _xdg("FIRMABOK_CONFIG_DIR", ".config")


def data_dir() -> Path:
    return _xdg("FIRMABOK_DATA_DIR", ".local/share")


def state_dir() -> Path:
    return _xdg("FIRMABOK_STATE_DIR", ".local/state")


# User-facing brand for artifacts like backup files/dirs. The package and
# import name stay ``firmabok`` (never renamed); "bokVakt" is only the brand.
BRAND_NAME = "bokVakt"


def brand_state_dir() -> Path:
    """$XDG_STATE_HOME/bokVakt — brand state dir for user-facing artifacts
    (e.g. safety backups). FIRMABOK_STATE_DIR overrides the base (tests /
    portable use), mirroring _xdg(); evaluated at call time."""
    raw = os.environ.get("FIRMABOK_STATE_DIR") or os.environ.get("XDG_STATE_HOME")
    base = Path(raw).expanduser() if raw else Path.home() / ".local/state"
    return base / BRAND_NAME


def settings_path() -> Path:
    return config_dir() / "settings.json"


DB_PATH = data_dir() / "app.db"
UPLOAD_DIR = data_dir() / "uploads"
BACKUP_DIR = data_dir() / "backups"
LOG_DIR = state_dir() / "logs"
LOCK_PATH = state_dir() / f"{APP_NAME}.lock"

# Aliases used by ported core modules (db.py, backup.py, pdf.py)
DATABASE_URL = f"sqlite:///{DB_PATH}"


def ensure_dirs() -> None:
    for d in (config_dir(), data_dir(), state_dir(),
              UPLOAD_DIR, UPLOAD_DIR / "logos", UPLOAD_DIR / "receipts",
              BACKUP_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


class Settings:
    """settings.json wrapper: typed get/set, atomic save."""

    def __init__(self, path: Path | None = None):
        self.path = path or settings_path()
        self._data: dict[str, Any] = json.loads(json.dumps(DEFAULTS))
        if self.path.exists():
            import contextlib
            with contextlib.suppress(json.JSONDecodeError, OSError):
                # corrupt settings never block startup
                self._data.update(json.loads(self.path.read_text(encoding="utf-8")))

    def get(self, key: str, default: Any = None) -> Any:
        value = self._data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)


_settings: Settings | None = None


def settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Drop the cached singleton so the next access re-reads settings.json
    from disk (used after a backup restore replaces the file)."""
    global _settings
    _settings = None
    return settings()


def reset_for_tests(config: Path | None = None, data: Path | None = None,
                    state: Path | None = None) -> None:
    """Point the module at temporary dirs (tests) and drop caches."""
    global _settings, DB_PATH, UPLOAD_DIR, BACKUP_DIR, LOG_DIR, LOCK_PATH, DATABASE_URL
    if config is not None:
        os.environ["FIRMABOK_CONFIG_DIR"] = str(config)
    if data is not None:
        os.environ["FIRMABOK_DATA_DIR"] = str(data)
    if state is not None:
        os.environ["FIRMABOK_STATE_DIR"] = str(state)
    DB_PATH = data_dir() / "app.db"
    UPLOAD_DIR = data_dir() / "uploads"
    BACKUP_DIR = data_dir() / "backups"
    LOG_DIR = state_dir() / "logs"
    LOCK_PATH = state_dir() / f"{APP_NAME}.lock"
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    _settings = None
    # ported modules read these attributes at call time
    from . import db as _db
    _db.reset_engine_for_tests(DATABASE_URL)
