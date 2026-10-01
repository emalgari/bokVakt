"""First-run welcome screen: create a local account OR import existing data
from an encrypted bokVakt backup archive (.bokvakt — Phase 1 format)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from ...i18n import i18n, tr
from .. import theme
from .common import AuthScreenBase, secondary_button


class WelcomeScreen(AuthScreenBase):
    create_account_clicked = Signal()
    import_clicked = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self.shield = QLabel()
        self.shield.setPixmap(
            theme.icon("shield-check", color=theme.COLORS["primary"]).pixmap(40, 40))
        self.shield.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.create = QPushButton()
        self.create.setIcon(theme.icon("user-plus", color="#FFFFFF"))
        self.create.setDefault(True)
        self.create.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create.clicked.connect(self.create_account_clicked)
        self.import_btn = secondary_button("", "hard-drive")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.clicked.connect(self.import_clicked)
        self.lay.addWidget(self.shield, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.lay.addWidget(self.create)
        self.lay.addWidget(self.import_btn)
        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.create.setFocus()

    def _heading_key(self) -> str:
        return "Välkommen till bokVakt"

    def _subtitle_key(self) -> str:
        return ("Skapa ett lokalt konto för att komma igång. "
                "All data stannar på din dator.")

    def retranslate(self) -> None:
        self.retranslate_base()
        self.shield.setAccessibleName(tr("Lokal och krypterad"))
        self.create.setText(tr("Skapa konto"))
        self.import_btn.setText(tr("Importera befintlig data"))
        self.import_btn.setToolTip(
            tr("Importera från en krypterad bokVakt-backup (.bokvakt)"))
