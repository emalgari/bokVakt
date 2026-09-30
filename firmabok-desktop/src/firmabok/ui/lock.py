"""Lock screen: shown at start / after logout when a password is configured."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core import config as core_config
from ..core.auth import verify_password
from ..i18n import i18n, tr


class LockScreen(QWidget):
    unlocked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(400)
        lay = QVBoxLayout(card)
        lay.setSpacing(12)
        self.title = QLabel("Firmabok")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size:24px;font-weight:700;color:#10314F;")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub.setWordWrap(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self.try_unlock)
        self.button = QPushButton()
        self.button.clicked.connect(self.try_unlock)
        self.error = QLabel("")
        self.error.setObjectName("fieldError")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error.setVisible(False)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        lay.addWidget(self.password)
        lay.addWidget(self.button)
        lay.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch(1)
        outer.addWidget(card, alignment=Qt.AlignmentFlag.AlignHCenter)
        outer.addLayout(row)
        outer.addStretch(2)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        enabled = core_config.settings().get("auth.enabled", False)
        self.sub.setText(tr("Appen är låst. Ange ditt lösenord.") if enabled
                         else tr("Inget lösenord är valt. Appen kan öppnas direkt — "
                                 "aktivera lösenord i Inställningar → Konto & lösenord."))
        self.password.setVisible(enabled)
        self.button.setText(tr("Lås upp") if enabled else tr("Fortsätt"))
        self.setWindowTitle(tr("Låst"))

    def try_unlock(self) -> None:
        st = core_config.settings()
        if not st.get("auth.enabled", False):
            self.unlocked.emit()
            return
        if verify_password(self.password.text(), st.get("auth.password_hash", ""),
                           st.get("auth.password_salt", "")):
            self.password.clear()
            self.error.setVisible(False)
            self.unlocked.emit()
        else:
            self.error.setText(tr("Fel lösenord."))
            self.error.setVisible(True)
            self.password.selectAll()
            self.password.setFocus()
