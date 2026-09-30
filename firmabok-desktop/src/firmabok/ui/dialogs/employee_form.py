"""Employee & salary slip dialogs (feature E)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
)

from ...core import employees as emp
from ...core.errors import DomainError
from ...core.models import Employee, Vehicle
from ...core.money import ZERO, q2
from ...i18n import fmt, tr
from .. import theme
from ..widgets.forms import LabeledField, MoneyEdit, date_edit, date_of
from .forms import BaseDialog

_EMPTY_DATE = date(1900, 1, 2)


def _optional_date_edit(d: date | None):
    w = date_edit(d)
    w.setMinimumDate(QDate(_EMPTY_DATE.year, _EMPTY_DATE.month, _EMPTY_DATE.day))
    w.setSpecialValueText("—")
    if d is None:
        w.setDate(w.minimumDate())
    return w


def _optional_date_of(w) -> date | None:
    d = date_of(w)
    return None if d == _EMPTY_DATE else d


TYPE_KEYS = {
    "monthly": "Fast månadslön",
    "hourly": "Timlön",
    "revenue_pct": "Procent av omsättning",
    "contract": "Kontrakt (fritext)",
}


class EmployeeDialog(BaseDialog):
    def __init__(self, db, employee: Employee | None = None, parent=None):
        super().__init__("Lägg till anställd" if employee is None else "Redigera anställd", parent)
        self.db = db
        self.employee = employee
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.name = QLineEdit(employee.name if employee else "")
        self.f_name = LabeledField("Namn", self.name, required=True)
        self.pnr = QLineEdit(employee.personnummer if employee else "")
        self.f_pnr = LabeledField("Personnummer", self.pnr, help_key="personnummer.hint")
        self.addr = QLineEdit(employee.address_line1 if employee else "")
        self.f_addr = LabeledField("Adress", self.addr)
        self.postal = QLineEdit(employee.postal_code if employee else "")
        self.f_postal = LabeledField("Postnr", self.postal)
        self.city = QLineEdit(employee.city if employee else "")
        self.f_city = LabeledField("Ort", self.city)
        self.phone = QLineEdit(employee.phone if employee else "")
        self.f_phone = LabeledField("Telefon", self.phone)
        self.email = QLineEdit(employee.email if employee else "")
        self.f_email = LabeledField("E-post", self.email)

        self.type_cb = QComboBox()
        for value, key in TYPE_KEYS.items():
            self.type_cb.addItem(tr(key), value)
        if employee:
            i = self.type_cb.findData(employee.employment_type)
            if i >= 0:
                self.type_cb.setCurrentIndex(i)
        self.type_cb.currentIndexChanged.connect(self._toggle_type_fields)
        self.f_type = LabeledField("Anställningsform", self.type_cb, required=True)

        self.salary = MoneyEdit()
        if employee:
            self.salary.set_decimal(employee.monthly_salary)
        self.f_salary = LabeledField("Månadslön (kr)", self.salary)
        self.hourly = MoneyEdit()
        if employee:
            self.hourly.set_decimal(employee.hourly_rate)
        self.f_hourly = LabeledField("Timlön (kr/h)", self.hourly)
        self.pct = MoneyEdit()
        if employee:
            self.pct.set_decimal(employee.revenue_pct)
        self.f_pct = LabeledField("Procent av omsättning %", self.pct)
        self.terms = QTextEdit(employee.contract_terms if employee else "")
        self.terms.setMaximumHeight(56)
        self.f_terms = LabeledField("Kontraktsvillkor", self.terms)

        self.f_start = LabeledField("Startdatum", date_edit(employee.start_date if employee else None))
        self.f_end = LabeledField("Slutdatum (valfritt)",
                                  _optional_date_edit(employee.end_date if employee else None))
        self.f_birth = LabeledField("Födelsedatum (för ungdomsavgift)",
                                    _optional_date_edit(employee.birth_date if employee else None))
        self.tax_table = QLineEdit(employee.tax_table_note if employee else "")
        self.f_tax_table = LabeledField("Skattetabell / A-skattsedel", self.tax_table)
        self.bank = QLineEdit(employee.bank_account if employee else "")
        self.f_bank = LabeledField("Bankkonto", self.bank)
        self.ag_override = MoneyEdit()
        if employee and employee.ag_rate_override is not None:
            self.ag_override.set_decimal(employee.ag_rate_override)
        self.f_ag = LabeledField("Egen arbetsgivaravgift % (valfritt, annars standard)", self.ag_override)

        self.vehicle_cb = QComboBox()
        self.vehicle_cb.addItem(tr("— Ingen —"), 0)
        for v in db.query(Vehicle).order_by(Vehicle.label).all():
            self.vehicle_cb.addItem(v.label, v.id)
        if employee and employee.vehicle_id:
            i = self.vehicle_cb.findData(employee.vehicle_id)
            if i >= 0:
                self.vehicle_cb.setCurrentIndex(i)
        self.f_vehicle = LabeledField("Tilldelat fordon", self.vehicle_cb)

        rows = [(self.f_name, 0, 0), (self.f_pnr, 0, 1), (self.f_addr, 1, 0),
                (self.f_postal, 1, 1), (self.f_city, 2, 0), (self.f_phone, 2, 1),
                (self.f_email, 3, 0), (self.f_type, 3, 1), (self.f_salary, 4, 0),
                (self.f_hourly, 4, 1), (self.f_pct, 5, 0), (self.f_terms, 5, 1),
                (self.f_start, 6, 0), (self.f_end, 6, 1), (self.f_birth, 7, 0),
                (self.f_tax_table, 7, 1), (self.f_bank, 8, 0), (self.f_ag, 8, 1),
                (self.f_vehicle, 9, 0)]
        for w, r, c in rows:
            grid.addWidget(w, r, c)
        self._root.addLayout(grid)
        self._add_buttons()
        self._toggle_type_fields()
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "type_cb"):   # called from BaseDialog.__init__ pre-build
            return
        for i, key in enumerate(TYPE_KEYS.values()):
            self.type_cb.setItemText(i, tr(key))

    def _toggle_type_fields(self) -> None:
        t = self.type_cb.currentData()
        self.f_salary.setVisible(t == "monthly")
        self.f_hourly.setVisible(t == "hourly")
        self.f_pct.setVisible(t == "revenue_pct")
        self.f_terms.setVisible(t == "contract")

    def on_accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.f_name.set_error("Namn krävs.")
            return
        e = self.employee or Employee()
        e.name = name
        e.personnummer = self.pnr.text().strip()
        e.address_line1 = self.addr.text().strip()
        e.postal_code = self.postal.text().strip()
        e.city = self.city.text().strip()
        e.phone = self.phone.text().strip()
        e.email = self.email.text().strip()
        e.employment_type = self.type_cb.currentData()
        e.monthly_salary = self.salary.decimal() or ZERO
        e.hourly_rate = self.hourly.decimal() or ZERO
        e.revenue_pct = self.pct.decimal() or ZERO
        e.contract_terms = self.terms.toPlainText().strip()
        e.start_date = date_of(self.f_start.widget)
        e.end_date = _optional_date_of(self.f_end.widget)
        e.birth_date = _optional_date_of(self.f_birth.widget)
        e.tax_table_note = self.tax_table.text().strip()
        e.bank_account = self.bank.text().strip()
        e.ag_rate_override = self.ag_override.decimal()
        e.vehicle_id = self.vehicle_cb.currentData() or None
        self.result_employee = e
        self.accept()


class SalarySlipDialog(BaseDialog):
    """Create a salary slip draft for one employee and period."""

    def __init__(self, db, employee: Employee, parent=None,
                 year: int | None = None, month: int | None = None):
        super().__init__("Skapa lönespec", parent)
        self.db = db
        self.employee = employee
        today = date.today()
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(year or today.year)
        self.month_cb = QComboBox()
        from ...i18n import month_name
        for m in range(1, 13):
            self.month_cb.addItem(month_name(m), m)
        self.month_cb.setCurrentIndex((month or today.month) - 1)
        self.f_year = LabeledField("År", self.year_spin)
        self.f_month = LabeledField("Månad", self.month_cb)

        self.hours = MoneyEdit()
        self.f_hours = LabeledField("Timmar", self.hours)
        self.revenue = MoneyEdit()
        self.f_revenue = LabeledField("Omsättningsunderlag (kr)", self.revenue)
        if employee.employment_type == "revenue_pct":
            self.revenue.set_decimal(emp.month_revenue(db, self.year_spin.value(),
                                                       self.month_cb.currentData()))
        self.manual = MoneyEdit()
        self.f_manual = LabeledField("Bruttolön", self.manual)
        self.a_tax = MoneyEdit()
        self.f_a_tax = LabeledField("A-skatt (avdrag)", self.a_tax, required=True)

        self.extra_lbl = QLabel("")
        self.extra_rows: list[tuple[QLineEdit, MoneyEdit]] = []
        self.extra_host = QGridLayout()
        self.btn_add_extra = QPushButton(tr("Lägg till"))
        self.btn_add_extra.setProperty("kind", "ghost")
        self.btn_add_extra.setIcon(theme.icon("plus"))
        self.btn_add_extra.clicked.connect(self._add_extra_row)
        self.f_extra = LabeledField("Rader (tillägg/avdrag)", self._extra_host_widget())

        self.btn_preview = QPushButton(tr("Beräkna förhandsvisning"))
        self.btn_preview.setProperty("kind", "secondary")
        self.btn_preview.clicked.connect(self.preview)
        self.preview_lbl = QLabel("")
        self.preview_lbl.setWordWrap(True)

        for w, r, c in ((self.f_year, 0, 0), (self.f_month, 0, 1),
                        (self.f_hours, 1, 0), (self.f_revenue, 1, 1),
                        (self.f_manual, 2, 0), (self.f_a_tax, 2, 1),
                        (self.f_extra, 3, 0), (self.btn_add_extra, 3, 1)):
            grid.addWidget(w, r, c)
        grid.addWidget(self.btn_preview, 4, 0)
        grid.addWidget(self.preview_lbl, 5, 0, 1, 2)
        self._root.addLayout(grid)
        self._add_buttons()
        self._toggle_fields()
        self.year_spin.valueChanged.connect(self._toggle_fields)
        self.month_cb.currentIndexChanged.connect(self._toggle_fields)
        self.retranslate()

    def _extra_host_widget(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        self.extra_host = QGridLayout(host)
        self.extra_host.setContentsMargins(0, 0, 0, 0)
        return host

    def _add_extra_row(self) -> None:
        label = QLineEdit()
        amount = MoneyEdit()
        label.setPlaceholderText(tr("Rader (tillägg/avdrag)"))
        row = len(self.extra_rows)
        self.extra_host.addWidget(label, row, 0)
        self.extra_host.addWidget(amount, row, 1)
        self.extra_rows.append((label, amount))

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "btn_preview"):  # called from BaseDialog.__init__ pre-build
            return
        self.btn_preview.setText(tr("Beräkna förhandsvisning"))
        self.btn_add_extra.setText(tr("Lägg till"))
        self._toggle_fields()

    def _toggle_fields(self) -> None:
        t = self.employee.employment_type
        self.f_hours.setVisible(t == "hourly")
        self.f_revenue.setVisible(t == "revenue_pct")
        self.f_manual.setVisible(t == "contract")

    def _inputs(self):
        return dict(
            hours=self.hours.decimal(),
            revenue_base=self.revenue.decimal(),
            manual_gross=self.manual.decimal(),
            a_tax=self.a_tax.decimal() or ZERO,
            extra_lines=[{"label": le.text().strip(), "amount": str(me.decimal() or ZERO)}
                         for le, me in self.extra_rows if (me.decimal() or ZERO) != ZERO],
        )

    def preview(self) -> None:
        try:
            kw = self._inputs()
            gross = emp.compute_gross(self.db, self.employee, self.year_spin.value(),
                                      self.month_cb.currentData(),
                                      kw["hours"], kw["revenue_base"], kw["manual_gross"])
            extras = q2(sum((q2(Decimal(x["amount"])) for x in kw["extra_lines"]), ZERO))
            gross = q2(gross + extras)
            ag, rate, youth = emp.employer_contribution(
                self.db, self.employee, gross,
                date(self.year_spin.value(), self.month_cb.currentData(), 28))
            net = q2(gross - kw["a_tax"])
            self.preview_lbl.setText(
                f"{tr('Bruttolön')}: {fmt.money(gross)}  ·  "
                f"{tr('Arbetsgivaravgifter')} ({rate}%"
                + (f", {tr('Ungdomsavgift tillämpad')}" if youth else "") + f"): {fmt.money(ag)}  ·  "
                f"{tr('Nettolön')}: {fmt.money(net)}")
            self.f_a_tax.set_error(None)
        except DomainError as exc:
            self.preview_lbl.setText("")
            self.f_a_tax.set_error(exc.key)

    def on_accept(self) -> None:
        kw = self._inputs()
        try:
            slip = emp.create_slip(self.db, self.employee, self.year_spin.value(),
                                   self.month_cb.currentData(), **kw)
        except DomainError as exc:
            self.f_a_tax.set_error(exc.key)
            self.db.rollback()
            return
        self.result_slip = slip
        self.accept()
