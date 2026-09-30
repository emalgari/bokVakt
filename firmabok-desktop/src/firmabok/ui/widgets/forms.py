"""Form building blocks: label-above fields, locale-tolerant money parsing,
inline error text."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...i18n import i18n, tr


def parse_money(text: str) -> Decimal | None:
    """Parse '1 234,50' / '1,234.50' / '1234.50' / '−5' → Decimal. None if bad."""
    if text is None:
        return None
    s = str(text).strip().replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    s = s.replace("\u2212", "-").replace("−", "-")
    s = "".join(ch for ch in s if ch.isdigit() or ch in ",.-")
    if not s or s in {"-", "."}:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


class LabeledField(QWidget):
    """Label above input + inline error line. ``widget`` is the actual editor."""

    def __init__(self, label_key: str, widget: QWidget, required: bool = False,
                 help_key: str = "", parent=None):
        super().__init__(parent)
        self._label_key = label_key
        self._help_key = help_key
        self._required = required
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.label = QLabel("")
        lay.addWidget(self.label)
        self.widget = widget
        lay.addWidget(widget)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setVisible(False)
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        text = tr(self._label_key) + (" *" if self._required else "")
        self.label.setText(text)
        if self._help_key:
            self.label.setToolTip(tr(self._help_key))

    def set_error(self, message_key: str | None, **params) -> None:
        if message_key:
            self.error.setText(tr(message_key, **params))
            self.error.setVisible(True)
        else:
            self.error.setText("")
            self.error.setVisible(False)


class MoneyEdit(QLineEdit):
    """Money input: locale-tolerant parsing; displays with locale grouping."""

    def set_decimal(self, value: Decimal | None) -> None:
        from ...i18n import fmt
        self.setText("" if value is None else fmt.money(value, symbol=False))

    def decimal(self) -> Decimal | None:
        return parse_money(self.text())


class Form(QFormLayout):
    """Small helper: grid of LabeledFields, 2 columns by default via addRow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setHorizontalSpacing(16)
        self.setVerticalSpacing(10)


def date_edit(d: date | None = None) -> QDateEdit:
    w = QDateEdit()
    w.setCalendarPopup(True)
    w.setDisplayFormat("yyyy-MM-dd")
    if d:
        w.setDate(QDate(d.year, d.month, d.day))
    else:
        w.setDate(QDate.currentDate())
    return w


def date_of(w: QDateEdit) -> date:
    qd = w.date()
    return date(qd.year(), qd.month(), qd.day())


def check_box(label_key: str, checked: bool = False) -> QCheckBox:
    cb = QCheckBox(tr(label_key))
    cb.setChecked(checked)
    cb.setProperty("i18n_key", label_key)
    i18n.subscribe(lambda: cb.setText(tr(label_key)))
    return cb


def combo(options: list[tuple[str, str]], current_value: str = "") -> QComboBox:
    """options: list of (value, label_key)."""
    cb = QComboBox()
    for value, label_key in options:
        cb.addItem(tr(label_key), value)
    idx = cb.findData(current_value)
    if idx >= 0:
        cb.setCurrentIndex(idx)
    def _retranslate():
        for i in range(cb.count()):
            cb.setItemText(i, tr(cb.itemData(i + 0) and _key_for(cb, i) or ""))
    # simpler: store keys in a property list and retranslate
    cb.setProperty("option_keys", [k for _, k in options])
    def _rt():
        keys = cb.property("option_keys") or []
        for i, k in enumerate(keys):
            cb.setItemText(i, tr(k))
    i18n.subscribe(_rt)
    return cb


def _key_for(cb, i):  # pragma: no cover - unused helper
    return ""


def grid(parent=None, cols: int = 2, h=12, v=12):
    from PySide6.QtWidgets import QGridLayout
    g = QGridLayout(parent)
    g.setHorizontalSpacing(h)
    g.setVerticalSpacing(v)
    g.setColumnStretch(cols, 1)
    return g
