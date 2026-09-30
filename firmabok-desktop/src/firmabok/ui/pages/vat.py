"""VAT page: period selector, SKV boxes, lock/unlock, exports."""
from __future__ import annotations

from datetime import UTC, date

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...core import reports
from ...core import vat as vatmod
from ...core.invoices import get_profile
from ...core.swedish import filing_due, fiscal_year_of
from ...i18n import fmt, i18n, tr
from .. import theme
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader, StatCard
from ..widgets.tables import DataTable
from ..workers import Worker

BOX_COLUMNS = [("Fält", "l"), ("Beskrivning", "l"), ("Hela kronor", "r"), ("Exakt (kr)", "r")]


class VatPage(Translatable):
    page_id = "vat"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Momsredovisning")
        lay.addWidget(self.header)

        sel = QHBoxLayout()
        self.kind_cb = QComboBox()
        for value, key in (("month", "Månadsvis"), ("quarter", "Kvartalsvis"), ("year", "Årsvis")):
            self.kind_cb.addItem(tr(key), value)
        self.year_spin = QSpinBox(); self.year_spin.setRange(2000, 2100)
        self.number_cb = QComboBox()
        for w in (self.kind_cb, self.year_spin, self.number_cb):
            sel.addWidget(w)
        sel.addStretch(1)
        self.kind_cb.currentIndexChanged.connect(self._fill_numbers)
        self.year_spin.valueChanged.connect(self.reload)
        self.number_cb.currentIndexChanged.connect(self.reload)
        lay.addLayout(sel)

        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setObjectName("muted")
        lay.addWidget(self.info_lbl)

        cards = QHBoxLayout()
        self.card_out = StatCard("Utgående moms")
        self.card_in = StatCard("Ingående moms (avdragsgill)")
        self.card_net = StatCard("Moms att betala")
        self.card_sales = StatCard("Försäljning exkl. moms i perioden")
        for c in (self.card_out, self.card_in, self.card_net, self.card_sales):
            cards.addWidget(c)
        lay.addLayout(cards)

        self.warnings_lbl = QLabel("")
        self.warnings_lbl.setWordWrap(True)
        self.warnings_lbl.setVisible(False)
        self.warnings_lbl.setStyleSheet("color:#7A5B00;")
        lay.addWidget(self.warnings_lbl)

        self.table = DataTable(BOX_COLUMNS, empty_key="Inga sparade momsperioder ännu.")
        wrap = Card("Momsdeklarationens fält (SKV 4700)")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_save = QPushButton(tr("Spara (olåst)"))
        self.btn_save.setProperty("kind", "secondary")
        self.btn_save.clicked.connect(lambda: self._action("save"))
        self.btn_lock = QPushButton(tr("Spara & lås (deklarerad)"))
        self.btn_lock.clicked.connect(lambda: self._action("lock"))
        self.btn_unlock = QPushButton(tr("Lås upp"))
        self.btn_unlock.setProperty("kind", "danger")
        self.btn_unlock.clicked.connect(lambda: self._action("unlock"))
        self.btn_csv = QPushButton(tr("Exportera CSV"))
        self.btn_csv.setProperty("kind", "secondary")
        self.btn_csv.setIcon(theme.icon("download"))
        self.btn_csv.clicked.connect(self._export_csv)
        self.btn_pdf = QPushButton(tr("Exportera PDF"))
        self.btn_pdf.setProperty("kind", "secondary")
        self.btn_pdf.setIcon(theme.icon("download"))
        self.btn_pdf.clicked.connect(self._export_pdf)
        for b in (self.btn_save, self.btn_lock, self.btn_unlock, self.btn_csv, self.btn_pdf):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        for i, key in enumerate(("Månadsvis", "Kvartalsvis", "Årsvis")):
            self.kind_cb.setItemText(i, tr(key))
        self.btn_save.setText(tr("Spara (olåst)"))
        self.btn_lock.setText(tr("Spara & lås (deklarerad)"))
        self.btn_unlock.setText(tr("Lås upp"))
        self.btn_csv.setText(tr("Exportera CSV"))
        self.btn_pdf.setText(tr("Exportera PDF"))
        self._fill_numbers()
        self.reload()

    def _fill_numbers(self) -> None:
        kind = self.kind_cb.currentData() or "quarter"
        cur = self.number_cb.currentData() or 1
        self.number_cb.blockSignals(True)
        self.number_cb.clear()
        n = {"month": 12, "quarter": 4, "year": 1}[kind]
        for i in range(1, n + 1):
            label = tr("Månad") if kind == "month" else tr("Kvartal") if kind == "quarter" else tr("Hela året")
            self.number_cb.addItem(f"{label} {i}" if kind != "year" else label, i)
        self.number_cb.setCurrentIndex(max(0, self.number_cb.findData(min(cur, n))))
        self.number_cb.blockSignals(False)

    def _params(self):
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.year_spin.value() < 2001:
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(fiscal_year_of(today, profile.fiscal_year_start_month))
                self.year_spin.blockSignals(False)
            return (profile, self.kind_cb.currentData() or profile.vat_period,
                    self.year_spin.value(), self.number_cb.currentData() or 1)
        finally:
            db.close()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile, kind, fy, num = self._params()
            report, decl, period = reports.build_vat_report(
                db, kind, fy, num, profile.fiscal_year_start_month,
                vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
            db.commit()
            method = (tr("Bokslutsmetoden (kontantmetoden)") if profile.vat_method == "bokslut"
                      else tr("Fakturametoden"))
            self.info_lbl.setText(
                f"{period.label} ({fmt.date(period.start)} → {fmt.date(period.end)}) · {method} · "
                + tr("Deklaration lämnas senast") + f" {fmt.date(filing_due(period.end))} "
                + tr("(den 12 i andra månaden efter periodens slut)") + " · "
                + (tr("Deklarerad & låst") if report.locked else tr("Utkast (ej låst)")))
            self.card_out.set_values(fmt.money(decl.output_vat), tr("exakt"))
            self.card_in.set_values(fmt.money(decl.input_vat), tr("exakt"))
            self.card_net._label_key = "Moms att betala" if decl.net_vat_kronor >= 0 else "Att få tillbaka"
            self.card_net.retranslate()
            self.card_net.set_values(f"{decl.net_vat_kronor} kr", "fält 49",
                                     "neg" if decl.net_vat_kronor > 0 else "pos")
            self.card_sales.set_values(fmt.money(decl.sales_base_total))
            if decl.warnings:
                self.warnings_lbl.setVisible(True)
                self.warnings_lbl.setText("\n".join(f"⚠ {w}" for w in decl.warnings))
            else:
                self.warnings_lbl.setVisible(False)
            self.table.clear_rows()
            for b in vatmod.ALL_BOXES:
                exact = decl.boxes.get(b, reports.ZERO)
                kronor = decl.boxes_kronor.get(b, 0)
                if b == "49" or exact != 0 or kronor != 0:
                    self.table.add_row([b, tr(vatmod.BOX_LABELS_SV.get(b, "")),
                                        f"{kronor}", fmt.money(exact, symbol=False)])
            self.table.refresh_empty_state()
            self.table.resize_columns()
            self.btn_lock.setVisible(not report.locked)
            self.btn_unlock.setVisible(report.locked)
        finally:
            db.close()

    def _action(self, action: str) -> None:
        db = self.ctx.session()
        try:
            profile, kind, fy, num = self._params()
            report, decl, period = reports.build_vat_report(
                db, kind, fy, num, profile.fiscal_year_start_month,
                vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
            if report.locked and action != "unlock":
                self.ctx.toast(tr("Perioden är låst (deklarerad). Lås upp först om du gjort ändringar."), "warning")
                return
            if action == "lock":
                if not self.ctx.confirm("Låsa perioden som deklarerad? Siffrorna fryses.", danger=False):
                    db.rollback(); return
                report.locked = True
                from datetime import datetime
                report.filed_at = datetime.now(UTC)
                self.ctx.toast(f"{tr('Period')} {period.label} {tr('sparad och låst')}.", "success")
            elif action == "unlock":
                if not self.ctx.confirm("Låsa upp perioden? Gör bara detta om du ska rätta deklarationen."):
                    db.rollback(); return
                report.locked = False
                report.filed_at = None
                self.ctx.toast(f"{tr('Period')} {period.label} {tr('upplåst')}.", "success")
            else:
                self.ctx.toast(f"{tr('Rapport för')} {period.label} {tr('sparad (ej låst)')}.", "success")
            db.commit()
            self.reload()
        finally:
            db.close()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera CSV"), "momsdeklaration.csv", "CSV (*.csv)")
        if not path:
            return
        db = self.ctx.session()
        try:
            profile, kind, fy, num = self._params()
            _r, decl, _p = reports.build_vat_report(
                db, kind, fy, num, profile.fiscal_year_start_month,
                vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
            db.commit()
            content = reports.export_vat_declaration_csv(decl, lang=i18n.language)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            self.ctx.toast(tr("CSV sparad") + f": {path}", "success")
        finally:
            db.close()

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera PDF"), "momsrapport.pdf", "PDF (*.pdf)")
        if not path:
            return
        self.btn_pdf.setEnabled(False)

        def _job(p):
            db = self.ctx.session()
            try:
                from ...i18n import translate_for
                profile, kind, fy, num = self._params()
                _r, decl, period = reports.build_vat_report(
                    db, kind, fy, num, profile.fiscal_year_start_month,
                    vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
                db.commit()
                from ...core import pdf as core_pdf
                boxes_rows = [{"box": b, "label": vatmod.BOX_LABELS_SV.get(b, ""),
                               "kronor": decl.boxes_kronor.get(b, 0),
                               "exact": decl.boxes.get(b, reports.ZERO)} for b in vatmod.ALL_BOXES]
                data = core_pdf.render_report_pdf("vat_report_pdf.html", {
                    "profile": profile, "period": period, "decl": decl,
                    "boxes_rows": boxes_rows, "report": _r,
                    "kind_label": i18n.translate_raw(kind) if hasattr(i18n, "translate_raw") else tr({"month": "Månad", "quarter": "Kvartal", "year": "Helår"}[kind]),
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
