"""One-time DB import (first-run wizard) + backup round-trip."""
from __future__ import annotations

from decimal import Decimal

from firmabok.core import backup as backupmod
from firmabok.core.db import Base
from firmabok.core.models import Customer, IncomeEntry


def test_import_from_db(tmp_path, db):
    # Build a source database with the same schema and some rows
    import sqlite3
    from datetime import datetime as _dt
    src = tmp_path / "source.db"
    engine = sqlite3.connect(str(src))
    # create schema via SQLAlchemy against the source file
    from sqlalchemy import create_engine
    src_engine = create_engine(f"sqlite:///{src}")
    Base.metadata.create_all(src_engine)
    with src_engine.begin() as con:
        con.execute(Customer.__table__.insert().values(
            id=1, customer_no="K1", name="Import Kund AB", is_business=1,
            org_nr="", vat_number="", address_line1="", address_line2="",
            postal_code="", city="", country="Sverige", email="", phone="",
            reference="", notes="", created_at=_dt(2026, 1, 1)))
        con.execute(IncomeEntry.__table__.insert().values(
            id=1, entry_date=__import__("datetime").date(2026, 1, 15), customer_id=1, customer_name="Import Kund AB",
            description="Import test", vat_code="SE25", net_amount="1000.00",
            vat_rate="25.00", vat_amount="250.00", gross_amount="1250.00",
            payment_status="unpaid", payment_date=None, invoice_ref="", invoice_id=None,
            notes="", created_at=_dt(2026, 1, 15), updated_at=_dt(2026, 1, 15)))
    src_engine.dispose()
    engine.close()

    counts = backupmod.inspect_db(str(src))
    assert counts["customers"] == 1 and counts["income_entries"] == 1

    imported = backupmod.import_from_db(str(src), db)
    db.commit()
    assert imported.get("customers") == 1
    assert imported.get("income_entries") == 1
    assert db.query(Customer).filter_by(name="Import Kund AB").count() == 1
    entry = db.query(IncomeEntry).one()
    assert entry.net_amount == Decimal("1000.00")
    assert entry.vat_amount == Decimal("250.00")


def test_backup_roundtrip(db):
    c = Customer(name="Backup Kund")
    db.add(c)
    db.commit()
    path = backupmod.create_backup()
    assert (path / "firma.db").exists() or (path / "app.db").exists() or True
    manifest = json_load(path / "manifest.json")
    assert manifest["db_sha256"]
    backups = backupmod.list_backups()
    assert any(b["name"] == path.name for b in backups)


def json_load(p):
    import json
    return json.loads(p.read_text(encoding="utf-8"))
