"""Feature E: employees, salary slips (numbering, rates, youth reduction),
payment booking consistent with the cash method."""
from datetime import date
from decimal import Decimal

import pytest

from conftest import make_income, make_invoice
from firmabok.core import employees as emp
from firmabok.core import reports
from firmabok.core.errors import DomainError
from firmabok.core.invoices import finalize_invoice
from firmabok.core.migrate import ensure_tax_parameters
from firmabok.core.models import Employee, Expense, SalarySlip, SalarySlipSeries, TaxParameters


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(SalarySlip).delete()
    db.query(SalarySlipSeries).delete()
    db.query(Employee).delete()
    db.commit()
    p = db.get(TaxParameters, 1)
    if p:
        p.ag_rate_default = Decimal("31.42")
        p.youth_enabled = True
        p.youth_rate = Decimal("20.81")
        p.youth_ceiling = Decimal("25000.00")
        db.commit()
    yield
    db.query(Expense).filter_by(category_name=emp.PAYROLL_CATEGORY).delete()
    db.query(SalarySlip).delete()
    db.query(SalarySlipSeries).delete()
    db.query(Employee).delete()
    db.commit()


def _employee(db, **kw) -> Employee:
    defaults = dict(name="Test Anställd", employment_type="monthly",
                    monthly_salary=Decimal("30000.00"),
                    personnummer="010101-1234", bank_account="1234-5678")
    defaults.update(kw)
    e = Employee(**defaults)
    db.add(e)
    db.commit()
    return e


def test_personnummer_masked_in_lists(db):
    assert emp.mask_personnummer("010101-1234") == "•••••••1234"
    assert emp.mask_personnummer("") == ""


def test_monthly_slip_amounts_use_user_rates(db):
    e = _employee(db)
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("9000"))
    db.commit()
    assert slip.gross == Decimal("30000.00")
    assert slip.employer_contributions == Decimal("9426.00")   # 31.42 % default
    assert slip.a_tax == Decimal("9000.00")
    assert slip.net == Decimal("21000.00")
    assert slip.ag_rate_used == Decimal("31.42")
    assert not slip.youth_reduction


def test_youth_reduction_split_at_ceiling(db):
    e = _employee(db, birth_date=date(2005, 5, 5), monthly_salary=Decimal("30000.00"))
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    # 25 000 × 20.81 % + 5 000 × 31.42 % = 5 202.50 + 1 571.00
    assert slip.employer_contributions == Decimal("6773.50")
    assert slip.youth_reduction is True

    e2 = _employee(db, name="Under tak", birth_date=date(2004, 1, 1),
                   monthly_salary=Decimal("20000.00"))
    slip2 = emp.create_slip(db, e2, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    assert slip2.employer_contributions == Decimal("4162.00")  # 20 000 × 20.81 %
    assert slip2.youth_reduction is True


def test_youth_window_and_birth_years_respected(db):
    # born 2001 → outside configured birth-year span → standard rate
    e = _employee(db, birth_date=date(2001, 5, 5))
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    assert slip.youth_reduction is False
    assert slip.employer_contributions == Decimal("9426.00")
    # payment before the validity window → standard rate
    e2 = _employee(db, name="Utanför fönster", birth_date=date(2005, 5, 5))
    slip2 = emp.create_slip(db, e2, 2026, 2, a_tax=Decimal("0"),
                            pay_date=date(2026, 3, 25))
    db.commit()
    assert slip2.youth_reduction is False


def test_per_employee_override_disables_youth(db):
    e = _employee(db, birth_date=date(2005, 5, 5), ag_rate_override=Decimal("10.00"))
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    assert slip.youth_reduction is False
    assert slip.employer_contributions == Decimal("3000.00")
    assert slip.ag_rate_used == Decimal("10.00")


def test_hourly_requires_hours(db):
    e = _employee(db, employment_type="hourly", hourly_rate=Decimal("350.00"))
    with pytest.raises(DomainError) as exc:
        emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    assert exc.value.key == "emp.hours_required"
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("1000"), hours=Decimal("8"))
    db.commit()
    assert slip.gross == Decimal("2800.00")
    assert slip.net == Decimal("1800.00")


def test_revenue_percent_uses_month_income(db):
    make_income(db, date(2026, 5, 10), "10000.00")
    make_income(db, date(2026, 6, 10), "99999.00")   # other month, must not count
    e = _employee(db, employment_type="revenue_pct", revenue_pct=Decimal("20.00"))
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    assert slip.revenue_base == Decimal("10000.00")
    assert slip.gross == Decimal("2000.00")


def test_contract_requires_manual_gross(db):
    e = _employee(db, employment_type="contract", contract_terms="5 000 kr per körning")
    with pytest.raises(DomainError) as exc:
        emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    assert exc.value.key == "emp.manual_gross_required"
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("500"),
                           manual_gross=Decimal("5000.00"),
                           extra_lines=[{"label": "Bonus", "amount": "250.00"}])
    db.commit()
    assert slip.gross == Decimal("5250.00")
    assert slip.net == Decimal("4750.00")
    labels = [ln["label"] for ln in emp.slip_lines(slip)]
    assert "Kontraktsenlig lön" in labels and "Bonus" in labels


def test_slip_numbering_sequential_per_year_and_separate_from_invoices(db, customer):
    e = _employee(db)
    s1 = emp.create_slip(db, e, 2026, 1, a_tax=Decimal("0"))
    s2 = emp.create_slip(db, e, 2026, 2, a_tax=Decimal("0"))
    s3 = emp.create_slip(db, e, 2027, 1, a_tax=Decimal("0"))
    db.commit()
    assert (s1.number, s2.number, s3.number) == ("2026-0001", "2026-0002", "2027-0001")

    inv = make_invoice(db, customer, [("X", "1", "100", "SE25")], invoice_date=date(2026, 3, 1))
    finalize_invoice(db, inv, username="t")
    db.commit()
    assert inv.number == "2026-0001"      # invoice series untouched by slips


def test_draft_slip_books_nothing_paid_slip_books_cost(db):
    e = _employee(db)
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("9000"))
    db.commit()
    t0 = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t0.expense_cost == Decimal("0.00")   # not an expense until paid

    expense = emp.mark_paid(db, slip, date(2026, 5, 28))
    db.commit()
    assert slip.status == "paid" and slip.expense_id == expense.id
    assert expense.gross_amount == Decimal("39426.00")   # gross 30000 + AG 9426
    assert expense.deductible_vat == Decimal("0.00")
    assert expense.employee_id == e.id
    assert expense.category_name == emp.PAYROLL_CATEGORY
    assert expense.payment_date == date(2026, 5, 28)

    t1 = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t1.expense_cost == Decimal("39426.00")
    assert t1.input_vat == Decimal("0.00")   # personnel costs carry no VAT

    with pytest.raises(DomainError) as exc:
        emp.mark_paid(db, slip, date(2026, 6, 1))
    assert exc.value.key == "emp.already_paid"


def test_paid_period_blocks_second_slip(db):
    e = _employee(db)
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    emp.mark_paid(db, slip, date(2026, 5, 28))
    db.commit()
    with pytest.raises(DomainError) as exc:
        emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    assert exc.value.key == "emp.period_paid_exists"


def test_rates_come_from_settings_not_code(db):
    p = ensure_tax_parameters(db)
    p.ag_rate_default = Decimal("25.00")
    db.commit()
    e = _employee(db)
    slip = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("0"))
    db.commit()
    assert slip.employer_contributions == Decimal("7500.00")   # 30000 × 25 %
    assert slip.ag_rate_used == Decimal("25.00")


def test_zero_employees_app_state(db):
    assert db.query(Employee).count() == 0
    assert emp.employee_summary(db, _employee(db))["slips"] == []
