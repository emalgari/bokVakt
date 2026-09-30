"""Alembic migration runner + first-start bootstrap seeding."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from . import config

log = logging.getLogger("firmabok.core.migrate")

ROOT = Path(__file__).resolve().parents[3]  # firmabok-desktop/


def run_migrations() -> None:
    """Apply migrations; on a brand-new DB this creates the full schema."""
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", config.DATABASE_URL)
        command.upgrade(cfg, "head")
    except Exception:  # pragma: no cover
        log.exception("Alembic failed — falling back to create_all")
        from . import models  # noqa: F401  (register tables)
        from .db import Base, get_engine
        Base.metadata.create_all(get_engine())


def ensure_tax_parameters(db: Session):
    from .models import TaxParameters
    params = db.get(TaxParameters, 1)
    if params is None:
        params = TaxParameters(id=1)
        db.add(params)
        db.flush()
    return params


def seed_reference_data(db: Session) -> None:
    ensure_tax_parameters(db)
    """Idempotent: VAT code table, company profile row, default categories."""
    from sqlalchemy import select

    from . import vat as vatmod
    from .models import CompanyProfile, ExpenseCategory, VatRate

    if db.get(CompanyProfile, 1) is None:
        db.add(CompanyProfile(id=1))

    existing = {r[0] for r in db.execute(select(VatRate.code)).all()}
    for registry in (vatmod.SALE_CODES, vatmod.PURCHASE_CODES):
        for info in registry.values():
            if info.code in existing:
                continue
            db.add(VatRate(code=info.code, label_sv=info.label_sv, percent=info.percent,
                           side=info.side, skv_boxes=info.boxes_text,
                           sort_order=info.sort_order * 10))

    defaults = [
        ("Kontor & administration", "6100"), ("IT & programvara", "6500"),
        ("Telefon & internet", "6200"), ("Resor", "5800"), ("Bil & transport", "5600"),
        ("Marknadsföring", "5900"), ("Representation", "5720"), ("Lokal & hyra", "5000"),
        ("Varor & material", "4000"), ("Underentreprenörer", "4400"),
        ("Försäkringar", "5510"), ("Bank & kortavgifter", "6570"),
        ("Bokföring & revision", "6900"), ("Övrigt", ""),
        # Vehicle/personnel categories below are DEFAULTS only — users can
        # rename/remove them freely (Settings → Lists & defaults).
        ("Löner & personalkostnader", "7000"),
        ("Transportstyrelsen (fordonsskatter och avgifter)", "5610"),
        ("Trängselskatt & vägtullar", ""),
        ("Bränsle & laddning", "5660"),
        ("Bilfinansiering (leasing/avbetalning)", ""),
        ("Parkering", ""),
        ("Fordonsförsäkring", "5510"),
        ("Service & reparation", "5670"),
        ("Övriga fordonskostnader", ""),
    ]
    have = {r[0] for r in db.execute(select(ExpenseCategory.name)).all()}
    for name, bas in defaults:
        if name not in have:
            db.add(ExpenseCategory(name=name, bas_account_hint=bas))
    db.commit()
