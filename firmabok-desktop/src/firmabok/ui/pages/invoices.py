"""Invoices page: list, editor, finalize, send, payment, credit note, PDF."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import select

from ...core import audit
from ...core.errors import InvoiceError
from ...core.invoices import (
    create_credit_note,
    delete_draft,
    finalize_invoice,
    mark_paid,
    peek_next_number,
)
from ...core.models import Invoice, InvoiceStatus
from ...i18n import fmt, tr
from .. import theme
from ..dialogs.forms import InvoiceEditorDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.forms import MoneyEdit, date_edit, date_of
from ..widgets.tables import DataTable
from ..workers import Worker

STATUS_KEYS = {
    InvoiceStatus.DRAFT.value: "Utkast",
    InvoiceStatus.FINALIZED.value: "Fastställd",
    InvoiceStatus.SENT.value: "Skickad",
    InvoiceStatus.PAID.value: "Betald",
    InvoiceStatus.CREDITED.value: "Krediterad",
}

COLUMNS = [("Nummer", "l"), ("Datum", "l"), ("Förfaller", "l"), ("Kund", "l"), ("Typ", "l"),
           ("Exkl. moms", "r"), ("Moms", "r"), ("Inkl. moms", "r"), ("Status", "c")]


class InvoiceDetailDialog(QDialog):
    """Read-only view + lifecycle actions for a finalized invoice."""

    def __init__(self, ctx, db, invoice: Invoice, parent=None):
        super().__init__(parent)
        self.ctx, self.db, self.inv = ctx, db, invoice
        self.setMinimumWidth(720)
        lay = QVBoxLayout(self)
        title = QLabel()
        title.setStyleSheet("font-size:20px;font-weight:700;")
        title.setText(f"{tr('Kreditfaktura') if invoice.is_credit_note else tr('Faktura')} "
                      f"{invoice.number or ''}")
        lay.addWidget(title)
        grid = QGridLayout()
        info = [
            ("Fakturadatum", fmt.date(invoice.invoice_date)),
            ("Leveransdatum", fmt.date(invoice.delivery_date or invoice.invoice_date)),
            ("Förfallodatum", fmt.date(invoice.due_date)),
            ("OCR", invoice.ocr),
            ("Kund", invoice.customer.name if invoice.customer else ""),
            (tr("Summa exkl. moms"), fmt.money(invoice.net_total)),
            ("Moms", fmt.money(invoice.vat_total)),
            ("Avrundning", fmt.money(invoice.rounding_amount or Decimal(0))),
            (tr("Summa inkl. moms"), fmt.money(invoice.gross_total)),
            ("Att betala", fmt.money(invoice.amount_to_pay)),
        ]
        for i, (k, v) in enumerate(info):
            key = QLabel(tr(k) if not k.startswith(("Fält",)) else k)
            key.setObjectName("muted")
            val = QLabel(str(v))
            val.setStyleSheet("font-weight:600;")
            grid.addWidget(key, i // 2, (i % 2) * 2)
            grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(grid)

        lines = DataTable([("Art.nr", "l"), ("Beskrivning", "l"), ("Antal", "r"), ("Enhet", "l"),
                           ("À-pris exkl", "r"), ("Moms", "l"), ("Rad exkl", "r"), ("Rad inkl", "r")],
                          empty_key="")
        for ln in invoice.lines:
            lines.add_row([ln.article_no, ln.description, fmt.qty(ln.quantity), ln.unit,
                           fmt.money(ln.unit_price, symbol=False), f"{ln.vat_rate}%",
                           fmt.money(ln.line_net, symbol=False), fmt.money(ln.line_gross, symbol=False)])
        lines.table.setMaximumHeight(180)
        lay.addWidget(lines)

        actions = QHBoxLayout()
        self.btn_pdf = QPushButton(tr("Ladda ner PDF"))
        self.btn_pdf.setIcon(theme.icon("download"))
        self.btn_pdf.clicked.connect(self._pdf)
        actions.addWidget(self.btn_pdf)
        if invoice.status in (InvoiceStatus.FINALIZED.value,):
            self.btn_sent = QPushButton(tr("Markera som skickad"))
            self.btn_sent.setProperty("kind", "secondary")
            self.btn_sent.clicked.connect(self._sent)
            actions.addWidget(self.btn_sent)
        if invoice.status in (InvoiceStatus.FINALIZED.value, InvoiceStatus.SENT.value,
                              InvoiceStatus.PAID.value):
            self.pay_edit = MoneyEdit()
            self.pay_date = date_edit(date.today())
            self.btn_pay = QPushButton(tr("Registrera betalning"))
            self.btn_pay.setProperty("kind", "secondary")
            self.btn_pay.setIcon(theme.icon("coins"))
            self.btn_pay.clicked.connect(self._pay)
            actions.addWidget(self.pay_edit)
            actions.addWidget(self.pay_date)
            actions.addWidget(self.btn_pay)
            if not invoice.is_credit_note:
                self.btn_credit = QPushButton(tr("Skapa kreditfaktura"))
                self.btn_credit.setProperty("kind", "danger")
                self.btn_credit.clicked.connect(self._credit)
                actions.addWidget(self.btn_credit)
        actions.addStretch(1)
        close_btn = QPushButton(tr("Stäng"))
        close_btn.setProperty("kind", "ghost")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        lay.addLayout(actions)

    def _pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("Spara PDF"), f"faktura_{self.inv.number or 'utkast'}.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.btn_pdf.setEnabled(False)
        invoice_id = self.inv.id

        def _job(p):
            from ...core import pdf as core_pdf
            db2 = self.ctx.session()
            try:
                data = core_pdf.render_invoice_pdf(db2, invoice_id)
                with open(p, "wb") as f:
                    f.write(data)
                return p
            finally:
                db2.close()

        w = Worker(_job, path)
        w.finished.connect(lambda p: (self.btn_pdf.setEnabled(True),
                                      self.ctx.toast(tr("PDF sparad") + f": {p}", "success")))
        w.failed.connect(lambda e: (self.btn_pdf.setEnabled(True),
                                    self.ctx.toast(self.ctx_error_text(e), "error")))
        w.start()
        self._worker = w

    def ctx_error_text(self, e: str) -> str:
        try:
            return tr(e)
        except Exception:  # noqa: BLE001
            return e

    def _sent(self) -> None:
        self.inv.status = InvoiceStatus.SENT.value
        audit.log(self.db, "desktop", "update", "Invoice", self.inv.id,
                  summary=f"{self.inv.number} sent")
        self.db.commit()
        self.ctx.toast(tr("Markerad som skickad."), "success")
        self.accept()

    def _pay(self) -> None:
        amt = self.pay_edit.decimal()
        mark_paid(self.db, self.inv, amt, date_of(self.pay_date))
        audit.log(self.db, "desktop", "update", "Invoice", self.inv.id,
                  summary=f"payment {amt}")
        self.db.commit()
        self.ctx.toast(tr("Betalning registrerad") + f": {fmt.money(amt or self.inv.amount_to_pay)}",
                       "success")
        self.accept()

    def _credit(self) -> None:
        if not self.ctx.confirm("Skapa kreditfaktura för hela beloppet?", danger=False):
            return
        credit = create_credit_note(self.db, self.inv, username="desktop")
        self.db.commit()
        self.ctx.toast(tr("Kreditfaktura skapad") + f" (id {credit.id}).", "success")
        self.accept()


class InvoicesPage(Translatable):
    page_id = "invoices"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Fakturor")
        self.btn_new = QPushButton(tr("Ny faktura"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_invoice)
        self.header.add_action(self.btn_new)
        lay.addWidget(self.header)

        row = QHBoxLayout()
        self.status_cb = QComboBox()
        self.status_cb.addItem(tr("Alla"), "")
        for value, key in STATUS_KEYS.items():
            self.status_cb.addItem(tr(key), value)
        self.status_cb.currentIndexChanged.connect(self.reload)
        row.addWidget(self.status_cb)
        row.addStretch(1)
        self.next_lbl = QLabel("")
        self.next_lbl.setObjectName("muted")
        row.addWidget(self.next_lbl)
        lay.addLayout(row)

        self.table = DataTable(COLUMNS, empty_key="Inga fakturor ännu.",
                               empty_cta="Skapa den första →", on_empty_cta=self.new_invoice)
        self.table.table.doubleClicked.connect(lambda _: self.open_selected())
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_open = QPushButton(tr("Öppna"))
        self.btn_open.setProperty("kind", "secondary")
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_delete = QPushButton(tr("Radera utkast"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_draft)
        actions.addWidget(self.btn_open)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)
        self.hint = QLabel(tr("Nummerserien är löpande per räkenskapsår utan luckor: nummer "
                              "tilldelas när fakturan fastställs."))
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        lay.addLayout(actions)
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_new.setText(tr("Ny faktura"))
        self.btn_open.setText(tr("Öppna"))
        self.btn_delete.setText(tr("Radera utkast"))
        self.status_cb.setItemText(0, tr("Alla"))
        for i, key in enumerate(STATUS_KEYS.values()):
            self.status_cb.setItemText(i + 1, tr(key))
        self.hint.setText(tr("Nummerserien är löpande per räkenskapsår utan luckor: nummer "
                             "tilldelas när fakturan fastställs."))
        self.reload()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            stmt = select(Invoice)
            status = self.status_cb.currentData()
            if status:
                stmt = stmt.where(Invoice.status == status)
            invoices = db.execute(stmt.order_by(
                Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())).scalars().all()
            self._invoices = invoices
            self.table.clear_rows()
            for inv in invoices:
                self.table.add_row([
                    inv.number or tr("(utkast)"), fmt.date(inv.invoice_date), fmt.date(inv.due_date),
                    inv.customer.name if inv.customer else "—",
                    tr("Kredit") if inv.is_credit_note else tr("Faktura"),
                    fmt.money(inv.net_total, symbol=False), fmt.money(inv.vat_total, symbol=False),
                    fmt.money(inv.gross_total, symbol=False),
                    tr(STATUS_KEYS.get(inv.status, inv.status))])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            self.next_lbl.setText(f"{tr('Nästa lediga nummer')}: {peek_next_number(db, date.today().year)}")
        finally:
            db.close()

    def _selected(self) -> Invoice | None:
        row = self.table.selected_row()
        return self._invoices[row] if 0 <= row < len(self._invoices) else None

    def new_invoice(self) -> None:
        db = self.ctx.session()
        try:
            dlg = InvoiceEditorDialog(db, None, self.window())
            if dlg.exec() and getattr(dlg, "result_invoice", None) is not None:
                inv = dlg.result_invoice
                audit.log(db, "desktop", "create", "Invoice", inv.id,
                          summary=f"draft {inv.gross_total}")
                if getattr(dlg, "result_finalize", False):
                    try:
                        finalize_invoice(db, inv, username="desktop", book_income=True)
                        db.commit()
                        self.ctx.toast(tr("Faktura skapad och fastställd") + f": {inv.number}. "
                                       + tr("Betalning kan registreras senare."), "success")
                    except InvoiceError as exc:
                        db.rollback()
                        self.ctx.toast(tr(exc.key), "error")
                        db.commit()
                else:
                    db.commit()
                    self.ctx.toast(tr("Utkast skapat"), "success")
                self.reload()
            else:
                db.rollback()
        finally:
            db.close()

    def open_selected(self) -> None:
        inv = self._selected()
        if not inv:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(inv)
            if merged.status == InvoiceStatus.DRAFT.value:
                dlg = InvoiceEditorDialog(db, merged, self.window())
                if dlg.exec():
                    if getattr(dlg, "result_finalize", False):
                        try:
                            finalize_invoice(db, merged, username="desktop", book_income=True)
                            db.commit()
                            self.ctx.toast(tr("Faktura skapad och fastställd") + f": {merged.number}.", "success")
                        except InvoiceError as exc:
                            db.rollback()
                            self.ctx.toast(tr(exc.key), "error")
                            db.commit()
                    else:
                        db.commit()
                        self.ctx.toast(tr("Sparat."), "success")
                else:
                    db.rollback()
            else:
                detail = InvoiceDetailDialog(self.ctx, db, merged, self.window())
                detail.exec()
            self.reload()
        finally:
            db.close()

    def delete_draft(self) -> None:
        inv = self._selected()
        if not inv:
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        db = self.ctx.session()
        try:
            merged = db.merge(inv)
            try:
                delete_draft(db, merged)
                audit.log(db, "desktop", "delete", "Invoice", merged.id, summary="draft deleted")
                db.commit()
                self.ctx.toast(tr("Utkast raderat (nummerserien opåverkad)."), "success")
            except InvoiceError as exc:
                db.rollback()
                self.ctx.toast(tr(exc.key), "error")
            self.reload()
        finally:
            db.close()
