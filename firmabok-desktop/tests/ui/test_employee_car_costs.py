"""Feature F: employee car expenses attribution surfaced in the UI."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtWidgets import QMainWindow

from conftest import make_expense
from firmabok.core.models import Employee, Vehicle
from firmabok.i18n import i18n
from firmabok.ui.context import AppContext
from firmabok.ui.pages.employees import EmployeesPage


@pytest.fixture()
def page(qapp, qtbot, db):
    e = Employee(name="Bil Förare", employment_type="monthly",
                 monthly_salary=Decimal("20000"))
    db.add(e)
    db.commit()
    v = Vehicle(label="Taxi 1", reg_no="ABC123", assigned_employee_id=e.id)
    db.add(v)
    db.commit()
    make_expense(db, date(date.today().year, 2, 10), "1250.00",
                 category_name="Bränsle & laddning", vehicle_id=v.id,
                 employee_id=e.id, mileage=Decimal("15"))
    make_expense(db, date(date.today().year, 3, 1), "300.00",
                 category_name="Trängselskatt & vägtullar",
                 code="NON_DEDUCTIBLE_P", deductible=0, employee_id=e.id)

    win = QMainWindow()
    ctx = AppContext(win)
    p = EmployeesPage(ctx)
    p.table.table.selectRow(0)
    p._reload_car()
    qtbot.addWidget(p)
    yield p
    i18n.unsubscribe(p.retranslate)
    db.query(Vehicle).delete()
    db.query(Employee).delete()
    db.commit()
    win.deleteLater()


def test_car_summary_shows_attributed_costs(page):
    text = page.car_lbl.text().replace("\u00a0", " ")
    assert "1 300,00" in text   # 1000 (fuel) + 300 (congestion tax)
    assert "Bränsle & laddning" in text
    assert "Trängselskatt & vägtullar" in text
    assert "15" in text  # mileage total


def test_car_summary_translates(page):
    i18n.set_language("en")
    try:
        assert page.car_title.text() == "Car costs per employee"
    finally:
        i18n.set_language("sv")
    assert page.car_title.text() == "Bilkostnader per anställd"
