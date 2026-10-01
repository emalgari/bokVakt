"""Recovery code screen: shows the single-use 24-char code (6 × 4 groups)
EXACTLY once, with copy / download / print, a prominent warning and a
required "I have saved it" checkbox that gates Continue.

Used after signup AND after a password reset (a reset consumes the old code
and issues a fresh one — same one-time-showing rule).
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
)

from ...i18n import i18n, tr
from .. import theme
from .common import AuthScreenBase, mono_font

WARNING_KEY = ("Spara koden på en säker plats — den visas bara en gång och "
               "är enda sättet att återställa ditt lösenord.")


class RecoveryCodeScreen(AuthScreenBase):
    confirmed = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self._code = ""
        self._is_new = False
        self._copied_flash = False

        self.warning = QFrame()
        self.warning.setStyleSheet(
            f"background:{theme.COLORS['warning-bg']};"
            " border:1px solid #E0B64A; border-radius:8px;")
        wl = QHBoxLayout(self.warning)
        wl.setContentsMargins(10, 8, 10, 8)
        wicon = QLabel()
        wicon.setPixmap(theme.icon("alert-triangle", color=theme.COLORS["warning"])
                        .pixmap(16, 16))
        wl.addWidget(wicon, alignment=Qt.AlignmentFlag.AlignTop)
        self.warning_text = QLabel("")
        self.warning_text.setWordWrap(True)
        self.warning_text.setStyleSheet(f"color:{theme.COLORS['warning']};")
        wl.addWidget(self.warning_text, 1)

        self.code_label = QLabel("")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setWordWrap(True)
        self.code_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        f = mono_font(15)
        f.setBold(True)
        self.code_label.setFont(f)
        self.code_label.setStyleSheet(
            f"color:{theme.COLORS['primary']}; background:#EEF4FA;"
            " border:1px dashed #9DB8D4; border-radius:8px; padding:12px;")
        self.code_label.setAccessibleName("")

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.btn_copy = QPushButton()
        self.btn_copy.setIcon(theme.icon("copy", color="#FFFFFF"))
        self.btn_copy.setAutoDefault(False)
        self.btn_copy.clicked.connect(self.copy_code)
        self.btn_download = QPushButton()
        self.btn_download.setProperty("kind", "secondary")
        self.btn_download.setIcon(theme.icon("download", color=theme.COLORS["primary"]))
        self.btn_download.setAutoDefault(False)
        self.btn_download.clicked.connect(self.download_code)
        self.btn_print = QPushButton()
        self.btn_print.setProperty("kind", "secondary")
        self.btn_print.setIcon(theme.icon("printer", color=theme.COLORS["primary"]))
        self.btn_print.setAutoDefault(False)
        self.btn_print.clicked.connect(self.print_code)
        for b in (self.btn_copy, self.btn_download, self.btn_print):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            actions.addWidget(b)

        self.saved_check = QCheckBox()
        self.saved_check.toggled.connect(self._update_continue)
        self.button = QPushButton()
        self.button.setIcon(theme.icon("key-round", color="#FFFFFF"))
        self.button.setDefault(True)
        self.button.setEnabled(False)
        self.button.clicked.connect(self.confirmed)

        self.lay.addWidget(self.warning)
        self.lay.addWidget(self.code_label)
        self.lay.addLayout(actions)
        self.lay.addWidget(self.saved_check)
        self.lay.addWidget(self.button)

        i18n.subscribe(self.retranslate)
        self.retranslate()

    # ------------------------------------------------------------- labels
    def _heading_key(self) -> str:
        return "Din nya återställningskod" if self._is_new else "Din återställningskod"

    def retranslate(self) -> None:
        self.retranslate_base()
        self.warning_text.setText(tr(WARNING_KEY))
        self.btn_copy.setText(tr("Kopierad!") if self._copied_flash else tr("Kopiera"))
        self.btn_download.setText(tr("Ladda ner"))
        self.btn_print.setText(tr("Skriv ut"))
        self.saved_check.setText(tr("Jag har sparat min återställningskod"))
        self.button.setText(tr("Fortsätt"))
        self.code_label.setAccessibleName(
            tr("Din återställningskod") + ": " + self._code)

    # ---------------------------------------------------------------- api
    def set_code(self, code: str, is_new: bool = False) -> None:
        self._code = code
        self._is_new = is_new
        self.code_label.setText(code)
        self.saved_check.setChecked(False)
        self._update_continue()
        self.retranslate()

    def _update_continue(self, *_args) -> None:
        self.button.setEnabled(self.saved_check.isChecked() and bool(self._code))

    # ------------------------------------------------------------ actions
    def copy_code(self) -> None:
        QApplication.clipboard().setText(self._code)
        self._copied_flash = True
        self.retranslate()
        QTimer.singleShot(2000, self._end_flash)

    def _end_flash(self) -> None:
        self._copied_flash = False
        self.retranslate()

    def _document(self) -> QTextDocument:
        doc = QTextDocument()
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc.setPlainText(
            f"bokVakt — {tr('Återställningskod')}\n"
            f"{tr('Skapad')}: {when}\n\n"
            f"{self._code}\n\n"
            f"{tr(WARNING_KEY)}\n")
        f = doc.defaultFont()
        f.setFamily("DejaVu Sans Mono")
        doc.setDefaultFont(f)
        return doc

    def _pick_save_path(self) -> str:
        default = f"bokVakt-recovery-code-{datetime.now():%Y-%m-%d}.txt"
        path, _sel = QFileDialog.getSaveFileName(
            self, tr("Spara återställningskod"), default,
            tr("Textfil") + " (*.txt)")
        return path

    def download_code(self) -> None:
        path = self._pick_save_path()
        if not path:
            return
        if not path.lower().endswith(".txt"):
            path += ".txt"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._document().toPlainText())
        self.show_info("Återställningskoden har sparats som fil.")

    def print_code(self) -> None:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle(tr("Skriv ut"))
        if dialog.exec():
            self._document().print_(printer)
