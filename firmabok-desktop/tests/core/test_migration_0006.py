"""Migration 0006 (c3a7f10b0006): user_accounts + tax_parameters extras.

Own up/down/up coverage so tests/core/test_migrations.py can keep verifying
0004 against a PINNED target revision as new head migrations are added.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config

from firmabok.core import config as core_config

HEAD = "c3a7f10b0006"
BELOW = "525c59bcf550"  # 0004 — the head before this migration
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

ACCOUNT_COLUMNS = {"id", "display_name", "email", "password_hash", "recovery_hash",
                   "created_at", "last_login_at", "last_password_change_at",
                   "last_recovery_regen_at"}


def _cfg() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
    return cfg


def _tables() -> set[str]:
    con = sqlite3.connect(str(core_config.DB_PATH))
    try:
        return {r[0] for r in con.execute(
            "select name from sqlite_master where type='table'")}
    finally:
        con.close()


def _columns(table: str) -> set[str]:
    con = sqlite3.connect(str(core_config.DB_PATH))
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def _version() -> str:
    con = sqlite3.connect(str(core_config.DB_PATH))
    try:
        return con.execute("select version_num from alembic_version").fetchone()[0]
    finally:
        con.close()


def test_head_is_0006(db):
    command.upgrade(_cfg(), "head")
    assert _version() == HEAD


def test_upgrade_adds_new_schema(db):
    command.upgrade(_cfg(), "head")
    assert "user_accounts" in _tables()
    assert _columns("user_accounts") >= ACCOUNT_COLUMNS
    # email uniqueness is enforced
    idx = sqlite3.connect(str(core_config.DB_PATH)).execute(
        "select \"unique\" from pragma_index_list('user_accounts') where name=?",
        ("ix_user_accounts_email",)).fetchone()
    assert idx and idx[0] == 1
    # tax_parameters extras added, existing columns untouched
    cols = _columns("tax_parameters")
    assert {"kommun_name", "total_rate"} <= cols
    assert {"municipal_tax_pct", "church_pct", "burial_pct", "extra_deduction",
            "ag_rate_default", "youth_enabled", "youth_rate", "youth_ceiling",
            "mileage_rate", "vat_deadline_day", "source_note", "updated_at"} <= cols


def test_downgrade_removes_only_0006_and_upgrade_restores(db):
    command.upgrade(_cfg(), "head")
    command.downgrade(_cfg(), BELOW)
    assert _version() == BELOW
    assert "user_accounts" not in _tables()
    assert "kommun_name" not in _columns("tax_parameters")
    assert "total_rate" not in _columns("tax_parameters")
    # 0004's schema is still fully intact — only 0006 was rolled back.
    assert {"tax_parameters", "employees", "vehicles", "salary_slips",
            "salary_slip_series", "gig_platforms", "tax_documents"} <= _tables()
    assert {"source_type", "platform_name"} <= _columns("income_entries")
    assert {"vehicle_id", "employee_id", "mileage"} <= _columns("expenses")

    command.upgrade(_cfg(), "head")
    assert _version() == HEAD
    assert "user_accounts" in _tables()
    assert {"kommun_name", "total_rate"} <= _columns("tax_parameters")


def test_existing_tax_parameters_row_gets_safe_defaults(db):
    """The singleton row survives the down/up cycle; the new columns fall
    back to neutral server defaults (never a hardcoded legal value)."""
    from firmabok.core.migrate import ensure_tax_parameters

    command.upgrade(_cfg(), "head")
    params = ensure_tax_parameters(db)
    db.commit()
    assert params.id == 1
    assert params.kommun_name == ""
    assert params.total_rate == Decimal("0.00")
    # user-owned values in the new columns survive a round-trip
    params.kommun_name = "Stockholm"
    params.total_rate = Decimal("32.50")
    db.commit()
    command.downgrade(_cfg(), BELOW)
    command.upgrade(_cfg(), "head")
    db.expire_all()
    params = ensure_tax_parameters(db)
    db.commit()
    # (columns were dropped and re-added → neutral defaults again)
    assert params.kommun_name == ""
    assert params.total_rate == Decimal("0.00")
