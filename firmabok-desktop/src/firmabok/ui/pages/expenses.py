"""Expenses page: list, filters, CRUD, receipt viewer."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy import extract, or_, select

from ...core import audit
from ...core import config as core_config
from ...core.invoices import get_profile
from ...core.models import Employee, Expense, ExpenseCategory, Vehicle
from ...core.money import ZERO, sum_money
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, tr
from .. import theme
from ..dialogs.forms import ExpenseDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable

COLUMNS = [
    ("Datum", "l"), ("Leverantör", "l"), ("Kategori", "l"), ("Beskrivning", "l"),
    ("Fordon", "l"), ("Anställd", "l"),
    ("Moms", "l"), ("Exkl.", "r"), ("Moms kr", "r"), ("Avdragsgill", "r"),
    ("Inkl.", "r"), ("Kostnad*", "r"), ("Kvitto", "c"),
]


class ExpensesPage(Translatable):
    page_id = "expenses"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Utgifter")
        self.btn_new = QPushButton(tr("Ny utgift"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_entry)
        self.header.add_action(self.btn_new)
        lay.addWidget(self.header)

        filters = QHBoxLayout()
        self.year_spin = QSpinBox(); self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        self.month_cb = QComboBox()
        self.cat_cb = QComboBox()
        self.search = QLineEdit(); self.search.setPlaceholderText(tr("Sök"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        self.vehicle_cb = QComboBox()
        self.vehicle_cb.addItem(tr("Alla fordon"), 0)
        for w in (self.year_spin, self.month_cb, self.cat_cb, self.vehicle_cb, self.search):
            filters.addWidget(w)
        filters.addStretch(1)
        self.month_cb.currentIndexChanged.connect(self.reload)
        self.cat_cb.currentIndexChanged.connect(self.reload)
        self.vehicle_cb.currentIndexChanged.connect(self.reload)
        lay.addLayout(filters)

        self.table = DataTable(COLUMNS, empty_key="Inga utgifter för filtret.",
                               empty_cta="Registrera utgift", on_empty_cta=self.new_entry)
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_receipt = QPushButton(tr("Visa kvitto"))
        self.btn_receipt.setProperty("kind", "secondary")
        self.btn_receipt.setIcon(theme.icon("paperclip"))
        self.btn_receipt.clicked.connect(self.show_receipt)
        self.btn_edit = QPushButton(tr("Redigera"))
        self.btn_edit.setProperty("kind", "ghost")
        self.btn_edit.setIcon(theme.icon("pencil"))
        self.btn_edit.clicked.connect(self.edit_entry)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_entry)
        for b in (self.btn_receipt, self.btn_edit, self.btn_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        self.totals_lbl = QLabel("")
        self.totals_lbl.setStyleSheet("font-weight:600;")
        actions.addWidget(self.totals_lbl)
        lay.addLayout(actions)
        note = QLabel(tr("Kostnad = belopp inkl. moms − avdragsgill moms. Icke avdragsgill moms "
                         "blir en del av kostnaden."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        self._note = note
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_new.setText(tr("Ny utgift"))
        self.btn_receipt.setText(tr("Visa kvitto"))
        self.btn_edit.setText(tr("Redigera"))
        self.btn_delete.setText(tr("Radera"))
        self.search.setPlaceholderText(tr("Sök"))
        self.vehicle_cb.setItemText(0, tr("Alla fordon"))
        self._note.setText(tr("Kostnad = belopp inkl. moms − avdragsgill moms. Icke avdragsgill moms "
                              "blir en del av kostnaden."))
        self._fill_filters(keep=True)
        self.reload()

    def _fill_filters(self, keep: bool = False) -> None:
        db = self.ctx.session()
        try:
            month_cur = self.month_cb.currentData() if keep and self.month_cb.count() else 0
            cat_cur = self.cat_cb.currentData() if keep and self.cat_cb.count() else ""
            veh_cur = self.vehicle_cb.currentData() if keep and self.vehicle_cb.count() else 0
            self.month_cb.blockSignals(True); self.cat_cb.blockSignals(True)
            self.vehicle_cb.blockSignals(True)
            self.month_cb.clear(); self.cat_cb.clear(); self.vehicle_cb.clear()
            from ...i18n import month_name
            self.month_cb.addItem(tr("Hela året"), 0)
            for m in range(1, 13):
                self.month_cb.addItem(month_name(m), m)
            self.cat_cb.addItem(tr("Alla"), "")
            for c in db.query(ExpenseCategory).order_by(ExpenseCategory.name).all():
                self.cat_cb.addItem(c.name, c.name)
            self.vehicle_cb.addItem(tr("Alla fordon"), 0)
            for v in db.query(Vehicle).order_by(Vehicle.label).all():
                self.vehicle_cb.addItem(v.label, v.id)
            self.month_cb.setCurrentIndex(max(0, self.month_cb.findData(month_cur)))
            self.cat_cb.setCurrentIndex(max(0, self.cat_cb.findData(cat_cur)))
            self.vehicle_cb.setCurrentIndex(max(0, self.vehicle_cb.findData(veh_cur)))
            self.month_cb.blockSignals(False); self.cat_cb.blockSignals(False)
            self.vehicle_cb.blockSignals(False)
        finally:
            db.close()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.year_spin.value() < 2001:
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(fiscal_year_of(today, profile.fiscal_year_start_month))
                self.year_spin.blockSignals(False)
            fy = self.year_spin.value()
            if self.month_cb.count() == 0:
                self._fill_filters()
            start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
            stmt = select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
            month = self.month_cb.currentData() or 0
            if month:
                stmt = stmt.where(extract("month", Expense.expense_date) == month)
            cat = self.cat_cb.currentData()
            if cat:
                stmt = stmt.where(Expense.category_name == cat)
            vid = self.vehicle_cb.currentData() or 0
            if vid:
                stmt = stmt.where(Expense.vehicle_id == vid)
            q = self.search.text().strip()
            if q:
                like = f"%{q}%"
                stmt = stmt.where(or_(Expense.supplier.ilike(like), Expense.description.ilike(like)))
            expenses = db.execute(stmt.order_by(Expense.expense_date.desc(),
                                                Expense.id.desc())).scalars().all()
            self._expenses = expenses
            vlabels = {v.id: v.label for v in db.execute(select(Vehicle)).scalars()}
            enames = {e.id: e.name for e in db.execute(select(Employee)).scalars()}
            self.table.clear_rows()
            for x in expenses:
                deductible = min(x.deductible_vat or ZERO, x.vat_amount or ZERO)
                self.table.add_row([
                    fmt.date(x.expense_date), x.supplier, x.category_name, x.description,
                    vlabels.get(x.vehicle_id, ""), enames.get(x.employee_id, ""),
                    f"{x.vat_code} {x.vat_rate}%",
                    fmt.money(x.net_amount, symbol=False), fmt.money(x.vat_amount, symbol=False),
                    fmt.money(deductible, symbol=False), fmt.money(x.gross_amount, symbol=False),
                    fmt.money(x.book_cost, symbol=False),
                    "📎" if x.receipt_path else "—"])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            self.totals_lbl.setText(
                f"{tr('Summa')}: {fmt.money(sum_money(x.book_cost for x in expenses))} "
                f"({tr('Kostnad')}) · {fmt.money(sum_money(min(x.deductible_vat or ZERO, x.vat_amount or ZERO) for x in expenses))} "
                f"({tr('Avdragsgill moms')})")
        finally:
            db.close()

    def _selected(self) -> Expense | None:
        row = self.table.selected_row()
        return self._expenses[row] if 0 <= row < len(self._expenses) else None

    def new_entry(self) -> None:
        db = self.ctx.session()
        try:
            dlg = ExpenseDialog(db, None, self.window())
            if dlg.exec() and getattr(dlg, "result_expense", None) is not None:
                x = dlg.result_expense
                db.add(x)
                db.flush()
                audit.log(db, "desktop", "create", "Expense", x.id,
                          summary=f"{x.expense_date} {x.gross_amount} ({x.category_name})")
                db.commit()
                self.ctx.toast(tr("Utgift sparad") + f": {fmt.money(x.gross_amount)}", "success")
                self._fill_filters(keep=True)
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def edit_entry(self) -> None:
        x = self._selected()
        if not x:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(x)
            dlg = ExpenseDialog(db, merged, self.window())
            if dlg.exec():
                before = audit.snapshot(merged)
                for k, v in audit.snapshot(dlg.result_expense).items():
                    setattr(merged, k, v)
                changes = audit.diff(before, merged)
                if changes:
                    audit.log(db, "desktop", "update", "Expense", merged.id, summary="changed", changes=changes)
                db.commit()
                self.ctx.toast(tr("Utgift uppdaterad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def delete_entry(self) -> None:
        x = self._selected()
        if not x:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        if not self.ctx.confirm("Radera utgiften (och ev. kvitto)?"):
            return
        db = self.ctx.session()
        try:
            merged = db.merge(x)
            if merged.receipt_path:
                p = core_config.UPLOAD_DIR / merged.receipt_path
                if p.exists():
                    p.unlink()
            audit.log(db, "desktop", "delete", "Expense", merged.id,
                      summary=f"{merged.expense_date} {merged.gross_amount}",
                      changes={"row": audit.snapshot(merged)})
            db.delete(merged)
            db.commit()
            self.ctx.toast(tr("Utgift raderad."), "success")
            self.reload()
        finally:
            db.close()

    def show_receipt(self) -> None:
        x = self._selected()
        if not x or not x.receipt_path:
            self.ctx.toast(tr("Inget kvitto på vald rad."), "warning"); return
        p = core_config.UPLOAD_DIR / x.receipt_path
        if p.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
