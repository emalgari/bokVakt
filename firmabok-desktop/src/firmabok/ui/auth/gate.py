"""AuthGate: startup dialog orchestrating the Phase 2 auth screens.

Entry decision (additive wiring in ``ui/main.py``):
  * ``user_accounts`` exist          → Login screen
  * true first run (no accounts)     → Welcome (Create account / Import)
  * legacy users (no accounts, wizard done) never see the gate at all.

Also owns: navigation between screens, "remember email" (login screen),
the .bokvakt archive import (Phase 1 ``restore_backup_archive`` → engine
dispose → re-migrate → Login), auto-login after a password reset, and
Esc = back on sub-screens (Esc on Login/Welcome/Recovery = quit, matching
the wizard's cancel semantics).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
)
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from ...core import accounts
from ...core import config as core_config
from ...core.backup import restore_backup_archive
from ...core.db import get_engine, get_session_factory
from ...core.errors import AuthError, DomainError
from ...core.migrate import run_migrations, seed_reference_data
from ...i18n import LANGS, i18n, init_language, tr
from .common import PasswordField, detach_orm
from .forgot_password_screen import ForgotPasswordScreen
from .login_screen import LoginScreen
from .recovery_code_screen import RecoveryCodeScreen
from .recovery_lost_screen import RecoveryLostScreen
from .signup_screen import SignupScreen
from .welcome_screen import WelcomeScreen

log = logging.getLogger("firmabok.auth")


def accounts_exist(session_factory=None) -> bool:
    """True when at least one local account exists. Safe before migrations
    (missing table → False)."""
    from ...core.models import UserAccount
    factory = session_factory or get_session_factory()
    db = factory()
    try:
        n = db.execute(select(func.count()).select_from(UserAccount)).scalar_one()
        return int(n) > 0
    except SQLAlchemyError:  # pragma: no cover - pre-migration edge
        return False
    finally:
        db.close()


class ArchivePasswordDialog(QDialog):
    """Tiny modal asking for the backup archive password (empty = the
    archive is unencrypted). Separated so tests can bypass it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("bokVakt")
        lay = QVBoxLayout(self)
        title = QLabel()
        title.setObjectName("cardTitle")
        title.setText(tr("Lösenord för backupen"))
        hint = QLabel()
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        hint.setText(tr("Lämna tomt om backupen inte är krypterad."))
        self.field = PasswordField()
        self.field.setFocus()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(title)
        lay.addWidget(hint)
        lay.addWidget(self.field)
        lay.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self._retranslate_buttons()
        i18n.subscribe(self._retranslate_buttons)

    def _retranslate_buttons(self) -> None:
        self._ok.setText(tr("Fortsätt"))
        self._cancel.setText(tr("Avbryt"))

    def password(self) -> str | None:
        i18n.unsubscribe(self._retranslate_buttons)
        self.field.detach_i18n()
        return self.field.text() if self.exec() else None


class AuthGate(QDialog):
    def __init__(self, parent=None, session_factory=None):
        super().__init__(parent)
        self.setWindowTitle("bokVakt")
        self.account = None                 # UserAccount (detached) once accepted
        self._pending_new_account = None    # signup awaiting recovery confirmation
        self._auto_login = None             # (email, password) after a reset
        self._factory = session_factory or get_session_factory()

        self.welcome = WelcomeScreen(self._factory)
        self.login = LoginScreen(self._factory)
        self.signup = SignupScreen(self._factory)
        self.recovery = RecoveryCodeScreen(self._factory)
        self.forgot = ForgotPasswordScreen(self._factory)
        self.lost = RecoveryLostScreen(self._factory)
        self.screens = [self.welcome, self.login, self.signup,
                        self.recovery, self.forgot, self.lost]

        self.stack = QStackedWidget()
        for s in self.screens:
            self.stack.addWidget(s)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self.resize(520, 660)

        self.welcome.create_account_clicked.connect(self.show_signup)
        self.welcome.import_clicked.connect(self.import_archive)
        self.login.login_succeeded.connect(self._on_login)
        self.login.signup_clicked.connect(self.show_signup)
        self.login.forgot_password_clicked.connect(self.show_forgot)
        self.signup.account_created.connect(self._on_account_created)
        self.signup.back_clicked.connect(self._on_signup_back)
        self.recovery.confirmed.connect(self._on_recovery_confirmed)
        self.forgot.reset_completed.connect(self._on_reset_completed)
        self.forgot.back_clicked.connect(self.show_login)
        self.forgot.recovery_lost_clicked.connect(self.show_lost)
        self.lost.back_clicked.connect(self.show_login)

        if accounts_exist(self._factory):
            self.show_login()
        else:
            self.show_welcome()

    # -------------------------------------------------------- navigation
    def _show(self, screen) -> None:
        self.stack.setCurrentWidget(screen)

    def show_welcome(self) -> None:
        self.welcome.clear_banners()
        self._show(self.welcome)

    def show_login(self, prefill: str = "") -> None:
        self.login.clear_banners()
        self.login.reload_remembered()
        if prefill:
            self.login.set_email(prefill)
        self._show(self.login)

    def show_signup(self) -> None:
        email = (self.login.email.text().strip()
                 if self.stack.currentWidget() is self.login else "")
        self.signup.reset_form()
        if email:
            self.signup.set_email(email)
        self._show(self.signup)

    def show_forgot(self) -> None:
        self.forgot.reset_flow(email=self.login.email.text().strip())
        self._show(self.forgot)

    def show_lost(self) -> None:
        self._show(self.lost)

    def _on_login(self, account) -> None:
        self.account = account
        self.accept()

    def _on_signup_back(self) -> None:
        if accounts_exist(self._factory):
            self.show_login()
        else:
            self.show_welcome()

    def _on_account_created(self, account, code: str) -> None:
        self._pending_new_account = account
        self.recovery.set_code(code, is_new=False)
        self._show(self.recovery)

    def _on_reset_completed(self, email: str, password: str, new_code: str) -> None:
        self._auto_login = (email, password)
        self.recovery.set_code(new_code, is_new=True)
        self._show(self.recovery)

    def _on_recovery_confirmed(self) -> None:
        if self._auto_login is not None:
            email, password = self._auto_login
            self._auto_login = None
            db = self._factory()
            try:
                account = accounts.verify_login(db, email, password)
                detach_orm(db, account)
            except AuthError:  # pragma: no cover - password was just set
                log.warning("auto-login after reset failed; showing login")
                self.show_login(prefill=email)
                return
            finally:
                db.close()
            self.account = account
            self.accept()
        elif self._pending_new_account is not None:
            self.account = self._pending_new_account
            self._pending_new_account = None
            self.accept()

    # ------------------------------------------------------------ import
    def _pick_archive(self) -> str:
        from pathlib import Path
        path, _sel = QFileDialog.getOpenFileName(
            self, tr("Välj en bokVakt-backup"), str(Path.home()),
            "bokVakt (*.bokvakt)")
        return path

    def _ask_archive_password(self) -> str | None:
        return ArchivePasswordDialog(self).password()

    def import_archive(self) -> None:
        path = self._pick_archive()
        if not path:
            return
        password = self._ask_archive_password()
        if password is None:  # cancelled
            return
        self.welcome.clear_banners()
        try:
            restore_backup_archive(path, password or None)
        except DomainError as exc:
            log.warning("archive import failed: %s", exc.key)
            screen = self.stack.currentWidget()
            if hasattr(screen, "show_error"):
                screen.show_error(exc.key, **exc.params)
            return
        # The DB file was replaced: drop pooled connections, re-apply any
        # pending migrations and reseed reference data (both idempotent).
        get_engine().dispose()
        run_migrations()
        db = get_session_factory()()
        try:
            seed_reference_data(db)
        finally:
            db.close()
        self._apply_restored_language()
        if accounts_exist():
            self.show_login()
            self.login.show_info("Importen är klar — logga in med kontouppgifterna "
                                 "från backupen.")
        else:
            self.show_welcome()
            self.welcome.show_info("Importerad data innehåller inga konton — "
                                   "skapa ett nytt konto.")

    def _apply_restored_language(self) -> None:
        """settings.json may have been replaced by the restore; adopt its
        language without re-saving it (init_language is the no-persist
        setter), then push it through every screen."""
        lang = core_config.settings().get("language", "sv")
        if lang in LANGS and lang != i18n.language:
            init_language(lang)
        for s in self.screens:
            s.retranslate()
            s.lang_toggle.retranslate()

    # -------------------------------------------------------------- misc
    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            cur = self.stack.currentWidget()
            if cur is self.signup:
                self._on_signup_back()
            elif cur is self.forgot:
                self.forgot.go_back()
            elif cur is self.lost:
                self.show_login()
            else:  # login / welcome / recovery: Esc = quit (wizard semantics)
                self.reject()
            event.accept()
            return
        super().keyPressEvent(event)

    def detach(self) -> None:
        """Unsubscribe every screen from the i18n bus (call after exec())."""
        for s in self.screens:
            s.detach_i18n()

    def closeEvent(self, event):  # noqa: N802
        self.detach()
        super().closeEvent(event)
