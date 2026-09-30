"""Feature C: quarterly VAT overview — totals per quarter, filing marks, configurable deadline."""
from datetime import UTC, date, datetime
from decimal import Decimal

from conftest import make_expense, make_income
from firmabok.core import reports
from firmabok.core.migrate import ensure_tax_parameters
from firmabok.core.models import VatReport
from firmabok.core.swedish import filing_due, periods_of_year


def test_quarter_totals_match_months_and_year(db):
    make_income(db, date(2026, 2, 10), "10000.00")   # Q1
    make_income(db, date(2026, 5, 10), "4000.00")    # Q2
    make_expense(db, date(2026, 3, 10), "1250.00")   # Q1: net 1000, vat 250
    make_expense(db, date(2026, 6, 10), "625.00")    # Q2: net 500, vat 125
    db.commit()

    q1, _d1, _p1 = reports.build_vat_report(db, "quarter", 2026, 1)
    q2, _d2, _p2 = reports.build_vat_report(db, "quarter", 2026, 2)
    db.commit()

    assert q1.output_vat == Decimal("2500.00")
    assert q1.input_vat == Decimal("250.00")
    assert q1.net_vat == Decimal("2250.00")
    assert q2.output_vat == Decimal("1000.00")
    assert q2.input_vat == Decimal("125.00")
    assert q2.net_vat == Decimal("875.00")

    year, _dy, _py = reports.build_vat_report(db, "year", 2026, 1)
    db.commit()
    assert year.output_vat == q1.output_vat + q2.output_vat
    assert year.net_vat == q1.net_vat + q2.net_vat


def test_quarter_periods_span_correct_months(db):
    periods = periods_of_year("quarter", 2026, 1)
    assert [(p.start.month, p.end.month) for p in periods] == [
        (1, 3), (4, 6), (7, 9), (10, 12)]


def test_mark_quarter_filed_and_unfile(db):
    make_income(db, date(2026, 1, 10), "1000.00")   # output VAT 250
    report, _d, _p = reports.build_vat_report(db, "quarter", 2026, 1)
    db.commit()
    assert not report.locked and report.filed_at is None
    assert report.output_vat == Decimal("250.00")

    report.locked = True
    report.filed_at = datetime.now(UTC)
    db.commit()

    fresh = db.get(VatReport, report.id)
    assert fresh.locked and fresh.filed_at is not None

    # locked report keeps its filed snapshot even if data changes afterwards
    make_income(db, date(2026, 2, 15), "2000.00")   # would add 500 VAT
    report2, _d2, _p2 = reports.build_vat_report(db, "quarter", 2026, 1)
    db.commit()
    assert report2.output_vat == Decimal("250.00")

    report2.locked = False
    report2.filed_at = None
    db.commit()
    report3, _d3, _p3 = reports.build_vat_report(db, "quarter", 2026, 1)
    db.commit()
    assert report3.output_vat == Decimal("750.00")


def test_deadline_uses_configurable_defaults_not_hardcoded(db):
    params = ensure_tax_parameters(db)
    # default matches the usual rule: 12th of second month after period end
    assert filing_due(date(2026, 3, 31)) == date(2026, 5, 12)
    assert filing_due(date(2026, 3, 31), params.vat_deadline_day,
                      params.vat_deadline_month_offset) == date(2026, 5, 12)
    # user changes the defaults → deadline follows, nothing hardcoded
    params.vat_deadline_day = 20
    params.vat_deadline_month_offset = 1
    db.commit()
    assert filing_due(date(2026, 3, 31), params.vat_deadline_day,
                      params.vat_deadline_month_offset) == date(2026, 4, 20)
