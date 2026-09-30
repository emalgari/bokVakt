"""About dialog."""
from __future__ import annotations

import platform

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ... import __version__
from ...core import config as core_config
from ...i18n import i18n, tr


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        self.title_lbl = QLabel()
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_lbl.setStyleSheet("font-size:20px;font-weight:700;color:#10314F;")
        self.body = QLabel()
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setObjectName("muted")
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.body)
        self.close_btn = QPushButton()
        self.close_btn.clicked.connect(self.accept)
        lay.addWidget(self.close_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr("Om Firmabok"))
        self.title_lbl.setText("Firmabok Desktop")
        self.body.setText(
            f"v{__version__} · Qt {platform.python_version()}\n"
            + tr("Lokal bokföring för enskild firma. All data stannar på din dator.")
            + "\n" + tr("Moms beräknas på försäljning, aldrig på vinst.")
            + f"\n\n{tr('Data')}: {core_config.data_dir()}"
            + f"\n{tr('Licens')}: MIT")
        self.close_btn.setText(tr("Stäng"))

    def accept(self) -> None:
        i18n.unsubscribe(self.retranslate)
        super().accept()
