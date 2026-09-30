"""Reports page: P&L, categories, monthly overview, exports."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...core import reports
from ...core.invoices import get_profile
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, i18n, month_name, tr
from .. import theme
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable
from ..workers import Worker


class ReportsPage(Translatable):
    page_id = "reports"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Rapporter")
        self.year_spin = QSpinBox(); self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        self.header.add_action(self.year_spin)
        lay.addWidget(self.header)

        actions = QHBoxLayout()
        self.btn_journal = QPushButton(tr("Bokföringsorder (CSV)"))
        self.btn_journal.setProperty("kind", "secondary")
        self.btn_journal.setIcon(theme.icon("download"))
        self.btn_journal.clicked.connect(self._export_journal)
        self.btn_ne = QPushButton(tr("NE-bilaga underlag (CSV)"))
        self.btn_ne.setProperty("kind", "secondary")
        self.btn_ne.setIcon(theme.icon("download"))
        self.btn_ne.clicked.connect(self._export_ne)
        self.btn_pdf = QPushButton(tr("Resultatrapport (PDF)"))
        self.btn_pdf.setProperty("kind", "secondary")
        self.btn_pdf.setIcon(theme.icon("download"))
        self.btn_pdf.clicked.connect(self._export_pdf)
        for b in (self.btn_journal, self.btn_ne, self.btn_pdf):
            actions.addWidget(b)
        actions.addStretch(1)
        lay.addLayout(actions)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.pl_card = Card("Resultaträkning")
        self.pl_lbl = QLabel("")
        self.pl_lbl.setWordWrap(True)
        self.pl_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pl_card.body.addWidget(self.pl_lbl)
        self.cat_table = DataTable([("Kategori", "l"), ("Kostnad", "r"), ("Moms totalt", "r"),
                                    ("Avdragsgill", "r"), ("Antal", "r")],
                                   empty_key="Inga utgifter.")
        cat_card = Card("Kostnadskategorier")
        cat_card.body.addWidget(self.cat_table)
        grid.addWidget(self.pl_card, 0, 0)
        grid.addWidget(cat_card, 0, 1)
        lay.addLayout(grid, 1)

        self.month_table = DataTable(
            [("Månad", "l"), ("Intäkter exkl", "r"), ("Utg. moms", "r"), ("Kostnader", "r"),
             ("Ing. moms", "r"), ("Moms +/−", "r"), ("Resultat", "r"), ("Egna uttag", "r")],
            empty_key="Ingen data för detta år ännu.", sortable=False)
        month_card = Card("Månadsöversikt")
        month_card.body.addWidget(self.month_table)
        lay.addWidget(month_card, 1)
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_journal.setText(tr("Bokföringsorder (CSV)"))
        self.btn_ne.setText(tr("NE-bilaga underlag (CSV)"))
        self.btn_pdf.setText(tr("Resultatrapport (PDF)"))
        self.reload()

    def _fy(self):
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            if self.year_spin.value() < 2001:
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(fiscal_year_of(today, profile.fiscal_year_start_month))
                self.year_spin.blockSignals(False)
            fy = self.year_spin.value()
            return profile, fy, *fiscal_year_bounds(fy, profile.fiscal_year_start_month)
        finally:
            db.close()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile, fy, start, end = self._fy()
            pl = reports.pl_report(db, start, end)
            lines = [f"<b>{tr('Intäkter (exkl. moms)')}</b>"]
            for r in pl["revenue_rows"]:
                lines.append(f"{r['label']}: {fmt.money(r['amount'])}")
            lines.append(f"<b>{tr('Summa nettoomsättning')}: {fmt.money(pl['revenue_total'])}</b>")
            lines.append("")
            lines.append(f"<b>{tr('Kostnader (exkl. avdragsgill moms)')}</b>")
            for c in pl["expense_rows"]:
                lines.append(f"{c['category']}: {fmt.money(c['cost'])}")
            lines.append(f"<b>{tr('Summa kostnader')}: {fmt.money(pl['expense_total'])}</b>")
            lines.append(f"<b>{tr('Årets resultat före skatt')}: {fmt.money(pl['profit'])}</b>")
            lines.append("")
            lines.append(f"{tr('Memo (påverkar EJ resultatet): egna uttag')} "
                         f"{fmt.money(pl['owner_withdrawals'])}, "
                         f"{tr('egna insättningar')} {fmt.money(pl['owner_contributions'])}")
            lines.append(f"{tr('Moms: utgående')} {fmt.money(pl['output_vat'])}, "
                         f"{tr('ingående')} {fmt.money(pl['input_vat'])}, "
                         f"{tr('netto')} {fmt.money(pl['net_vat'])}")
            lines.append(f"<i>{tr('Ingen inkomstskatt beräknas i detta system.')}</i>")
            self.pl_lbl.setText("<br>".join(lines))

            self.cat_table.clear_rows()
            for c in pl["expense_rows"]:
                self.cat_table.add_row([c["category"], fmt.money(c["cost"], symbol=False),
                                        fmt.money(c["vat"], symbol=False),
                                        fmt.money(c["deductible"], symbol=False), str(c["count"])])
            self.cat_table.refresh_empty_state()
            self.cat_table.resize_columns()

            months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
            self.month_table.clear_rows()
            for row in months:
                t = row["totals"]
                self.month_table.add_row([
                    month_name(row["calendar_month"]),
                    fmt.money(t.net_income, symbol=False), fmt.money(t.output_vat, symbol=False),
                    fmt.money(t.expense_cost, symbol=False), fmt.money(t.input_vat, symbol=False),
                    fmt.money(t.net_vat, symbol=False), fmt.money(t.profit, symbol=False),
                    fmt.money(t.owner_withdrawals, symbol=False)])
            self.month_table.refresh_empty_state()
            self.month_table.resize_columns()
        finally:
            db.close()

    # ------------------------------------------------------------- exports
    def _export_journal(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("Exportera CSV"),
                                              f"bokforingsorder_{self.year_spin.value()}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        db = self.ctx.session()
        try:
            _p, _fy, start, end = self._fy()
            content = reports.export_journal_csv(db, start, end, lang=i18n.language)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            self.ctx.toast(tr("CSV sparad") + f": {path}", "success")
        finally:
            db.close()

    def _export_ne(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("Exportera CSV"),
                                              f"ne_bilaga_{self.year_spin.value()}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        db = self.ctx.session()
        try:
            profile, fy, _s, _e = self._fy()
            content = reports.export_ne_bilaga_csv(db, fy, profile.fiscal_year_start_month,
                                                   lang=i18n.language)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            self.ctx.toast(tr("CSV sparad") + f": {path}", "success")
        finally:
            db.close()

    def _export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("Exportera PDF"),
                                              f"resultat_{self.year_spin.value()}.pdf",
                                              "PDF (*.pdf)")
        if not path:
            return
        self.btn_pdf.setEnabled(False)

        def _job(p):
            db = self.ctx.session()
            try:
                from ...core import pdf as core_pdf
                from ...i18n import translate_for
                profile, fy, start, end = self._fy()
                pl = reports.pl_report(db, start, end)
                months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
                data = core_pdf.render_report_pdf("report_pdf.html", {
                    "profile": profile,
                    "title": (f"Resultatrapport {fy}" if i18n.language == "sv"
                              else f"Profit & loss report {fy}"),
                    "period_text": f"{start.isoformat()} – {end.isoformat()}",
                    "pl": pl, "months": months, "generated": date.today().isoformat(),
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
        self._worker = w
