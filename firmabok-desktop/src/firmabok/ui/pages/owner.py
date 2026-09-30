"""Owner finances page (egna uttag / insättningar)."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from sqlalchemy import select

from ...core import audit
from ...core.invoices import get_profile
from ...core.models import OwnerTransaction, OwnerTxType
from ...core.money import q2, sum_money
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import fmt, tr
from .. import theme
from ..translatable import Translatable
from ..widgets.cards import Banner, Card, PageHeader, StatCard
from ..widgets.tables import DataTable

COLUMNS = [("Datum", "l"), ("Typ", "l"), ("Belopp", "r"), ("Beskrivning", "l"), ("Referens", "l")]


class OwnerPage(Translatable):
    page_id = "owner"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Ägarfinanser — egna uttag & insättningar")
        self.year_spin = QSpinBox(); self.year_spin.setRange(2000, 2100)
        self.year_spin.valueChanged.connect(self.reload)
        self.header.add_action(self.year_spin)
        lay.addWidget(self.header)

        self.notice = Banner("info")
        self.notice.set_text("Egna uttag och egna insättningar är privata transaktioner mellan dig "
                             "och firman. De är inte företagets intäkter eller kostnader, påverkar "
                             "inte resultatet och har ingen momseffekt.")
        lay.addWidget(self.notice)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(12)
        self.card_out = StatCard("Egna uttag")
        self.card_in = StatCard("Egna insättningar")
        self.card_net = StatCard("Netto")
        self._stat_cards = (self.card_out, self.card_in, self.card_net)
        lay.addLayout(self.cards_grid)
        self._layout_cards()

        self.table = DataTable(COLUMNS, empty_key="Inga transaktioner i år.")
        wrap = Card("")
        wrap.body.addWidget(self.table)
        lay.addWidget(wrap, 1)

        actions = QHBoxLayout()
        self.btn_new = QPushButton(tr("Registrera transaktion"))
        self.btn_new.setIcon(theme.icon("plus"))
        self.btn_new.clicked.connect(self.new_tx)
        self.btn_delete = QPushButton(tr("Radera"))
        self.btn_delete.setProperty("kind", "danger")
        self.btn_delete.setIcon(theme.icon("trash"))
        self.btn_delete.clicked.connect(self.delete_tx)
        actions.addWidget(self.btn_new)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)
        lay.addLayout(actions)
        self.retranslate()

    def _layout_cards(self) -> None:
        w = self.width() or 1000
        cols = 3 if w >= 900 else 1
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
        self.notice.set_text("Egna uttag och egna insättningar är privata transaktioner mellan dig "
                             "och firman. De är inte företagets intäkter eller kostnader, påverkar "
                             "inte resultatet och har ingen momseffekt.")
        self.btn_new.setText(tr("Registrera transaktion"))
        self.btn_delete.setText(tr("Radera"))
        self.reload()

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
            start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
            txs = db.execute(select(OwnerTransaction)
                             .where(OwnerTransaction.tx_date >= start, OwnerTransaction.tx_date <= end)
                             .order_by(OwnerTransaction.tx_date.desc(),
                                       OwnerTransaction.id.desc())).scalars().all()
            self._txs = txs
            uttag = sum_money(t.amount for t in txs if t.tx_type == OwnerTxType.UTTAG.value)
            insatt = sum_money(t.amount for t in txs if t.tx_type == OwnerTxType.INSATTNING.value)
            self.card_out.set_values(fmt.money(uttag), tone="neg")
            self.card_in.set_values(fmt.money(insatt), tone="pos")
            self.card_net.set_values(fmt.money(q2(insatt - uttag)),
                                     tr("positivt = mer insatt än uttaget"))
            self.table.clear_rows()
            for t in txs:
                self.table.add_row([
                    fmt.date(t.tx_date),
                    tr("Eget uttag") if t.tx_type == OwnerTxType.UTTAG.value else tr("Insättning"),
                    fmt.money(t.amount, symbol=False), t.description, t.reference])
            self.table.refresh_empty_state()
            self.table.resize_columns()
        finally:
            db.close()

    def new_tx(self) -> None:
        from ..dialogs.forms import OwnerDialog as Dlg
        dlg = Dlg(self.window())
        if dlg.exec() and getattr(dlg, "result_tx", None):
            db = self.ctx.session()
            try:
                tx = dlg.result_tx
                db.add(tx)
                db.flush()
                label = tr("Eget uttag") if tx.tx_type == OwnerTxType.UTTAG.value else tr("Insättning")
                audit.log(db, "desktop", "create", "OwnerTransaction", tx.id,
                          summary=f"{label} {tx.amount} {tx.tx_date}")
                db.commit()
                self.ctx.toast(f"{label} {fmt.money(tx.amount)} — "
                               + tr("sparad. (Påverkar varken resultat eller moms.)"), "success")
                self.reload()
            finally:
                db.close()

    def delete_tx(self) -> None:
        row = self.table.selected_row()
        if not (0 <= row < len(self._txs)):
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        if not self.ctx.confirm("Radera transaktionen?"):
            return
        db = self.ctx.session()
        try:
            tx = db.merge(self._txs[row])
            audit.log(db, "desktop", "delete", "OwnerTransaction", tx.id,
                      summary=f"{tx.tx_type} {tx.amount}", changes={"row": audit.snapshot(tx)})
            db.delete(tx)
            db.commit()
            self.ctx.toast(tr("Raderad."), "success")
            self.reload()
        finally:
            db.close()
