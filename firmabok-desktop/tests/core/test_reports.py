"""Report totals: P&L, monthly summaries, owner transactions isolation, CSV."""
from datetime import date
from decimal import Decimal

from conftest import make_expense, make_income
from firmabok.core import reports
from firmabok.core.models import OwnerTransaction


def test_profit_excludes_vat_and_owner_transactions(db):
    make_income(db, date(2026, 3, 1), "10000.00")            # vat 2500
    make_expense(db, date(2026, 3, 5), "3750.00")            # net 3000, vat 750 deductible
    db.add(OwnerTransaction(tx_date=date(2026, 3, 10), tx_type="uttag",
                            amount=Decimal("50000.00"), description="Stort uttag"))
    db.add(OwnerTransaction(tx_date=date(2026, 3, 11), tx_type="insattning",
                            amount=Decimal("7000.00"), description="Insättning"))
    db.commit()

    t = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t.net_income == Decimal("10000.00")
    assert t.gross_income == Decimal("12500.00")
    assert t.output_vat == Decimal("2500.00")
    assert t.input_vat == Decimal("750.00")
    assert t.net_vat == Decimal("1750.00")
    assert t.expense_cost == Decimal("3000.00")
    # Profit = net income − expense cost. Owner transactions must NOT affect it.
    assert t.profit == Decimal("7000.00")
    assert t.owner_withdrawals == Decimal("50000.00")
    assert t.owner_contributions == Decimal("7000.00")


def test_non_deductible_vat_is_cost(db):
    make_expense(db, date(2026, 2, 1), "625.00", deductible=Decimal("0"))
    t = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t.input_vat == Decimal("0.00")
    assert t.non_deductible_vat == Decimal("125.00")
    assert t.expense_cost == Decimal("625.00")     # full gross becomes the cost


def test_monthly_summary_groups_by_month(db):
    make_income(db, date(2026, 1, 15), "1000.00")
    make_income(db, date(2026, 1, 20), "2000.00")
    make_income(db, date(2026, 2, 10), "500.00")
    rows = reports.monthly_summary(db, 2026)
    assert len(rows) == 12
    jan = next(r for r in rows if r["calendar_month"] == 1)
    feb = next(r for r in rows if r["calendar_month"] == 2)
    mar = next(r for r in rows if r["calendar_month"] == 3)
    assert jan["totals"].net_income == Decimal("3000.00")
    assert feb["totals"].net_income == Decimal("500.00")
    assert mar["totals"].net_income == Decimal("0.00")


def test_weekly_summary_iso_weeks(db):
    # 2026-03-02 is a Monday (ISO week 10), 2026-03-09 Monday of week 11
    make_income(db, date(2026, 3, 2), "100.00", description="v10 a")
    make_income(db, date(2026, 3, 4), "200.00", description="v10 b")
    make_income(db, date(2026, 3, 9), "400.00", description="v11")
    weeks = reports.weekly_summary(db, 2026, 3)
    assert [w["week"] for w in weeks] == [10, 11]
    assert weeks[0]["net"] == Decimal("300.00")
    assert weeks[0]["count"] == 2
    assert weeks[1]["net"] == Decimal("400.00")


def test_expense_by_category(db):
    make_expense(db, date(2026, 3, 1), "1250.00", category_name="IT")
    make_expense(db, date(2026, 3, 2), "2500.00", category_name="IT")
    make_expense(db, date(2026, 3, 3), "625.00", category_name="Resor")
    cats = reports.expense_by_category(db, date(2026, 1, 1), date(2026, 12, 31))
    by_name = {c["category"]: c for c in cats}
    assert by_name["IT"]["gross"] == Decimal("3750.00")
    assert by_name["IT"]["cost"] == Decimal("3000.00")
    assert by_name["IT"]["count"] == 2
    assert by_name["Resor"]["cost"] == Decimal("500.00")


def test_pl_report_structure(db):
    make_income(db, date(2026, 3, 1), "1000.00")
    make_income(db, date(2026, 3, 2), "2000.00", code="SE6", rate=6)
    make_expense(db, date(2026, 3, 3), "1250.00", category_name="Kontor")
    pl = reports.pl_report(db, date(2026, 1, 1), date(2026, 12, 31))
    assert pl["revenue_total"] == Decimal("3000.00")
    assert pl["expense_total"] == Decimal("1000.00")
    assert pl["profit"] == Decimal("2000.00")
    assert len(pl["revenue_rows"]) == 2


def test_vat_report_snapshot_and_lock(db):
    make_income(db, date(2026, 4, 15), "10000.00")
    report, decl, period = reports.build_vat_report(db, "quarter", 2026, 2)
    db.commit()
    assert period.start == date(2026, 4, 1) and period.end == date(2026, 6, 30)
    assert decl.boxes["05"] == Decimal("10000.00")
    assert report.output_vat == Decimal("2500.00")
    assert report.net_vat == Decimal("2500.00")
    assert not report.locked

    # lock it
    report.locked = True
    db.commit()
    # new income must NOT change the locked snapshot
    make_income(db, date(2026, 5, 15), "99999.00")
    report2, decl2, _ = reports.build_vat_report(db, "quarter", 2026, 2)
    assert report2.id == report.id
    assert report2.output_vat == Decimal("2500.00")
    # live declaration shows the change (for comparison), snapshot stays
    assert decl2.output_vat == Decimal("27499.75")
    kronor = reports.boxes_kronor_from_report(report2)
    assert kronor["49"] == 2500


def test_journal_csv_contents(db):
    make_income(db, date(2026, 3, 1), "1000.00", description="Konsult A")
    make_expense(db, date(2026, 3, 2), "1250.00", supplier="Telia")
    db.add(OwnerTransaction(tx_date=date(2026, 3, 3), tx_type="uttag",
                            amount=Decimal("500.00"), description="Uttag"))
    db.commit()
    csv_text = reports.export_journal_csv(db, date(2026, 1, 1), date(2026, 12, 31))
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("Datum;Typ;Motpart")
    assert any("INTÄKT" in row and "Konsult A" in row for row in lines)
    assert any("UTGIFT" in row and "Telia" in row for row in lines)
    assert any("EGNA UTTAG" in row for row in lines)
    # rows are date-sorted
    dates = [row.split(";")[0] for row in lines[1:]]
    assert dates == sorted(dates)


def test_vat_declaration_csv_all_boxes(db):
    make_income(db, date(2026, 3, 1), "1000.00")
    incomes = db.query(reports.IncomeEntry).all()
    from firmabok.core.vat import compute_declaration
    decl = compute_declaration(incomes, [], date(2026, 1, 1), date(2026, 12, 31))
    csv_text = reports.export_vat_declaration_csv(decl)
    lines = csv_text.strip().splitlines()
    boxes = {row.split(";")[0] for row in lines[1:]}
    assert {"05", "10", "48", "49"} <= boxes


def test_ne_bilaga_csv(db):
    make_income(db, date(2026, 3, 1), "10000.00")
    make_expense(db, date(2026, 3, 2), "2500.00", category_name="IT")
    db.add(OwnerTransaction(tx_date=date(2026, 3, 3), tx_type="uttag",
                            amount=Decimal("99999.00"), description="x"))
    db.commit()
    csv_text = reports.export_ne_bilaga_csv(db, 2026)
    assert "Omsättning netto" in csv_text
    assert "10000.00" in csv_text
    assert "Resultat före skatt" in csv_text
    assert "8000.00" in csv_text          # 10000 − 2000 cost
    assert "99999.00" in csv_text          # withdrawals listed separately
    assert "Egna uttag" in csv_text
    assert "ej inlämningsformat" in csv_text.lower()  # disclaimer present
