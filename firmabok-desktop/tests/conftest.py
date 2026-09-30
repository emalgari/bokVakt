"""Shared test fixtures: isolated XDG dirs, fresh DB per session/test, Qt offscreen."""
from __future__ import annotations

import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_TMP = Path(tempfile.mkdtemp(prefix="firmabok-test-"))
os.environ["FIRMABOK_CONFIG_DIR"] = str(_TMP / "config")
os.environ["FIRMABOK_DATA_DIR"] = str(_TMP / "data")
os.environ["FIRMABOK_STATE_DIR"] = str(_TMP / "state")

import pytest  # noqa: E402

from firmabok.core import config  # noqa: E402
from firmabok.core.db import get_session_factory  # noqa: E402
from firmabok.core.migrate import run_migrations, seed_reference_data  # noqa: E402
from firmabok.core.models import (  # noqa: E402
    CompanyProfile,
    Customer,
    Expense,
    IncomeEntry,
    Invoice,
    InvoiceLine,
    InvoiceSeries,
    OwnerTransaction,
    VatReport,
)

config.reset_for_tests(_TMP / "config", _TMP / "data", _TMP / "state")


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    config.ensure_dirs()
    run_migrations()
    db = get_session_factory()()
    try:
        seed_reference_data(db)
    finally:
        db.close()
    yield


def _truncate(session):
    from sqlalchemy import text

    from firmabok.core.models import AuditLog
    session.execute(text("PRAGMA foreign_keys=OFF"))
    for model in (IncomeEntry, InvoiceLine, Invoice, Expense, OwnerTransaction,
                  VatReport, InvoiceSeries, Customer, AuditLog):
        session.query(model).delete()
    session.execute(text("PRAGMA foreign_keys=ON"))


@pytest.fixture()
def db():
    session = get_session_factory()()
    _truncate(session)
    profile = session.get(CompanyProfile, 1)
    if profile:
        profile.invoice_number_prefix = ""
        profile.invoice_number_digits = 4
        profile.invoice_number_start = 1
        profile.fiscal_year_start_month = 1
        profile.vat_period = "quarter"
        profile.simplified_vat_mode = False
        profile.payment_terms_days = 30
        profile.round_total_to_krona = False
        profile.vat_method = "faktura"
        profile.input_vat_on_payment = False
        profile.org_nr = ""
        profile.vat_number = ""
        profile.company_name = "Test Konsult"
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def customer(db) -> Customer:
    c = Customer(name="Testkund AB", org_nr="", city="Stockholm",
                 address_line1="Testgatan 1", postal_code="111 11", is_business=True)
    db.add(c)
    db.commit()
    return c


@pytest.fixture()
def profile(db) -> CompanyProfile:
    return db.get(CompanyProfile, 1)


def make_income(db, d: date, net: str, code="SE25", rate=None, **kw) -> IncomeEntry:
    from firmabok.core import vat as vatmod
    from firmabok.core.money import q2, vat_amount
    r = q2(rate if rate is not None else vatmod.default_rate_for(code))
    info = vatmod.get_code(code)
    vat = vat_amount(net, r) if info.domestic_sale_vat else q2(0)
    e = IncomeEntry(entry_date=d, customer_name=kw.pop("customer_name", "Kund"),
                    description=kw.pop("description", "Testintäkt"),
                    vat_code=code, net_amount=q2(net), vat_rate=r, vat_amount=vat,
                    gross_amount=q2(q2(net) + vat), **kw)
    db.add(e)
    db.commit()
    return e


def make_expense(db, d: date, gross: str, code="SE25_P", rate=None,
                 deductible=None, **kw) -> Expense:
    from firmabok.core import vat as vatmod
    from firmabok.core.money import net_from_gross, q2
    r = q2(rate if rate is not None else vatmod.default_rate_for(code))
    net = net_from_gross(gross, r)
    vat = q2(q2(gross) - net)
    x = Expense(expense_date=d, supplier=kw.pop("supplier", "Leverantör"),
                category_name=kw.pop("category_name", "Övrigt"),
                description=kw.pop("description", "Testutgift"),
                vat_code=code, net_amount=net, vat_rate=r, vat_amount=vat,
                gross_amount=q2(gross),
                deductible_vat=vat if deductible is None else q2(min(Decimal(str(deductible)), vat)),
                **kw)
    db.add(x)
    db.commit()
    return x


def make_invoice(db, customer, lines, invoice_date=None, **kw) -> Invoice:
    """lines: list of (description, qty, unit_price, code[, rate])"""
    from firmabok.core import vat as vatmod
    from firmabok.core.invoices import recalc_invoice
    from firmabok.core.money import q2
    inv = Invoice(status="draft", invoice_date=invoice_date or date(2026, 3, 15),
                  customer_id=customer.id, payment_terms_days=30, **kw)
    db.add(inv)
    db.flush()
    for i, spec in enumerate(lines):
        desc, qty, price, code = spec[0], spec[1], spec[2], spec[3]
        rate = spec[4] if len(spec) > 4 else None
        r = q2(rate if rate is not None else vatmod.default_rate_for(code))
        db.add(InvoiceLine(invoice_id=inv.id, position=i, description=desc,
                           quantity=Decimal(str(qty)), unit="st",
                           unit_price=q2(price), vat_code=code, vat_rate=r))
    db.flush()
    recalc_invoice(inv)
    db.commit()
    return inv
