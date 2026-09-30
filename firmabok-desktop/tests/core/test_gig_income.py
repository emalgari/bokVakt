"""Feature A: gig/platform income flows into totals, filters, CSV and invoicing."""
from datetime import date
from decimal import Decimal

import pytest

from conftest import make_expense, make_income, make_invoice
from firmabok.core import reports
from firmabok.core.invoices import finalize_invoice
from firmabok.core.models import Customer, GigPlatform
from firmabok.core.money import q2


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(GigPlatform).delete()
    db.commit()
    yield
    db.query(GigPlatform).delete()
    db.commit()


def test_platform_income_flows_into_totals_and_result(db):
    make_income(db, date(2026, 6, 5), "10000.00", source_type="direct")
    make_income(db, date(2026, 6, 12), "8000.00", source_type="platform",
                platform_name="Uber", customer_name="Uber BV")
    make_expense(db, date(2026, 6, 20), "2500.00")  # net 2000, vat 500 deductible

    t = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t.net_income == Decimal("18000.00")           # direct + platform
    assert t.output_vat == q2(Decimal("18000.00") * Decimal("0.25"))
    assert t.expense_cost == Decimal("2000.00")
    assert t.profit == Decimal("16000.00")              # income - expenses


def test_platform_filters(db):
    make_income(db, date(2026, 5, 1), "1000.00", source_type="direct")
    make_income(db, date(2026, 5, 2), "2000.00", source_type="platform", platform_name="Uber")
    make_income(db, date(2026, 5, 3), "3000.00", source_type="platform", platform_name="Bolt")
    lo, hi = date(2026, 1, 1), date(2026, 12, 31)

    assert reports.compute_totals(db, lo, hi).net_income == Decimal("6000.00")  # legacy default
    assert reports.compute_totals(db, lo, hi, platform="Uber").net_income == Decimal("2000.00")
    assert reports.compute_totals(db, lo, hi, platform="*").net_income == Decimal("5000.00")
    assert reports.compute_totals(db, lo, hi, platform="").net_income == Decimal("1000.00")

    assert reports.compute_totals(db, lo, hi, platform="Bolt").net_income == Decimal("3000.00")


def test_weekly_monthly_aggregates_are_plain_entries(db):
    # one weekly and one monthly aggregate row for the same platform
    make_income(db, date(2026, 9, 28), "7350.25", source_type="platform",
                platform_name="Bolt", description="Bolt v.39")
    make_income(db, date(2026, 9, 30), "31200.10", source_type="platform",
                platform_name="Bolt", description="Bolt sept")
    t = reports.compute_totals(db, date(2026, 9, 1), date(2026, 9, 30), platform="Bolt")
    assert t.net_income == q2(Decimal("7350.25") + Decimal("31200.10"))


def test_monthly_summary_includes_platform_income(db):
    make_income(db, date(2026, 4, 1), "500.00", source_type="platform", platform_name="Foodora")
    months = reports.monthly_summary(db, 2026)
    april = next(m for m in months if m["calendar_month"] == 4)
    assert april["totals"].net_income == Decimal("500.00")


def test_invoice_for_platform_customer_uses_profile_and_customer(db):
    cust = Customer(name="Bolt Operations OÜ", country="EE", city="Tallinn",
                    address_line1="Test 1", postal_code="10111", is_business=True)
    db.add(cust)
    db.commit()
    make_income(db, date(2026, 7, 1), "12000.00", source_type="platform",
                platform_name="Bolt", customer_name="Bolt Operations OÜ",
                customer_id=cust.id)

    invoice = make_invoice(db, cust,
                           [("Körning via plattform, juni", "1", "12000.00", "SE25")],
                           invoice_date=date(2026, 7, 2))
    finalize_invoice(db, invoice, username="test")
    db.commit()

    assert invoice.status == "finalized"
    assert invoice.number
    assert invoice.gross_total == Decimal("15000.00")
    # seller data comes from CompanyProfile (checked in PDF tests), buyer from Customer
    assert db.get(Customer, invoice.customer_id).name == "Bolt Operations OÜ"


def test_platform_names_are_user_configurable(db):
    db.add(GigPlatform(name="MinLokalaPlattform", notes="egen"))
    db.commit()
    names = [p.name for p in db.query(GigPlatform).all()]
    assert "MinLokalaPlattform" in names
    assert not any(n in names for n in ("Uber", "Bolt"))  # nothing pre-seeded
