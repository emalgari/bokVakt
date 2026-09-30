"""Vehicle cost aggregation (pure Python, no Qt).

Costs always use the existing rule: book cost = gross − deductible VAT, so
summaries here match ``reports.compute_totals`` exactly. Attribution: an
expense counts for an employee when it is directly attributed (expense.employee_id)
OR charged to a vehicle assigned to that employee (vehicle.assigned_employee_id).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Employee, Expense, Vehicle
from .money import ZERO, q2


def _expense_query(db: Session, start: date, end: date,
                   vehicle_id: int | None = None, employee_id: int | None = None):
    q = (select(Expense)
         .where(Expense.expense_date >= start, Expense.expense_date <= end))
    if vehicle_id is not None:
        q = q.where(Expense.vehicle_id == vehicle_id)
    if employee_id is not None:
        vehicle_ids = [v.id for v in db.execute(
            select(Vehicle).where(Vehicle.assigned_employee_id == employee_id)).scalars()]
        conds = [Expense.employee_id == employee_id]
        if vehicle_ids:
            conds.append(Expense.vehicle_id.in_(vehicle_ids))
        q = q.where(or_(*conds))
    return q.order_by(Expense.expense_date, Expense.id)


def aggregate(db: Session, start: date, end: date,
              vehicle_id: int | None = None, employee_id: int | None = None) -> dict:
    rows = db.execute(_expense_query(db, start, end, vehicle_id, employee_id)).scalars().all()
    by_category: dict[str, Decimal] = {}
    total_cost = total_gross = input_vat = mileage = ZERO
    for x in rows:
        deductible = q2(min(x.deductible_vat or ZERO, x.vat_amount or ZERO))
        cost = q2((x.gross_amount or ZERO) - deductible)
        by_category[x.category_name] = q2(by_category.get(x.category_name, ZERO) + cost)
        total_cost = q2(total_cost + cost)
        total_gross = q2(total_gross + (x.gross_amount or ZERO))
        input_vat = q2(input_vat + deductible)
        if x.mileage:
            mileage = q2(mileage + x.mileage)
    return {
        "count": len(rows),
        "total_cost": total_cost,
        "total_gross": total_gross,
        "input_vat": input_vat,
        "mileage": mileage,
        "by_category": by_category,
        "rows": rows,
    }


def vehicle_costs(db: Session, vehicle_id: int, start: date, end: date) -> dict:
    return aggregate(db, start, end, vehicle_id=vehicle_id)


def employee_car_costs(db: Session, employee_id: int, start: date, end: date) -> dict:
    return aggregate(db, start, end, employee_id=employee_id)


def vehicles_for_employee(db: Session, employee_id: int) -> list[Vehicle]:
    return list(db.execute(select(Vehicle).where(
        Vehicle.assigned_employee_id == employee_id).order_by(Vehicle.label)).scalars())


def employee_label(db: Session, employee_id: int | None) -> str:
    if not employee_id:
        return ""
    e = db.get(Employee, employee_id)
    return e.name if e else ""
