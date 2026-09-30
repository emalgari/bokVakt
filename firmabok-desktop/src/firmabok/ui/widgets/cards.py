"""Reusable card/stat/empty-state widgets."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...i18n import i18n, tr


class Card(QFrame):
    """Surface card with optional title. objectName 'card' → QSS styling."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._title_key = title
        self._title = QLabel("") if title else None
        if self._title:
            self._title.setObjectName("cardTitle")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 16, 16, 16)
        self.body.setSpacing(8)
        if self._title:
            self.body.addWidget(self._title)
            self._title.setText(tr(title))
        i18n.subscribe(self.retranslate)

    def set_title(self, key: str) -> None:
        self._title_key = key
        self.retranslate()

    def retranslate(self) -> None:
        if self._title:
            self._title.setText(tr(self._title_key))


class StatCard(Card):
    """Big number + label + optional sub-label."""

    def __init__(self, label_key: str, parent=None):
        super().__init__("", parent)
        self._label_key = label_key
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        self.label = QLabel("")
        self.label.setObjectName("statLabel")
        self.value = QLabel("—")
        self.value.setObjectName("statValue")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        grid.addWidget(self.label, 0, 0)
        grid.addWidget(self.value, 1, 0)
        grid.addWidget(self.sub, 2, 0)
        self.body.addLayout(grid)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def set_values(self, value: str, sub: str = "", tone: str = "") -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        self.value.setProperty("tone", tone)
        style = "color:#1D5C2B;" if tone == "pos" else "color:#8C1D1D;" if tone == "neg" else ""
        self.value.setStyleSheet(f"font-size:24px;font-weight:700;{style}")

    def retranslate(self) -> None:
        super().retranslate()
        self.label.setText(tr(self._label_key))


class EmptyState(QWidget):
    """Icon + message + optional CTA button, shown over empty tables."""

    def __init__(self, message_key: str, cta_key: str = "", on_cta=None, parent=None):
        super().__init__(parent)
        self._message_key = message_key
        self._cta_key = cta_key
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(8)
        self.icon_label = QLabel("")
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setStyleSheet("font-size:32px;color:#A9B2BD;")
        self.message = QLabel("")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color:#667080;")
        lay.addWidget(self.icon_label)
        lay.addWidget(self.message)
        self.cta: QPushButton | None = None
        if cta_key and on_cta:
            self.cta = QPushButton("")
            self.cta.setProperty("kind", "secondary")
            self.cta.clicked.connect(on_cta)
            lay.addWidget(self.cta, alignment=Qt.AlignmentFlag.AlignHCenter)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.icon_label.setText("◫")
        self.message.setText(tr(self._message_key))
        if self.cta:
            self.cta.setText(tr(self._cta_key))


class Banner(QFrame):
    def __init__(self, kind: str = "info", parent=None):
        super().__init__(parent)
        self.setObjectName("bannerDanger" if kind == "danger" else "bannerInfo")
        self.label = QLabel("")
        self.label.setWordWrap(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.addWidget(self.label)

    def set_text(self, key: str, **params) -> None:
        self.label.setText(tr(key, **params))


class PageHeader(QWidget):
    """Page title row with right-aligned action area."""

    def __init__(self, title_key: str, parent=None):
        super().__init__(parent)
        self._title_key = title_key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 8)
        self.title = QLabel("")
        self.title.setObjectName("pageTitle")
        lay.addWidget(self.title)
        lay.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)

    def retranslate(self) -> None:
        self.title.setText(tr(self._title_key))
