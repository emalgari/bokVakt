"""Dashboard page: year overview, month grid, current VAT period, warnings."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ...core import reports
from ...core.invoices import get_profile
from ...core.models import VatReport
from ...core.swedish import fiscal_year_of, period_of
from ...i18n import fmt, i18n, tr
from ..translatable import Translatable
from ..widgets.cards import Banner, Card, PageHeader, StatCard
from ..widgets.tables import DataTable


class DashboardPage(Translatable):
    page_id = "dashboard"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.header = PageHeader("Dashboard")
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(lambda _: self.reload())
        self.header.add_action(self.year_spin)
        lay.addWidget(self.header)

        self.simplified_banner = Banner("danger")
        self.simplified_banner.setVisible(False)
        lay.addWidget(self.simplified_banner)

        self.warnings_card = Card("Varningar")
        self.warnings_lbl = QLabel("")
        self.warnings_lbl.setWordWrap(True)
        self.warnings_card.body.addWidget(self.warnings_lbl)
        lay.addWidget(self.warnings_card)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(12)
        self.card_revenue = StatCard("Nettoomsättning")
        self.card_costs = StatCard("Kostnader")
        self.card_profit = StatCard("Resultat")
        self.card_vat = StatCard("Moms")
        self._stat_cards = (self.card_revenue, self.card_costs, self.card_profit, self.card_vat)
        lay.addLayout(self.cards_grid)
        self._layout_cards()

        self.period_card = Card("Aktuell momsperiod")
        self.period_lbl = QLabel("")
        self.period_lbl.setWordWrap(True)
        self.period_card.body.addWidget(self.period_lbl)
        lay.addWidget(self.period_card)

        self.months = DataTable(
            [("Månad", "l"), ("Intäkter exkl.", "r"), ("Utg. moms", "r"),
             ("Kostnader", "r"), ("Ing. moms", "r"), ("Moms +/−", "r"),
             ("Resultat", "r"), ("Egna uttag", "r")],
            empty_key="Ingen data för detta år ännu.", sortable=False)
        months_wrap = Card("Månadsöversikt")
        months_wrap.body.addWidget(self.months)
        lay.addWidget(months_wrap, 1)

        self.retranslate()

    def _layout_cards(self) -> None:
        w = self.width() or 1000
        cols = 4 if w >= 1150 else 2 if w >= 700 else 1
        if getattr(self, "_card_cols", None) == cols:
            return
        self._card_cols = cols
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for i, c in enumerate(self._stat_cards):
            self.cards_grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._layout_cards()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.simplified_banner.set_text(
            "FÖRENKLAT LÄGE (EJ KORREKT): momssiffran på dashboarden är beräknad på vinst "
            "och får INTE användas till Skatteverket.")
        self.reload()

    def reload(self) -> None:
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            today = date.today()
            fy = self.year_spin.value()
            if fy in (2000, 0) or fy < 2001:
                fy = fiscal_year_of(today, profile.fiscal_year_start_month)
                self.year_spin.blockSignals(True)
                self.year_spin.setValue(fy)
                self.year_spin.blockSignals(False)

            self.simplified_banner.setVisible(bool(profile.simplified_vat_mode))

            # warnings
            warnings = []
            if not profile.company_name:
                warnings.append(tr("warning.no_company"))
            if not profile.org_nr:
                warnings.append(tr("warning.no_orgnr"))
            if not profile.vat_number:
                warnings.append(tr("warning.no_vatnr"))
            if not profile.f_skatt_registered:
                warnings.append(tr("warning.no_fskatt"))
            pay = profile.payment_display or "bankgiro"
            have = (profile.bankgiro if pay == "bankgiro"
                    else profile.plusgiro if pay == "plusgiro"
                    else (profile.bank_account_number or profile.bank_name))
            if not have:
                warnings.append(tr("warning.no_bank"))
            self.warnings_card.setVisible(bool(warnings))
            self.warnings_lbl.setText("\n".join(f"• {w}" for w in warnings))

            months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
            year = reports.yearly_summary(db, fy, profile.fiscal_year_start_month)
            self.card_revenue.set_values(fmt.money(year.net_income),
                                         tr("exkl. moms · brutto") + f" {fmt.money(year.gross_income)}")
            self.card_costs.set_values(fmt.money(year.expense_cost), tr("exkl. avdragsgill moms"))
            self.card_profit.set_values(fmt.money(year.profit),
                                        tr("nettoomsättning − kostnader (före skatt)"),
                                        "pos" if year.profit >= 0 else "neg")
            self.card_vat.set_values(fmt.money(year.net_vat),
                                     f"{tr('utgående')} {fmt.money(year.output_vat)} − "
                                     f"{tr('ingående')} {fmt.money(year.input_vat)} = "
                                     + (tr("att betala") if year.net_vat > 0
                                        else tr("att få tillbaka") if year.net_vat < 0 else tr("noll")),
                                     "neg" if year.net_vat > 0 else "pos")
            if profile.simplified_vat_mode:
                from ...core.money import q2
                self.card_vat.set_values(fmt.money(q2(year.profit * Decimal25())),
                                         tr("simplified.card_note"), "neg")

            self.months.clear_rows()
            for row in months:
                t = row["totals"]
                self.months.add_row([
                    i18n and f"{fmt_month(row['calendar_month'])}",
                    fmt.money(t.net_income, symbol=False), fmt.money(t.output_vat, symbol=False),
                    fmt.money(t.expense_cost, symbol=False), fmt.money(t.input_vat, symbol=False),
                    fmt.money(t.net_vat, symbol=False), fmt.money(t.profit, symbol=False),
                    fmt.money(t.owner_withdrawals, symbol=False)])
            self.months.add_total_row([
                f"{tr('Summa')} {fy}",
                fmt.money(year.net_income, symbol=False), fmt.money(year.output_vat, symbol=False),
                fmt.money(year.expense_cost, symbol=False), fmt.money(year.input_vat, symbol=False),
                fmt.money(year.net_vat, symbol=False), fmt.money(year.profit, symbol=False),
                fmt.money(year.owner_withdrawals, symbol=False)])
            self.months.refresh_empty_state()
            self.months.resize_columns()

            # current VAT period
            kind = profile.vat_period or "quarter"
            m_in_fy = ((today.month - profile.fiscal_year_start_month) % 12) + 1
            pnum = m_in_fy if kind == "month" else ((m_in_fy - 1) // 3 + 1 if kind == "quarter" else 1)
            try:
                p = period_of(kind, fiscal_year_of(today, profile.fiscal_year_start_month),
                              pnum, profile.fiscal_year_start_month)
                _rep, decl, _ = reports.build_vat_report(
                    db, kind, p.year, pnum, profile.fiscal_year_start_month,
                    vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
                db.rollback()
                filed = db.query(VatReport).filter_by(
                    period_kind=kind, fiscal_year=p.year, period_number=pnum, locked=True).one_or_none()
                method_note = (" — " + tr("Bokslutsmetoden: siffrorna följer betalningsdatum.")) \
                    if profile.vat_method == "bokslut" else ""
                self.period_lbl.setText(
                    f"{p.label} ({fmt.date(p.start)} → {fmt.date(p.end)}){method_note}\n"
                    f"{tr('Utgående moms')}: {fmt.money(decl.output_vat)}    "
                    f"{tr('Ingående moms (avdragsgill)')}: {fmt.money(decl.input_vat)}    "
                    f"{tr('Att betala') if decl.net_vat_kronor >= 0 else tr('Att få tillbaka')}"
                    f" ({tr('fält')} 49): {fmt.int(decl.net_vat_kronor)} {tr('kr')}\n"
                    + (tr("Deklarerad & låst") if filed else tr("Ej låst")))
            except Exception:
                self.period_lbl.setText("")
        finally:
            db.close()


def Decimal25():
    from decimal import Decimal
    return Decimal("0.25")


def fmt_month(m: int) -> str:
    from ...i18n import month_name
    return month_name(m)
