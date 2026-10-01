"""Login screen: email + password, remember-email, forgot-password / create
account links, and visible rate-limit feedback (banner + countdown).

Reuses ``core.accounts.verify_login`` — identical errors for unknown email
and wrong password; on ``auth.too_many_attempts`` the form locks with a
visible countdown driven by the core-provided ``retry_after`` seconds.
"Remember me" persists ONLY the email (settings.json) — never a password,
never a session; the password is required on every start.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPushButton

from ...core import accounts
from ...core import config as core_config
from ...core.errors import AuthError
from ...i18n import i18n, tr
from .. import theme
from .common import AuthField, AuthScreenBase, PasswordField, detach_orm

REMEMBER_KEY = "auth.remembered_email"


class LoginScreen(AuthScreenBase):
    login_succeeded = Signal(object)      # UserAccount (detached)
    forgot_password_clicked = Signal()
    signup_clicked = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self._lock_left = 0
        self._busy = False
        self._lockout_timer = QTimer(self)
        self._lockout_timer.setInterval(1000)
        self._lockout_timer.timeout.connect(self.tick_lockout)

        self.email = QLineEdit()
        self.email.setPlaceholderText("namn@example.com")
        self.email_field = AuthField("E-post", self.email)
        self.password = PasswordField()
        self.password_field = AuthField("Lösenord", self.password)
        self.remember = QCheckBox()
        self.button = QPushButton()
        self.button.setIcon(theme.icon("log-in", color="#FFFFFF"))
        self.button.setDefault(True)
        self.button.clicked.connect(self.submit)
        self.forgot = QPushButton()
        self.forgot.setProperty("kind", "ghost")
        self.forgot.setAutoDefault(False)
        self.forgot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forgot.clicked.connect(self.forgot_password_clicked)
        self.signup = QPushButton()
        self.signup.setProperty("kind", "ghost")
        self.signup.setAutoDefault(False)
        self.signup.setIcon(theme.icon("user-plus", color=theme.COLORS["primary"]))
        self.signup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.signup.clicked.connect(self.signup_clicked)
        links = QHBoxLayout()
        links.addWidget(self.forgot)
        links.addStretch(1)
        links.addWidget(self.signup)

        self.lay.addWidget(self.email_field)
        self.lay.addWidget(self.password_field)
        self.lay.addWidget(self.remember)
        self.lay.addWidget(self.button)
        self.lay.addLayout(links)

        # remember-email prefill (the only thing "Remember me" stores)
        remembered = str(core_config.settings().get(REMEMBER_KEY, "") or "")
        if remembered:
            self.email.setText(remembered)
            self.remember.setChecked(True)

        i18n.subscribe(self.retranslate)
        self.retranslate()
        (self.password if remembered else self.email).setFocus()

    # ------------------------------------------------------------- labels
    def _heading_key(self) -> str:
        return "Logga in"

    def _subtitle_key(self) -> str:
        return "Logga in för att fortsätta"

    def retranslate(self) -> None:
        self.retranslate_base()
        self.remember.setText(tr("Kom ihåg mig"))
        self.remember.setToolTip(tr("Fyller i din e-postadress nästa gång. "
                                    "Lösenordet sparas aldrig."))
        self.forgot.setText(tr("Glömt lösenord?"))
        self.signup.setText(tr("Skapa konto"))
        if self._lock_left > 0:
            self.button.setText(tr("Vänta {seconds} s…", seconds=self._lock_left))
        elif not self._busy:
            self.button.setText(tr("Logga in"))

    # ------------------------------------------------------------ submit
    def submit(self) -> None:
        if self._busy or self._lock_left > 0:
            return
        self.clear_banners()
        self.email_field.set_error(None)
        self.password_field.set_error(None)
        email = self.email.text().strip()
        password = self.password.text()
        if not email:
            self.email_field.set_error("auth.invalid_email")
            self.email.setFocus()
            return
        self._busy = True
        self.button.setEnabled(False)
        self.button.setText(tr("Loggar in…"))
        db = self.session()
        try:
            account = accounts.verify_login(db, email, password)
            detach_orm(db, account)
        except AuthError as exc:
            self._busy = False
            self.show_error_from(exc)
            if exc.key == "auth.too_many_attempts":
                self.begin_lockout(int(exc.params.get("retry_after", 60)))
            else:
                self.button.setEnabled(True)
                self.retranslate()
                self.password.selectAll()
                self.password.setFocus()
            return
        finally:
            db.close()
        self._busy = False
        self.button.setEnabled(True)
        self.retranslate()
        self._persist_remember(account.email)
        self.password.clear()
        self.login_succeeded.emit(account)

    def _persist_remember(self, email: str) -> None:
        st = core_config.settings()
        st.set(REMEMBER_KEY, email if self.remember.isChecked() else "")
        st.save()

    # ---------------------------------------------------------- lockout UI
    def begin_lockout(self, seconds: int) -> None:
        self._lock_left = max(1, int(seconds))
        for w in (self.email, self.password, self.remember):
            w.setEnabled(False)
        self.button.setEnabled(False)
        self.retranslate()
        self._lockout_timer.start()

    def tick_lockout(self) -> None:
        self._lock_left -= 1
        if self._lock_left <= 0:
            self._lockout_timer.stop()
            self._lock_left = 0
            for w in (self.email, self.password, self.remember):
                w.setEnabled(True)
            self.button.setEnabled(True)
            self.retranslate()
            self.password.setFocus()
        else:
            self.retranslate()

    def set_email(self, email: str) -> None:
        self.email.setText(email)
        self.password.clear()
        self.password.setFocus()

    def reload_remembered(self) -> None:
        """Re-read the remembered email (settings.json may have been replaced
        by an archive import since this screen was built)."""
        if self.email.text().strip():
            return
        remembered = str(core_config.settings().get(REMEMBER_KEY, "") or "")
        if remembered:
            self.email.setText(remembered)
            self.remember.setChecked(True)
