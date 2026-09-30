"""Employees page (feature E): staff list, salary slips, per-employee car costs.

Stays fully usable with ZERO employees (empty state with CTA) — the payroll
feature is effectively dormant until the first employee is added.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy import select

from ...core import audit
from ...core import employees as emp
from ...core import pdf as core_pdf
from ...core import vehicles as veh
from ...core.invoices import get_profile
from ...core.models import Employee, Expense, SalarySlip, Vehicle
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, tr
from .. import theme
from ..dialogs.employee_form import TYPE_KEYS, EmployeeDialog, SalarySlipDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable
from ..workers import Worker

EMP_COLUMNS = [
    ("Namn", "l"), ("Anställningsform", "l"), ("Startdatum", "l"),
    ("Personnummer", "l"), ("Tilldelat fordon", "l"),
]
SLIP_COLUMNS = [
    ("Nr", "l"), ("Löneperiod", "l"), ("Bruttolön", "r"), ("Arbetsgivaravgifter", "r"),
    ("A-skatt (avdrag)", "r"), ("Nettolön", "r"), ("Status", "l"), ("Utbetalningsdatum", "l"),
]


class EmployeesPage(Translatable):
    page_id = "employees"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.header = PageHeader("Anställda")
        self.btn_new = QPushButton(tr("Lägg till anställd"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_employee)
        self.header.add_action(self.btn_new)
        lay.addWidget(self.header)

        self.empty_note = QLabel("")
        self.empty_note.setWordWrap(True)
        self.empty_note.setObjectName("muted")
        lay.addWidget(self.empty_note)

        self.table = DataTable(EMP_COLUMNS, empty_key="employees.empty",
                               empty_cta="employees.empty_cta", on_empty_cta=self.new_employee)
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_edit = QPushButton(tr("Redigera"))
        self.btn_edit.setProperty("kind", "ghost")
        self.btn_edit.setIcon(theme.icon("pencil"))
        self.btn_edit.clicked.connect(self.edit_employee)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_employee)
        self.btn_slip = QPushButton(tr("Skapa lönespec"))
        self.btn_slip.setProperty("kind", "secondary")
        self.btn_slip.setIcon(theme.icon("file-text"))
        self.btn_slip.clicked.connect(self.new_slip)
        self.btn_pay = QPushButton(tr("Markera som utbetald & bokförd"))
        self.btn_pay.setProperty("kind", "secondary")
        self.btn_pay.setIcon(theme.icon("check"))
        self.btn_pay.clicked.connect(self.pay_slip)
        self.btn_pdf = QPushButton(tr("Öppna PDF"))
        self.btn_pdf.setProperty("kind", "ghost")
        self.btn_pdf.setIcon(theme.icon("download"))
        self.btn_pdf.clicked.connect(self.export_pdf)
        for b in (self.btn_edit, self.btn_delete, self.btn_slip, self.btn_pay, self.btn_pdf):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        # ---- slips for selected employee ----
        self.slips_card = Card("Lönespecifikationer")
        self.slips_table = DataTable(SLIP_COLUMNS, empty_key="Inga lönespecifikationer ännu.",
                                     sortable=False)
        self.slips_card.body.addWidget(self.slips_table)
        lay.addWidget(self.slips_card, 1)

        # ---- car cost summary for selected employee ----
        car_row = QHBoxLayout()
        self.car_title = QLabel("")
        self.car_title.setStyleSheet("font-weight:600;")
        self.car_year = QSpinBox()
        self.car_year.setRange(2000, 2100)
        self.car_year.valueChanged.connect(self.reload)
        self.car_btn = QPushButton(tr("Beräkna"))
        self.car_btn.setProperty("kind", "secondary")
        self.car_btn.clicked.connect(self.reload)
        car_row.addWidget(self.car_title)
        car_row.addStretch(1)
        car_row.addWidget(self.car_year)
        car_row.addWidget(self.car_btn)
        self.car_card = Card("")
        self.car_card.body.addLayout(car_row)
        self.car_lbl = QLabel("")
        self.car_lbl.setWordWrap(True)
        self.car_card.body.addWidget(self.car_lbl)
        lay.addWidget(self.car_card)

        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_new.setText(tr("Lägg till anställd"))
        self.btn_edit.setText(tr("Redigera"))
        self.btn_delete.setText(tr("Radera"))
        self.btn_slip.setText(tr("Skapa lönespec"))
        self.btn_pay.setText(tr("Markera som utbetald & bokförd"))
        self.btn_pdf.setText(tr("Öppna PDF"))
        self.car_title.setText(tr("car.summary"))
        self.car_btn.setText(tr("Beräkna"))
        self.empty_note.setText(tr("employees.empty"))
        self.reload()

    # ----------------------------------------------------------------- data
    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.car_year.value() < 2001:
                self.car_year.blockSignals(True)
                self.car_year.setValue(
                    fiscal_year_of(today, profile.fiscal_year_start_month))
                self.car_year.blockSignals(False)
            emps = db.execute(select(Employee).order_by(Employee.name)).scalars().all()
            self._emps = emps
            vlabels = {v.id: v.label for v in db.execute(select(Vehicle)).scalars()}
            self.table.clear_rows()
            for e in emps:
                self.table.add_row([
                    e.name, tr(TYPE_KEYS.get(e.employment_type, e.employment_type)),
                    fmt.date(e.start_date) if e.start_date else "",
                    emp.mask_personnummer(e.personnummer),
                    vlabels.get(e.vehicle_id, "")])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            self._reload_slips()
            self._reload_car()
        finally:
            db.close()

    def _selected_employee(self) -> Employee | None:
        row = self.table.selected_row()
        return self._emps[row] if 0 <= row < len(self._emps) else None

    def _reload_slips(self) -> None:
        db = self.ctx.session()
        try:
            e = self._selected_employee()
            self._slips: list[SalarySlip] = []
            self.slips_table.clear_rows()
            if e is None:
                return
            slips = db.execute(
                select(SalarySlip).where(SalarySlip.employee_id == e.id)
                .order_by(SalarySlip.period_year.desc(), SalarySlip.period_month.desc(),
                          SalarySlip.id.desc())).scalars().all()
            self._slips = slips
            for s in slips:
                self.slips_table.add_row([
                    s.number, emp.period_label(s),
                    fmt.money(s.gross, symbol=False),
                    fmt.money(s.employer_contributions, symbol=False),
                    fmt.money(s.a_tax, symbol=False), fmt.money(s.net, symbol=False),
                    tr("Utbetald") if s.status == "paid" else tr("Utkast"),
                    fmt.date(s.paid_date) if s.paid_date else ""])
            self.slips_table.refresh_empty_state()
        finally:
            db.close()

    def _reload_car(self) -> None:
        db = self.ctx.session()
        try:
            e = self._selected_employee()
            if e is None:
                self.car_lbl.setText("")
                return
            profile = get_profile(db)
            start, end = fiscal_year_bounds(self.car_year.value(),
                                            profile.fiscal_year_start_month)
            agg = veh.employee_car_costs(db, e.id, start, end)
            parts = [f"{cat}: {fmt.money(amount)}" for cat, amount in
                     sorted(agg["by_category"].items())]
            self.car_lbl.setText(
                f"{tr('car.total')}: {fmt.money(agg['total_cost'])}  ·  "
                f"{tr('Ingående moms')}: {fmt.money(agg['input_vat'])}  ·  "
                f"{tr('Körsträcka (mil)')}: {agg['mileage']}\n" + ("  |  ".join(parts)))
        finally:
            db.close()

    def _selected_slip(self) -> SalarySlip | None:
        row = self.slips_table.selected_row()
        return self._slips[row] if 0 <= row < len(self._slips) else None

    # -------------------------------------------------------------- actions
    def new_employee(self) -> None:
        db = self.ctx.session()
        try:
            dlg = EmployeeDialog(db, None, self.window())
            if dlg.exec() and getattr(dlg, "result_employee", None) is not None:
                e = dlg.result_employee
                db.add(e)
                db.flush()
                audit.log(db, "desktop", "create", "Employee", e.id, summary=e.name)
                db.commit()
                self.ctx.toast(tr("Anställd sparad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def edit_employee(self) -> None:
        e = self._selected_employee()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            dlg = EmployeeDialog(db, merged, self.window())
            if dlg.exec():
                before = audit.snapshot(merged)
                for k, v in audit.snapshot(dlg.result_employee).items():
                    setattr(merged, k, v)
                changes = audit.diff(before, merged)
                if changes:
                    audit.log(db, "desktop", "update", "Employee", merged.id,
                              summary="changed", changes=changes)
                db.commit()
                self.ctx.toast(tr("Anställd sparad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def delete_employee(self) -> None:
        e = self._selected_employee()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            if db.query(SalarySlip).filter_by(employee_id=merged.id).count():
                self.ctx.toast(tr("Lönespecifikationer kan inte raderas "
                                  "(nummerserien är löpande). Korrigera med en ny spec vid behov."),
                               "warning")
                db.rollback()
                return
            if not self.ctx.confirm("Radera anställd?"):
                db.rollback()
                return
            db.query(Expense).filter_by(employee_id=merged.id).update({"employee_id": None})
            db.query(Vehicle).filter_by(assigned_employee_id=merged.id).update(
                {"assigned_employee_id": None})
            audit.log(db, "desktop", "delete", "Employee", merged.id,
                      summary=merged.name, changes={"row": audit.snapshot(merged)})
            db.delete(merged)
            db.commit()
            self.ctx.toast(tr("Anställd raderad."), "success")
            self.reload()
        finally:
            db.close()

    def new_slip(self) -> None:
        e = self._selected_employee()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            dlg = SalarySlipDialog(db, merged, self.window())
            if dlg.exec() and getattr(dlg, "result_slip", None) is not None:
                audit.log(db, "desktop", "create", "SalarySlip", dlg.result_slip.id,
                          summary=f"{dlg.result_slip.number} {merged.name}")
                db.commit()
                self.ctx.toast(tr("Lönespec skapad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def pay_slip(self) -> None:
        s = self._selected_slip()
        if not s:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(s)
            if merged.status == "paid":
                self.ctx.toast(tr("Redan utbetald."), "info")
                db.rollback()
                return
            paid_date = date.today()
            expense = emp.mark_paid(db, merged, paid_date)
            audit.log(db, "desktop", "update", "SalarySlip", merged.id,
                      summary=f"paid {paid_date}", changes={"expense_id": expense.id})
            db.commit()
            self.ctx.toast(tr("Lönespec markerad som utbetald — lönekostnad bokförd som utgift."),
                           "success")
            self.reload()
        finally:
            db.close()

    def export_pdf(self) -> None:
        s = self._selected_slip()
        if not s:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        slip_id = s.id
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera PDF"), f"lonespec-{s.number}.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.btn_pdf.setEnabled(False)

        def _job(p):
            db = self.ctx.session()
            try:
                data = core_pdf.render_salary_slip_pdf(db, slip_id)
                with open(p, "wb") as f:
                    f.write(data)
                return p
            finally:
                db.close()

        w = Worker(_job, path)
        w.finished.connect(lambda p: (self.btn_pdf.setEnabled(True),
                                      self.ctx.toast(tr("PDF sparad") + f": {p}", "success")))
        w.failed.connect(lambda e: (self.btn_pdf.setEnabled(True),
                                    self.ctx.toast(f"{tr('Export misslyckades')}: {e}", "error")))
        w.start()
        self._pdf_worker = w
