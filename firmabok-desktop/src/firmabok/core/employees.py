"""Employees & salary slips (feature E) — pure Python, no Qt.

Design rules honoured here:
* No Swedish legal values are hardcoded: employer-contribution rates,
  youth reduction parameters, mileage etc. all come from ``TaxParameters``
  (user-editable) or per-employee overrides.
* Salary slips have their OWN sequential series per fiscal year, separate
  from invoice numbering. Slips are never deleted (sequential integrity);
  corrections are made with a new slip.
* Consistent with bokslutsmetoden elsewhere in the app, the personnel cost
  (gross salary + employer contributions) is booked as an expense ONLY when
  the slip is marked as paid, dated with the payment date.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from . import reports
from .errors import DomainError
from .migrate import ensure_tax_parameters
from .models import Employee, Expense, SalarySlip, SalarySlipSeries
from .money import ZERO, q2, sum_money
from .swedish import month_name_sv

EMPLOYMENT_TYPES = ("monthly", "hourly", "revenue_pct", "contract")
PAYROLL_CATEGORY = "Löner & personalkostnader"


def mask_personnummer(pnr: str) -> str:
    """Local-only storage; masked everywhere except the employee record itself."""
    pnr = (pnr or "").strip()
    if len(pnr) < 5:
        return pnr
    return "•" * (len(pnr) - 4) + pnr[-4:]


def slip_number(db: Session, fiscal_year: int) -> str:
    series = db.query(SalarySlipSeries).filter_by(series_year=fiscal_year).first()
    if series is None:
        series = SalarySlipSeries(series_year=fiscal_year, next_seq=1)
        db.add(series)
        db.flush()
    number = f"{fiscal_year}-{series.next_seq:04d}"
    series.next_seq += 1
    db.flush()
    return number


def employer_contribution(db: Session, employee: Employee, gross: Decimal,
                          pay_date: date) -> tuple[Decimal, Decimal, bool]:
    """Returns (amount, effective standard rate, youth_reduction_applied).

    Youth reduction (when enabled and the employee qualifies by birth year and
    payment date window) applies the reduced rate to salary up to the monthly
    ceiling and the standard rate to the excess — parameters are user-owned.
    """
    params = ensure_tax_parameters(db)
    std_rate = employee.ag_rate_override if employee.ag_rate_override is not None \
        else params.ag_rate_default
    gross = q2(gross)
    youth = False
    if (params.youth_enabled and employee.ag_rate_override is None
            and employee.birth_date is not None
            and params.youth_birth_from <= employee.birth_date.year <= params.youth_birth_to
            and params.youth_valid_from <= pay_date <= params.youth_valid_to):
        youth = True
        base = q2(min(gross, params.youth_ceiling))
        excess = q2(gross - base)
        amount = q2(q2(base * params.youth_rate / Decimal("100"))
                    + q2(excess * std_rate / Decimal("100")))
    else:
        amount = q2(gross * std_rate / Decimal("100"))
    return amount, q2(std_rate), youth


def month_revenue(db: Session, year: int, month: int) -> Decimal:
    """Net income (excl. VAT) for a calendar month — basis for %-of-revenue pay."""
    if month == 12:
        start, end = date(year, 12, 1), date(year, 12, 31)
    else:
        start, end = date(year, month, 1), date(year, month + 1, 1)
        from datetime import timedelta
        end = end - timedelta(days=1)
    return reports.compute_totals(db, start, end).net_income


def compute_gross(db: Session, employee: Employee, year: int, month: int,
                  hours: Decimal | None = None,
                  revenue_base: Decimal | None = None,
                  manual_gross: Decimal | None = None) -> Decimal:
    t = employee.employment_type
    if t == "monthly":
        return q2(employee.monthly_salary)
    if t == "hourly":
        if hours is None:
            raise DomainError("emp.hours_required")
        return q2(q2(hours) * employee.hourly_rate)
    if t == "revenue_pct":
        base = q2(revenue_base if revenue_base is not None
                  else month_revenue(db, year, month))
        return q2(base * employee.revenue_pct / Decimal("100"))
    # contract: employer-defined terms → manual amount required
    if manual_gross is None:
        raise DomainError("emp.manual_gross_required")
    return q2(manual_gross)


def create_slip(db: Session, employee: Employee, year: int, month: int,
                a_tax: Decimal, hours: Decimal | None = None,
                revenue_base: Decimal | None = None,
                manual_gross: Decimal | None = None,
                extra_lines: list[dict] | None = None,
                pay_date: date | None = None) -> SalarySlip:
    if not (1 <= month <= 12):
        raise DomainError("emp.bad_period")
    existing = db.query(SalarySlip).filter_by(
        employee_id=employee.id, period_year=year, period_month=month,
        status="paid").first()
    if existing is not None:
        raise DomainError("emp.period_paid_exists")

    if employee.employment_type == "revenue_pct" and revenue_base is None:
        revenue_base = month_revenue(db, year, month)
    gross = compute_gross(db, employee, year, month, hours, revenue_base, manual_gross)
    lines: list[dict] = []
    base_label = {
        "monthly": "Fast månadslön", "hourly": "Timlön",
        "revenue_pct": "Provision av omsättning", "contract": "Kontraktsenlig lön",
    }[employee.employment_type]
    lines.append({"label": base_label, "amount": str(gross)})
    for extra in (extra_lines or []):
        amt = q2(Decimal(str(extra.get("amount", "0"))))
        if amt:
            lines.append({"label": str(extra.get("label", ""))[:120] or "Justering",
                          "amount": str(amt)})
    gross = q2(sum_money(Decimal(ln["amount"]) for ln in lines))
    ref_date = pay_date or date(year, month, 28)
    ag, rate_used, youth = employer_contribution(db, employee, gross, ref_date)
    a_tax = q2(max(ZERO, Decimal(str(a_tax))))
    net = q2(gross - a_tax)

    slip = SalarySlip(
        number=slip_number(db, year), series_year=year,
        employee_id=employee.id, period_year=year, period_month=month,
        gross=gross, employer_contributions=ag, a_tax=a_tax, net=net,
        hours=hours, revenue_base=revenue_base,
        lines=json.dumps(lines, ensure_ascii=False),
        ag_rate_used=rate_used, youth_reduction=youth, status="draft")
    db.add(slip)
    db.flush()
    return slip


def slip_lines(slip: SalarySlip) -> list[dict]:
    try:
        data = json.loads(slip.lines or "[]")
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def period_label(slip: SalarySlip) -> str:
    return f"{month_name_sv(slip.period_month).capitalize()} {slip.period_year}"


def mark_paid(db: Session, slip: SalarySlip, paid_date: date,
              supplier_note: str = "") -> Expense:
    """Books the personnel cost (gross + employer contributions) as an expense
    on the payment date — consistent with the app's cash-method handling.
    The employee's withheld A-tax is NOT a business cost."""
    if slip.status == "paid":
        raise DomainError("emp.already_paid")
    employee = db.get(Employee, slip.employee_id)
    if employee is None:
        raise DomainError("emp.not_found")
    cost = q2(slip.gross + slip.employer_contributions)
    expense = Expense(
        expense_date=paid_date,
        supplier=employee.name[:200],
        category_name=PAYROLL_CATEGORY,
        description=(supplier_note or
                     f"Lönekostnad {period_label(slip)} – {employee.name}")[:300],
        vat_code="NON_DEDUCTIBLE_P",
        net_amount=cost, vat_rate=ZERO, vat_amount=ZERO, gross_amount=cost,
        deductible_vat=ZERO,
        payment_method="bank", payment_date=paid_date,
        employee_id=employee.id)
    db.add(expense)
    db.flush()
    slip.status = "paid"
    slip.paid_date = paid_date
    slip.expense_id = expense.id
    db.flush()
    return expense


def employee_summary(db: Session, employee: Employee) -> dict:
    paid = db.query(SalarySlip).filter_by(employee_id=employee.id, status="paid").all()
    return {
        "slips": paid,
        "total_gross": q2(sum_money(s.gross for s in paid)),
        "total_ag": q2(sum_money(s.employer_contributions for s in paid)),
        "total_net": q2(sum_money(s.net for s in paid)),
    }
