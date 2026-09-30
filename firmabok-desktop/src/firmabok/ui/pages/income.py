"""Income page: list, filters, CRUD, mark paid, create invoice."""
from __future__ import annotations

from datetime import date

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
from ...core.invoices import (
    get_profile,
    recalc_invoice,
)
from ...core.models import GigPlatform, IncomeEntry, Invoice, InvoiceLine, PaymentStatus
from ...core.money import q2, sum_money
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, tr
from .. import theme
from ..dialogs.forms import IncomeDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable

COLUMNS = [
    ("Datum", "l"), ("Kund", "l"), ("Beskrivning", "l"), ("Plattform", "l"), ("Momskod", "l"),
    ("Exkl. moms", "r"), ("Moms", "r"), ("Inkl. moms", "r"),
    ("Betalstatus", "c"), ("Faktura", "l"),
]


class IncomePage(Translatable):
    page_id = "income"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.header = PageHeader("Intäkter")
        self.btn_new = QPushButton(tr("Ny intäkt"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_entry)
        self.header.add_action(self.btn_new)
        lay.addWidget(self.header)

        filters = QHBoxLayout()
        self.year_spin = QSpinBox(); self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        self.month_cb = QComboBox()
        self.month_cb.addItem(tr("Hela året"), 0)
        self.status_cb = QComboBox()
        for value, key in (("", "Alla"), ("unpaid", "Obetald"), ("paid", "Betald"), ("partial", "Delbetald")):
            self.status_cb.addItem(tr(key), value)
        self.source_cb = QComboBox()
        self._fill_sources()
        self.source_cb.currentIndexChanged.connect(self.reload)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Sök"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        for w in (self.year_spin, self.month_cb, self.source_cb, self.status_cb, self.search):
            filters.addWidget(w)
        filters.addStretch(1)
        self.month_cb.currentIndexChanged.connect(self.reload)
        self.status_cb.currentIndexChanged.connect(self.reload)
        lay.addLayout(filters)

        self.table = DataTable(COLUMNS, empty_key="Inga intäkter för filtret.",
                               empty_cta="Registrera intäkt", on_empty_cta=self.new_entry)
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_paid = QPushButton(tr("Markera som betald"))
        self.btn_paid.setProperty("kind", "secondary")
        self.btn_paid.setIcon(theme.icon("check"))
        self.btn_paid.clicked.connect(self.mark_paid)
        self.btn_invoice = QPushButton(tr("Skapa fakturautkast från intäkten"))
        self.btn_invoice.setProperty("kind", "secondary")
        self.btn_invoice.setIcon(theme.icon("file-text"))
        self.btn_invoice.clicked.connect(self.create_invoice)
        self.btn_edit = QPushButton(tr("Redigera"))
        self.btn_edit.setProperty("kind", "ghost")
        self.btn_edit.setIcon(theme.icon("pencil"))
        self.btn_edit.clicked.connect(self.edit_entry)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_entry)
        for b in (self.btn_paid, self.btn_invoice, self.btn_edit, self.btn_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        self.totals_lbl = QLabel("")
        self.totals_lbl.setStyleSheet("font-weight:600;")
        actions.addWidget(self.totals_lbl)
        lay.addLayout(actions)
        self._actions = actions
        self.reload()

    # --------------------------------------------------------------- labels
    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_new.setText(tr("Ny intäkt"))
        self.btn_paid.setText(tr("Markera som betald"))
        self.btn_invoice.setText(tr("Skapa fakturautkast från intäkten"))
        self.btn_edit.setText(tr("Redigera"))
        self.btn_delete.setText(tr("Radera"))
        self.month_cb.setItemText(0, tr("Hela året"))
        for i, key in enumerate(("Alla", "Obetald", "Betald", "Delbetald")):
            self.status_cb.setItemText(i, tr(key))
        self.source_cb.setItemText(0, tr("Alla källor"))
        self.source_cb.setItemText(1, tr("Direkt kund"))
        self.source_cb.setItemText(2, tr("Alla plattformar"))
        self.search.setPlaceholderText(tr("Sök"))
        self.reload()

    def _fill_sources(self) -> None:
        current = self.source_cb.currentData() if self.source_cb.count() else ""
        self.source_cb.blockSignals(True)
        self.source_cb.clear()
        self.source_cb.addItem(tr("Alla källor"), "")
        self.source_cb.addItem(tr("Direkt kund"), "direct")
        self.source_cb.addItem(tr("Alla plattformar"), "*")
        db = self.ctx.session()
        try:
            for p in db.query(GigPlatform).order_by(GigPlatform.name).all():
                self.source_cb.addItem(p.name, p.name)
        finally:
            db.close()
        idx = self.source_cb.findData(current if current is not None else "")
        self.source_cb.setCurrentIndex(max(0, idx))
        self.source_cb.blockSignals(False)

    def _fill_months(self, current: int) -> None:
        self.month_cb.blockSignals(True)
        self.month_cb.clear()
        self.month_cb.addItem(tr("Hela året"), 0)
        from ...i18n import month_name
        for m in range(1, 13):
            self.month_cb.addItem(month_name(m), m)
        idx = self.month_cb.findData(current)
        self.month_cb.setCurrentIndex(idx if idx >= 0 else 0)
        self.month_cb.blockSignals(False)

    # ----------------------------------------------------------------- data
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
            if self.month_cb.count() == 1:
                self._fill_months(0)
            self._fill_sources()
            start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
            stmt = select(IncomeEntry).where(IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end)
            month = self.month_cb.currentData() or 0
            if month:
                stmt = stmt.where(extract("month", IncomeEntry.entry_date) == month)
            status = self.status_cb.currentData()
            if status:
                stmt = stmt.where(IncomeEntry.payment_status == status)
            source = self.source_cb.currentData()
            if source == "*":
                stmt = stmt.where(IncomeEntry.source_type == "platform")
            elif source == "direct":
                stmt = stmt.where(IncomeEntry.source_type == "direct")
            elif source:
                stmt = stmt.where(IncomeEntry.platform_name == source)
            q = self.search.text().strip()
            if q:
                like = f"%{q}%"
                stmt = stmt.where(or_(IncomeEntry.description.ilike(like),
                                      IncomeEntry.customer_name.ilike(like),
                                      IncomeEntry.invoice_ref.ilike(like)))
            entries = db.execute(stmt.order_by(IncomeEntry.entry_date.desc(),
                                               IncomeEntry.id.desc())).scalars().all()
            self._entries = entries
            self.table.clear_rows()
            status_keys = {"unpaid": "Obetald", "paid": "Betald", "partial": "Delbetald"}
            for e in entries:
                self.table.add_row([
                    fmt.date(e.entry_date), e.customer_name, e.description,
                    e.platform_name if e.source_type == "platform" else "",
                    f"{e.vat_code} {e.vat_rate}%",
                    fmt.money(e.net_amount, symbol=False), fmt.money(e.vat_amount, symbol=False),
                    fmt.money(e.gross_amount, symbol=False),
                    tr(status_keys.get(e.payment_status, e.payment_status)),
                    e.invoice_ref or ""])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            self.totals_lbl.setText(
                f"{tr('Summa')}: {fmt.money(sum_money(e.net_amount for e in entries))} "
                f"({tr('Exkl. moms')}) · {fmt.money(sum_money(e.vat_amount for e in entries))} "
                f"({tr('Moms')})")
        finally:
            db.close()

    def _selected(self) -> IncomeEntry | None:
        row = self.table.selected_row()
        return self._entries[row] if 0 <= row < len(self._entries) else None

    # -------------------------------------------------------------- actions
    def new_entry(self) -> None:
        db = self.ctx.session()
        try:
            dlg = IncomeDialog(db, None, self.window())
            if dlg.exec() and getattr(dlg, "result_entry", None) is not None:
                e = dlg.result_entry
                if e.id is None:
                    db.add(e)
                db.flush()
                audit.log(db, "desktop", "create" if e.id else "update", "IncomeEntry", e.id,
                          summary=f"{e.entry_date} {e.net_amount} ({e.vat_code})")
                db.commit()
                self.ctx.toast(tr("Intäkt sparad") + f": {fmt.money(e.net_amount)} "
                               + tr("exkl. moms"), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def edit_entry(self) -> None:
        e = self._selected()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        if e.invoice_id:
            self.ctx.toast(tr("Intäkten är länkad till en faktura och bör ändras via fakturan/kreditfaktura. "
                              "Ta bort länken först om du verkligen vill ändra här."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            dlg = IncomeDialog(db, merged, self.window())
            if dlg.exec():
                before = audit.snapshot(merged)
                for k, v in audit.snapshot(dlg.result_entry).items():
                    setattr(merged, k, v)
                changes = audit.diff(before, merged)
                if changes:
                    audit.log(db, "desktop", "update", "IncomeEntry", merged.id,
                              summary="changed", changes=changes)
                db.commit()
                self.ctx.toast(tr("Intäkt uppdaterad."), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def mark_paid(self) -> None:
        e = self._selected()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            merged.payment_status = PaymentStatus.PAID.value
            merged.payment_date = date.today()
            audit.log(db, "desktop", "update", "IncomeEntry", merged.id, summary="paid")
            db.commit()
            self.ctx.toast(tr("Markerad som betald."), "success")
            self.reload()
        finally:
            db.close()

    def delete_entry(self) -> None:
        e = self._selected()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        if e.invoice_id:
            self.ctx.toast(tr("Intäkten är länkad till faktura och kan inte raderas. Kreditera fakturan i stället."),
                           "warning")
            return
        if not self.ctx.confirm("Radera intäkten?"):
            return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            audit.log(db, "desktop", "delete", "IncomeEntry", merged.id,
                      summary=f"{merged.entry_date} {merged.net_amount}",
                      changes={"row": audit.snapshot(merged)})
            db.delete(merged)
            db.commit()
            self.ctx.toast(tr("Intäkt raderad."), "success")
            self.reload()
        finally:
            db.close()

    def create_invoice(self) -> None:
        e = self._selected()
        if not e:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(e)
            if merged.invoice_id:
                self.ctx.toast(tr("Intäkten har redan en faktura."), "warning"); return
            if merged.customer_id is None:
                self.ctx.toast(tr("Välj en registrerad kund på intäkten innan faktura skapas "
                                  "(engångskunder: lägg upp dem under Kunder)."), "warning")
                return
            profile = get_profile(db)
            inv = Invoice(status="draft", invoice_date=date.today(),
                          payment_terms_days=profile.payment_terms_days,
                          customer_id=merged.customer_id, notes=profile.invoice_notes)
            db.add(inv)
            db.flush()
            db.add(InvoiceLine(invoice_id=inv.id, position=0,
                               description=merged.description or "Fakturerat arbete",
                               quantity=1, unit="st", unit_price=q2(merged.net_amount),
                               vat_code=merged.vat_code, vat_rate=merged.vat_rate))
            db.flush()
            recalc_invoice(inv, round_to_krona=bool(profile.round_total_to_krona))
            merged.invoice_id = inv.id
            audit.log(db, "desktop", "create", "Invoice", inv.id, summary=f"draft from income #{merged.id}")
            db.commit()
            self.ctx.toast(tr("Fakturautkast skapat (rad motsvarar beloppet exkl moms). "
                              "Kontrollera rader, antal och pris innan fastställning."), "success")
            self.reload()
        finally:
            db.close()
