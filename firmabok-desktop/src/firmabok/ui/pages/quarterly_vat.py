"""Quarterly VAT overview (feature C).

Read-only aggregation over the existing VAT engine: every number on this page
comes from ``reports.build_vat_report(kind="quarter", …)`` — the same function
the VAT page uses — so calculation logic is untouched. Deadlines use the
USER-CONFIGURABLE defaults in TaxParameters, not hardcoded legal dates.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...core import reports
from ...core import vat as vatmod
from ...core.invoices import get_profile
from ...core.migrate import ensure_tax_parameters
from ...core.swedish import filing_due, fiscal_year_of
from ...i18n import fmt, i18n, tr
from .. import theme
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable
from ..workers import Worker

COLUMNS = [
    ("Kvartal", "l"), ("Period", "l"), ("Utgående moms", "r"), ("Ingående moms", "r"),
    ("Att betala/få tillbaka", "r"), ("Deadline", "l"), ("Status", "l"),
]


class QuarterlyVatPage(Translatable):
    page_id = "quarterly"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Kvartalsmoms")
        lay.addWidget(self.header)

        bar = QHBoxLayout()
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        bar.addWidget(self.year_spin)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.table = DataTable(COLUMNS, empty_key="", sortable=False)
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_file = QPushButton(tr("Markera som inlämnad"))
        self.btn_file.setProperty("kind", "secondary")
        self.btn_file.setIcon(theme.icon("check"))
        self.btn_file.clicked.connect(lambda: self._action("file"))
        self.btn_unfile = QPushButton(tr("Häv inlämning"))
        self.btn_unfile.setProperty("kind", "danger")
        self.btn_unfile.clicked.connect(lambda: self._action("unfile"))
        self.btn_open = QPushButton(tr("Öppna period"))
        self.btn_open.setProperty("kind", "ghost")
        self.btn_open.setIcon(theme.icon("percent"))
        self.btn_open.clicked.connect(self._open_vat_page)
        self.btn_csv = QPushButton(tr("Exportera CSV"))
        self.btn_csv.setProperty("kind", "secondary")
        self.btn_csv.setIcon(theme.icon("download"))
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_pdf = QPushButton(tr("Exportera PDF"))
        self.btn_pdf.setProperty("kind", "secondary")
        self.btn_pdf.setIcon(theme.icon("download"))
        self.btn_pdf.clicked.connect(self._export_pdf)
        for b in (self.btn_file, self.btn_unfile, self.btn_open, self.btn_csv, self.btn_pdf):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.reload()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_file.setText(tr("Markera som inlämnad"))
        self.btn_unfile.setText(tr("Häv inlämning"))
        self.btn_open.setText(tr("Öppna period"))
        self.btn_csv.setText(tr("Exportera CSV"))
        self.btn_pdf.setText(tr("Exportera PDF"))
        self.reload()

    # ------------------------------------------------------------------ data
    def _params(self):
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.year_spin.value() < 2001:
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(fiscal_year_of(today, profile.fiscal_year_start_month))
                self.year_spin.blockSignals(False)
            return profile, self.year_spin.value()
        finally:
            db.close()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            fy = self.year_spin.value()
            if fy < 2001:
                return
            params = ensure_tax_parameters(db)
            self.table.clear_rows()
            for n in range(1, 5):
                report, _decl, period = reports.build_vat_report(
                    db, "quarter", fy, n, profile.fiscal_year_start_month,
                    vat_method=profile.vat_method,
                    input_vat_on_payment=profile.input_vat_on_payment)
                due = filing_due(period.end, params.vat_deadline_day,
                                 params.vat_deadline_month_offset)
                if report.locked:
                    status = tr("Inlämnad") + (
                        f" {fmt.date(report.filed_at.date())}" if report.filed_at else "")
                else:
                    status = tr("Ej inlämnad")
                self.table.add_row([
                    f"{tr('Kvartal')} {n}", period.label,
                    fmt.money(report.output_vat, symbol=False),
                    fmt.money(report.input_vat, symbol=False),
                    fmt.money(report.net_vat, symbol=False),
                    fmt.date(due), status])
            db.commit()
            self.table.refresh_empty_state()
            self.table.resize_columns()
        finally:
            db.close()

    def _selected_number(self) -> int:
        row = self.table.selected_row()
        return row + 1 if 0 <= row < 4 else 0

    # --------------------------------------------------------------- actions
    def _action(self, action: str) -> None:
        n = self._selected_number()
        if not n:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        db = self.ctx.session()
        try:
            profile, fy = self._params()
            report, _decl, period = reports.build_vat_report(
                db, "quarter", fy, n, profile.fiscal_year_start_month,
                vat_method=profile.vat_method,
                input_vat_on_payment=profile.input_vat_on_payment)
            if action == "file":
                if report.locked:
                    self.ctx.toast(tr("Redan inlämnad."), "info")
                    db.rollback()
                    return
                if not self.ctx.confirm("Låsa perioden som deklarerad? Siffrorna fryses.", danger=False):
                    db.rollback()
                    return
                report.locked = True
                report.filed_at = datetime.now(UTC)
                self.ctx.toast(tr("Kvartal inlämnat."), "success")
            else:
                if not report.locked:
                    db.rollback()
                    return
                if not self.ctx.confirm("Låsa upp perioden? Gör bara detta om du ska rätta deklarationen."):
                    db.rollback()
                    return
                report.locked = False
                report.filed_at = None
                self.ctx.toast(tr("Inlämning hävd."), "success")
            db.commit()
            self.reload()
        finally:
            db.close()

    def _open_vat_page(self) -> None:
        go = getattr(self.ctx.window, "go_page", None)
        if go:
            go("vat")

    def _quarter_decl(self, db, profile, fy, n):
        return reports.build_vat_report(
            db, "quarter", fy, n, profile.fiscal_year_start_month,
            vat_method=profile.vat_method,
            input_vat_on_payment=profile.input_vat_on_payment)

    def _export_csv(self) -> None:
        n = self._selected_number()
        if not n:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera CSV"), f"moms-kvartal-{n}.csv", "CSV (*.csv)")
        if not path:
            return
        db = self.ctx.session()
        try:
            profile, fy = self._params()
            _r, decl, _p = self._quarter_decl(db, profile, fy, n)
            db.commit()
            content = reports.export_vat_declaration_csv(decl, lang=i18n.language)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            self.ctx.toast(tr("CSV sparad") + f": {path}", "success")
        finally:
            db.close()

    def _export_pdf(self) -> None:
        n = self._selected_number()
        if not n:
            self.ctx.toast(tr("Markera en rad först."), "warning")
            return
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera PDF"), f"moms-kvartal-{n}.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.btn_pdf.setEnabled(False)

        def _job(p):
            db = self.ctx.session()
            try:
                from ...core import pdf as core_pdf
                from ...i18n import translate_for
                profile, fy = self._params()
                _r, decl, period = self._quarter_decl(db, profile, fy, n)
                db.commit()
                boxes_rows = [{"box": b, "label": vatmod.BOX_LABELS_SV.get(b, ""),
                               "kronor": decl.boxes_kronor.get(b, 0),
                               "exact": decl.boxes.get(b, reports.ZERO)} for b in vatmod.ALL_BOXES]
                data = core_pdf.render_report_pdf("vat_report_pdf.html", {
                    "profile": profile, "period": period, "decl": decl,
                    "boxes_rows": boxes_rows, "report": _r,
                    "kind_label": tr("Kvartal"),
                    "lang": i18n.language, "_": translate_for(i18n.language),
                })
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
