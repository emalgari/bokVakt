"""Tax documents page (feature D): upload/list Skatteverket documents,
user-entered key figures, and a transparent income-tax ESTIMATE built only
from user-provided parameters. Prominent disclaimer: not tax advice.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy import select

from ...core import reports, taxdocs
from ...core.invoices import get_profile
from ...core.models import TaxDocument
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, tr
from .. import theme
from ..dialogs.taxdoc_form import TYPE_KEYS, TaxDocDetailDialog, TaxDocUploadDialog
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.forms import MoneyEdit, parse_money
from ..widgets.tables import DataTable

COLUMNS = [
    ("Dokumenttyp", "l"), ("Titel", "l"), ("Utgivningsdatum", "l"),
    ("Period", "l"), ("Fil", "l"),
]


class TaxDocumentsPage(Translatable):
    page_id = "taxdocs"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.header = PageHeader("Skattedokument")
        self.btn_upload = QPushButton(tr("Ladda upp dokument"))
        self.btn_upload.setIcon(theme.icon("plus"))
        self.btn_upload.clicked.connect(self.upload)
        self.header.add_action(self.btn_upload)
        lay.addWidget(self.header)

        self.disclaimer = QLabel("")
        self.disclaimer.setWordWrap(True)
        self.disclaimer.setObjectName("disclaimer")
        self.disclaimer.setStyleSheet(
            "background:#fff8e6; border:1px solid #e6d9a8; border-radius:8px;"
            "padding:10px; color:#5c4a12;")
        lay.addWidget(self.disclaimer)

        bar = QHBoxLayout()
        self.type_cb = QComboBox()
        self.type_cb.currentIndexChanged.connect(self.reload)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        bar.addWidget(self.type_cb)
        bar.addWidget(self.year_spin)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.table = DataTable(COLUMNS, empty_key="Inga skattedokument ännu.",
                               empty_cta="Ladda upp dokument", on_empty_cta=self.upload)
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_detail = QPushButton(tr("Uppdatera nyckeltal"))
        self.btn_detail.setProperty("kind", "secondary")
        self.btn_detail.setIcon(theme.icon("pencil"))
        self.btn_detail.clicked.connect(self.detail)
        self.btn_open = QPushButton(tr("Öppna fil"))
        self.btn_open.setProperty("kind", "ghost")
        self.btn_open.setIcon(theme.icon("file-text"))
        self.btn_open.clicked.connect(self.open_file)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_doc)
        for b in (self.btn_detail, self.btn_open, self.btn_delete):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        # ---- estimate card ----
        est = Card("")
        grid = QHBoxLayout()
        self.est_title = QLabel("")
        self.est_title.setStyleSheet("font-weight:600;")
        self.income_edit = MoneyEdit()
        self.income_edit.setPlaceholderText(tr("Beskattningsbar inkomst (kr)"))
        self.btn_fill = QPushButton(tr("Beräkna"))
        self.btn_fill.setProperty("kind", "secondary")
        self.btn_fill.clicked.connect(self.calculate)
        self.est_result = QLabel("")
        self.est_result.setWordWrap(True)
        self.est_note = QLabel("")
        self.est_note.setObjectName("muted")
        self.est_note.setWordWrap(True)
        grid.addWidget(self.est_title)
        grid.addWidget(self.income_edit, 1)
        grid.addWidget(self.btn_fill)
        est.body.addLayout(grid)
        est.body.addWidget(self.est_result)
        est.body.addWidget(self.est_note)
        lay.addWidget(est)

        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_upload.setText(tr("Ladda upp dokument"))
        self.disclaimer.setText(tr("taxdocs.disclaimer"))
        self.btn_detail.setText(tr("Uppdatera nyckeltal"))
        self.btn_open.setText(tr("Öppna fil"))
        self.btn_delete.setText(tr("Radera"))
        self.est_title.setText(tr("Beräknad inkomstskatt"))
        self.btn_fill.setText(tr("Beräkna"))
        self.income_edit.setPlaceholderText(tr("Beskattningsbar inkomst (kr)"))
        self.est_note.setText(tr("Beräkningen använder dina egna parametrar "
                                 "(Inställningar → Lön & skatteparametrar)."))
        cur = self.type_cb.currentData() if self.type_cb.count() else ""
        self.type_cb.blockSignals(True)
        self.type_cb.clear()
        self.type_cb.addItem(tr("Alla"), "")
        for value, key in TYPE_KEYS.items():
            self.type_cb.addItem(tr(key), value)
        self.type_cb.setCurrentIndex(max(0, self.type_cb.findData(cur or "")))
        self.type_cb.blockSignals(False)
        self.reload()

    # ----------------------------------------------------------------- data
    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.year_spin.value() < 2001:
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(
                    fiscal_year_of(today, profile.fiscal_year_start_month))
                self.year_spin.blockSignals(False)
            flt = self.type_cb.currentData()
            q = select(TaxDocument).order_by(TaxDocument.issued_date.desc(),
                                             TaxDocument.id.desc())
            if flt:
                q = q.where(TaxDocument.doc_type == flt)
            docs = db.execute(q).scalars().all()
            self._docs = docs
            self.table.clear_rows()
            for d in docs:
                self.table.add_row([
                    tr(TYPE_KEYS[d.doc_type]), d.title,
                    fmt.date(d.issued_date) if d.issued_date else "",
                    d.period_text, d.original_name])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            # prefill estimate inputs from the user's own data
            start, end = fiscal_year_bounds(self.year_spin.value(),
                                            profile.fiscal_year_start_month)
            t = reports.compute_totals(db, start, end)
            if not self.income_edit.text().strip():
                self.income_edit.set_decimal(t.profit)
            self._prepaid = taxdocs.sum_prepaid_from_documents(db)
        finally:
            db.close()

    def _selected(self) -> TaxDocument | None:
        row = self.table.selected_row()
        return self._docs[row] if 0 <= row < len(self._docs) else None

    # -------------------------------------------------------------- actions
    def upload(self) -> None:
        db = self.ctx.session()
        try:
            dlg = TaxDocUploadDialog(db, self.window())
            if dlg.exec() and getattr(dlg, "result_doc", None) is not None:
                db.commit()
                self.ctx.toast(tr("Dokument uppladdat."), "success")
                self.reload()
            else:
                db.rollback()
        except Exception as exc:  # ValueError/FileNotFoundError
            db.rollback()
            self.ctx.toast(f"{tr('Export misslyckades')}: {exc}", "error")
        finally:
            db.close()

    def detail(self) -> None:
        doc = self._selected()
        if not doc:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            merged = db.merge(doc)
            TaxDocDetailDialog(db, merged, self.window()).exec()
            self.reload()
        finally:
            db.close()

    def open_file(self) -> None:
        doc = self._selected()
        if not doc:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        import subprocess
        import sys
        path = str(taxdocs.stored_path(doc))
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform.startswith("win"):
                import os
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            self.ctx.toast(f"{tr('Export misslyckades')}: {exc}", "error")

    def delete_doc(self) -> None:
        doc = self._selected()
        if not doc:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        if not self.ctx.confirm("Radera dokumentet permanent?"):
            return
        db = self.ctx.session()
        try:
            merged = db.merge(doc)
            taxdocs.delete_document(db, merged)
            db.commit()
            self.ctx.toast(tr("Dokument raderat."), "success")
            self.reload()
        finally:
            db.close()

    def calculate(self) -> None:
        db = self.ctx.session()
        try:
            taxable = parse_money(self.income_edit.text())
            if taxable is None:
                self.income_edit.setText("")
                self.est_result.setText(tr("salary.no_rows"))
                return
            est = taxdocs.estimate_income_tax(db, taxable, self._prepaid)
            sign = tr("Att betala in / få tillbaka (kr)")
            self.est_result.setText(
                f"{tr('Beskattningsbar inkomst (kr)')}: {fmt.money(est['taxable_income'])}  ·  "
                f"{tr('Kommun+kyrka+begravning %')}: {est['combined_pct']} %  ·  "
                f"{tr('Beräknad skatt före avdrag (kr)')}: {fmt.money(est['gross_tax'])}  ·  "
                f"{tr('Avdrag (kr)')}: {fmt.money(est['deduction'])}  ·  "
                f"{tr('Redan betald preliminärskatt (kr)')}: {fmt.money(est['prepaid_tax'])}\n"
                f"{sign}: {fmt.money(est['to_pay_or_refund'])}")
        finally:
            db.close()
