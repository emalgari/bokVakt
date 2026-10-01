"""Recovery-code-lost screen: an honest, clear message (no email resets, no
backdoors — the app is fully offline) and a way back to the login screen."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel

from ...i18n import i18n, tr
from .. import theme
from .common import AuthScreenBase, ghost_button

MESSAGE_KEY = ("Utan återställningskoden kan lösenordet inte återställas — "
               "det finns ingen e-postutskick eller bakdörr. Din bokföring är "
               "inte förlorad: all data ligger kvar på den här datorn. Har du "
               "en bokVakt-backup (.bokvakt) kan du börja om med en ny "
               "installation, importera backupen och logga in med uppgifterna "
               "från den tiden.")


class RecoveryLostScreen(AuthScreenBase):
    back_clicked = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.message.setStyleSheet(
            f"color:{theme.COLORS['text']}; background:#EEF4FA;"
            " border:1px solid #9DB8D4; border-radius:8px; padding:12px;")
        self.back = ghost_button("Tillbaka till inloggningen", "arrow-left")
        self.back.setDefault(True)
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.back_clicked)
        self.lay.addWidget(self.message)
        self.lay.addWidget(self.back)
        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.back.setFocus()

    def _heading_key(self) -> str:
        return "Tappat bort din återställningskod?"

    def retranslate(self) -> None:
        self.retranslate_base()
        self.message.setText(tr(MESSAGE_KEY))
        self.back.setText(tr("Tillbaka till inloggningen"))
