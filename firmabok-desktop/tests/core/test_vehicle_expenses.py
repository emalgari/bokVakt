"""Feature B: vehicle expense categories, attribution, per-employee summaries."""
from datetime import date
from decimal import Decimal

import pytest

from conftest import make_expense
from firmabok.core import reports
from firmabok.core import vehicles as veh
from firmabok.core.migrate import seed_reference_data
from firmabok.core.models import Employee, Expense, ExpenseCategory, Vehicle

VEHICLE_CATEGORIES = [
    "Transportstyrelsen (fordonsskatter och avgifter)",
    "Trängselskatt & vägtullar",
    "Bränsle & laddning",
    "Bilfinansiering (leasing/avbetalning)",
    "Parkering",
    "Fordonsförsäkring",
    "Service & reparation",
    "Övriga fordonskostnader",
]


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(Vehicle).delete()
    db.query(Employee).delete()
    db.commit()
    yield
    db.query(Vehicle).delete()
    db.query(Employee).delete()
    db.commit()


def test_default_vehicle_categories_seeded_and_configurable(db):
    names = {c.name for c in db.query(ExpenseCategory).all()}
    for cat in VEHICLE_CATEGORIES:
        assert cat in names, f"default category missing: {cat}"
    # configurable: rename + add + remove
    c = db.query(ExpenseCategory).filter_by(name="Parkering").one()
    c.name = "Parkering & garage"
    db.add(ExpenseCategory(name="Min egen kategori"))
    db.commit()
    names = {c.name for c in db.query(ExpenseCategory).all()}
    assert "Parkering & garage" in names and "Min egen kategori" in names
    db.query(ExpenseCategory).filter_by(name="Min egen kategori").delete()
    db.commit()
    assert "Min egen kategori" not in {c.name for c in db.query(ExpenseCategory).all()}
    # seeding again is idempotent and does not resurrect renames
    seed_reference_data(db)
    db.commit()
    names = {c.name for c in db.query(ExpenseCategory).all()}
    assert "Parkering & garage" in names


@pytest.mark.parametrize("cat", VEHICLE_CATEGORIES)
def test_each_vehicle_category_vat_correct(db, cat):
    make_expense(db, date(2026, 5, 10), "1250.00", category_name=cat, supplier="Leverantör X")
    x = db.query(Expense).one()
    assert x.category_name == cat
    assert x.gross_amount == Decimal("1250.00")
    assert x.net_amount == Decimal("1000.00")
    assert x.vat_amount == Decimal("250.00")
    assert x.deductible_vat == Decimal("250.00")
    db.query(Expense).delete()
    db.commit()


def test_vehicle_expense_flows_into_totals(db):
    v = Vehicle(label="Testbil 1", reg_no="ABC123")
    db.add(v)
    db.commit()
    make_expense(db, date(2026, 6, 1), "1250.00", category_name="Bränsle & laddning",
                 vehicle_id=v.id, mileage=Decimal("12.5"))
    t = reports.compute_totals(db, date(2026, 1, 1), date(2026, 12, 31))
    assert t.expense_cost == Decimal("1000.00")   # gross − deductible VAT
    assert t.input_vat == Decimal("250.00")


def test_employee_car_costs_attribution(db):
    e = Employee(name="Test Förare")
    v = Vehicle(label="Taxi 7", reg_no="XYZ999", assigned_employee_id=None)
    db.add_all([e, v])
    db.commit()
    v.assigned_employee_id = e.id
    db.commit()

    make_expense(db, date(2026, 3, 1), "1250.00", category_name="Bränsle & laddning",
                 vehicle_id=v.id, mileage=Decimal("10"))
    make_expense(db, date(2026, 3, 5), "250.00", category_name="Trängselskatt & vägtullar",
                 code="NON_DEDUCTIBLE_P", deductible=0, employee_id=e.id)   # direct attribution
    make_expense(db, date(2026, 4, 5), "500.00", category_name="Parkering")  # outside period & unattributed

    agg = veh.employee_car_costs(db, e.id, date(2026, 3, 1), date(2026, 3, 31))
    assert agg["count"] == 2
    assert agg["total_cost"] == Decimal("1000.00") + Decimal("250.00")
    assert agg["input_vat"] == Decimal("250.00")
    assert agg["mileage"] == Decimal("10.00")
    assert agg["by_category"]["Bränsle & laddning"] == Decimal("1000.00")
    assert agg["by_category"]["Trängselskatt & vägtullar"] == Decimal("250.00")

    vag = veh.vehicle_costs(db, v.id, date(2026, 3, 1), date(2026, 3, 31))
    assert vag["count"] == 1 and vag["total_cost"] == Decimal("1000.00")


def test_zero_employees_zero_vehicles_is_valid(db):
    assert veh.employee_car_costs(db, 999, date(2026, 1, 1), date(2026, 12, 31))["count"] == 0
    assert veh.vehicles_for_employee(db, 999) == []
