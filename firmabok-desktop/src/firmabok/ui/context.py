"""App context shared by pages/dialogs: DB session access, profile, toasts."""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QMessageBox

from ..core.db import get_session_factory
from ..core.errors import DomainError
from ..core.invoices import get_profile
from ..core.models import CompanyProfile
from ..i18n import tr
from .toasts import ToastManager


class AppContext:
    def __init__(self, window: QMainWindow):
        self.window = window
        self.toasts = ToastManager(window)
        self._factory = get_session_factory()

    def session(self):
        return self._factory()

    def profile(self, db) -> CompanyProfile:
        return get_profile(db)

    # ------------------------------------------------------------- feedback
    def toast(self, text: str, kind: str = "info") -> None:
        self.toasts.show(text, kind)

    def status(self, text: str, ms: int = 5000) -> None:
        self.window.statusBar().showMessage(text, ms)

    def error(self, exc: Exception) -> None:
        if isinstance(exc, DomainError):
            self.toast(tr(exc.key, **exc.params), "error")
        else:
            self.toast(str(exc) or exc.__class__.__name__, "error")

    def confirm(self, message_key: str, danger: bool = True, **params) -> bool:
        box = QMessageBox(self.window)
        box.setWindowTitle(tr("Bekräfta åtgärd"))
        box.setText(tr(message_key, **params))
        box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
        yes = box.addButton(tr("Ja, fortsätt"), QMessageBox.ButtonRole.AcceptRole)
        no = box.addButton(tr("Avbryt"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no if danger else yes)
        box.exec()
        return box.clickedButton() is yes

    def info(self, message_key: str, title_key: str = "Information", **params) -> None:
        QMessageBox.information(self.window, tr(title_key), tr(message_key, **params))
