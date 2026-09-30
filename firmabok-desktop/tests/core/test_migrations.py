"""Migration 0004: upgrade adds the new schema, downgrade removes exactly it."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from firmabok.core import config as core_config

NEW_TABLES = {"gig_platforms", "vehicles", "employees", "salary_slips",
              "salary_slip_series", "tax_documents", "tax_parameters"}
ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


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


@pytest.fixture()
def at_head(db):
    """The shared test DB is already migrated to head by conftest."""
    command.upgrade(_cfg(), "head")
    yield
    # downgrade drops seeded rows (tax parameters, categories) — restore them
    # so later tests see the same state conftest established.
    command.upgrade(_cfg(), "head")
    from firmabok.core.migrate import seed_reference_data
    seed_reference_data(db)
    db.commit()


def test_head_has_new_schema(at_head):
    assert _tables() >= NEW_TABLES
    assert {"source_type", "platform_name"} <= _columns("income_entries")
    assert {"vehicle_id", "employee_id", "mileage"} <= _columns("expenses")


def test_downgrade_removes_new_schema_and_upgrade_restores(at_head):
    # Pinned to the revision below 0004 (was relative "-1"): this test must
    # keep verifying 0004's down/up as newer head migrations are added.
    command.downgrade(_cfg(), "a9e5e7d2d9d8")
    tables = _tables()
    assert not (NEW_TABLES & tables)
    assert "source_type" not in _columns("income_entries")
    assert "platform_name" not in _columns("income_entries")
    assert "vehicle_id" not in _columns("expenses")

    command.upgrade(_cfg(), "head")
    assert _tables() >= NEW_TABLES
    assert {"source_type", "platform_name"} <= _columns("income_entries")
    assert {"vehicle_id", "employee_id", "mileage"} <= _columns("expenses")


def test_legacy_rows_get_safe_defaults(at_head, db):
    """Existing rows keep working after the additive migration."""
    from datetime import date

    from conftest import make_income
    entry = make_income(db, date(2026, 8, 1), "100.00")
    db.refresh(entry)
    assert entry.source_type == "direct"
    assert entry.platform_name == ""
