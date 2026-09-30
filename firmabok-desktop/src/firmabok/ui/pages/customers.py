"""Customers page."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout
from sqlalchemy import select

from ...core import audit
from ...core.models import Customer, IncomeEntry, Invoice
from ...i18n import tr
from .. import theme
from ..dialogs.forms import CustomerDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable

COLUMNS = [("Namn", "l"), ("Kundnr", "l"), ("Org.nr", "l"), ("Ort", "l"),
           ("Land", "l"), ("Referens", "l"), ("E-post", "l")]


class CustomersPage(Translatable):
    page_id = "customers"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Kunder")
        self.btn_new = QPushButton(tr("Ny kund"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_customer)
        self.header.add_action(self.btn_new)
        lay.addWidget(self.header)

        self.table = DataTable(COLUMNS, empty_key="Inga kunder ännu.",
                               empty_cta="Lägg upp första kunden →", on_empty_cta=self.new_customer)
        self.table.table.doubleClicked.connect(lambda _: self.edit_customer())
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_edit = QPushButton(tr("Redigera"))
        self.btn_edit.setProperty("kind", "ghost")
        self.btn_edit.setIcon(theme.icon("pencil"))
        self.btn_edit.clicked.connect(self.edit_customer)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_customer)
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_new.setText(tr("Ny kund"))
        self.btn_edit.setText(tr("Redigera"))
        self.btn_delete.setText(tr("Radera"))
        self.reload()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            self._customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
            self.table.clear_rows()
            for c in self._customers:
                self.table.add_row([c.name, c.customer_no, c.org_nr, c.city,
                                    c.country, c.reference, c.email])
            self.table.refresh_empty_state()
            self.table.resize_columns()
        finally:
            db.close()

    def _selected(self) -> Customer | None:
        row = self.table.selected_row()
        return self._customers[row] if 0 <= row < len(self._customers) else None

    def new_customer(self) -> None:
        db = self.ctx.session()
        try:
            dlg = CustomerDialog(db, None, self.window())
            if dlg.exec() and getattr(dlg, "result_customer", None):
                c = dlg.result_customer
                db.add(c)
                db.flush()
                audit.log(db, "desktop", "create", "Customer", c.id, summary=c.name)
                db.commit()
                self.ctx.toast(tr("Kund sparad") + f": {c.name}", "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def edit_customer(self) -> None:
        c = self._selected()
        if not c:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(c)
            dlg = CustomerDialog(db, merged, self.window())
            if dlg.exec():
                before = audit.snapshot(merged)
                for k, v in audit.snapshot(dlg.result_customer).items():
                    setattr(merged, k, v)
                changes = audit.diff(before, merged)
                if changes:
                    audit.log(db, "desktop", "update", "Customer", merged.id,
                              summary=merged.name, changes=changes)
                db.commit()
                self.ctx.toast(tr("Kund uppdaterad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def delete_customer(self) -> None:
        c = self._selected()
        if not c:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(c)
            has_inv = db.execute(select(Invoice.id).where(Invoice.customer_id == merged.id).limit(1)).first()
            has_inc = db.execute(select(IncomeEntry.id).where(IncomeEntry.customer_id == merged.id).limit(1)).first()
            if has_inv or has_inc:
                self.ctx.toast(tr("Kunden har fakturor/intäkter och kan inte raderas "
                                  "(bokföringshistorik ska bevaras)."), "warning")
                return
            if not self.ctx.confirm("Radera kunden?"):
                return
            audit.log(db, "desktop", "delete", "Customer", merged.id, summary=merged.name,
                      changes={"row": audit.snapshot(merged)})
            db.delete(merged)
            db.commit()
            self.ctx.toast(tr("Kund raderad."), "success")
            self.reload()
        finally:
            db.close()
