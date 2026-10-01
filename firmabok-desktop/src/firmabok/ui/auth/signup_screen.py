"""Signup screen: display name, email, password + confirm, strength meter,
show/hide toggles, inline validation. Calls ``core.accounts.create_account``;
keyed ``AuthError``s are mapped to the offending field, anything unexpected
goes to the form-level banner. Emits ``account_created(account, code)`` —
the recovery code must then be shown exactly once (RecoveryCodeScreen).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit, QPushButton

from ...core import accounts
from ...core.errors import AuthError
from ...i18n import i18n, tr
from .. import theme
from .common import (
    AuthField,
    AuthScreenBase,
    PasswordField,
    PasswordStrengthMeter,
    detach_orm,
    ghost_button,
)

#: core AuthError key → which field shows it inline
_FIELD_FOR_KEY = {
    "auth.display_name_required": "name",
    "auth.invalid_email": "email",
    "auth.email_taken": "email",
    "auth.password_too_short": "password",
}


class SignupScreen(AuthScreenBase):
    account_created = Signal(object, str)   # (UserAccount detached, recovery code)
    back_clicked = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self._busy = False
        self._touched = False  # inline validation starts after first submit

        self.name = QLineEdit()
        self.name_field = AuthField("Visningsnamn", self.name, required=True)
        self.email = QLineEdit()
        self.email.setPlaceholderText("namn@example.com")
        self.email_field = AuthField("E-post", self.email, required=True)
        self.password = PasswordField()
        self.password_field = AuthField("Lösenord (minst 8 tecken)", self.password,
                                        required=True)
        self.meter = PasswordStrengthMeter()
        self.confirm = PasswordField()
        self.confirm_field = AuthField("Upprepa lösenord", self.confirm, required=True)

        self.password.textChanged.connect(self._on_password_changed)
        self.confirm.textChanged.connect(lambda _: self._touched and self._validate_live())
        for w in (self.name, self.email):
            w.textChanged.connect(lambda _: self._touched and self._validate_live())

        self.button = QPushButton()
        self.button.setIcon(theme.icon("user-plus", color="#FFFFFF"))
        self.button.setDefault(True)
        self.button.clicked.connect(self.submit)
        self.back = ghost_button("Tillbaka", "arrow-left")
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.back_clicked)

        self.lay.addWidget(self.name_field)
        self.lay.addWidget(self.email_field)
        self.lay.addWidget(self.password_field)
        self.lay.addWidget(self.meter)
        self.lay.addWidget(self.confirm_field)
        self.lay.addWidget(self.button)
        self.lay.addWidget(self.back, alignment=Qt.AlignmentFlag.AlignHCenter)

        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.name.setFocus()

    # ------------------------------------------------------------- labels
    def _heading_key(self) -> str:
        return "Skapa konto"

    def _subtitle_key(self) -> str:
        return "All data stannar på din dator."

    def retranslate(self) -> None:
        self.retranslate_base()
        if not self._busy:
            self.button.setText(tr("Skapa konto"))
        self.back.setText(tr("Tillbaka"))
        if self._touched:
            self._validate_live()

    # ------------------------------------------------- inline validation
    def _clear_field_errors(self) -> None:
        for f in (self.name_field, self.email_field,
                  self.password_field, self.confirm_field):
            f.set_error(None)

    def _validate_live(self) -> None:
        """Non-raising inline checks (email format, length, match)."""
        self._clear_field_errors()
        ok = True
        if not self.name.text().strip():
            self.name_field.set_error("auth.display_name_required")
            ok = False
        email = self.email.text().strip()
        if email:
            try:
                accounts.validate_email_format(email)
            except AuthError as exc:
                self.email_field.set_error(exc.key, **exc.params)
                ok = False
        pw = self.password.text()
        if pw and len(pw) < accounts.MIN_PASSWORD_LENGTH:
            self.password_field.set_error("auth.password_too_short",
                                          min_length=accounts.MIN_PASSWORD_LENGTH)
            ok = False
        if self.confirm.text() and self.confirm.text() != pw:
            self.confirm_field.set_error("Lösenorden matchar inte.")
            ok = False
        return ok

    def _on_password_changed(self, text: str) -> None:
        self.meter.update_password(text)
        if self._touched:
            self._validate_live()

    # ------------------------------------------------------------ submit
    def submit(self) -> None:
        if self._busy:
            return
        self._touched = True
        self.clear_banners()
        if not self._validate_live():
            return
        if self.password.text() != self.confirm.text():
            self.confirm_field.set_error("Lösenorden matchar inte.")
            return
        self._busy = True
        self.button.setEnabled(False)
        self.button.setText(tr("Skapar konto…"))
        db = self.session()
        try:
            account, code = accounts.create_account(
                db, self.name.text(), self.email.text(), self.password.text())
            detach_orm(db, account)
        except AuthError as exc:
            self._busy = False
            self.button.setEnabled(True)
            self.retranslate()
            field = _FIELD_FOR_KEY.get(exc.key)
            if field == "name":
                self.name_field.set_error(exc.key, **exc.params)
            elif field == "email":
                self.email_field.set_error(exc.key, **exc.params)
            elif field == "password":
                self.password_field.set_error(exc.key, **exc.params)
            else:
                self.show_error_from(exc)
            return
        finally:
            db.close()
        self._busy = False
        self.button.setEnabled(True)
        self.retranslate()
        self.account_created.emit(account, code)

    # --------------------------------------------------------------- api
    def reset_form(self, keep_email: bool = False) -> None:
        email = self.email.text() if keep_email else ""
        self.name.clear()
        self.email.setText(email)
        self.password.clear()
        self.confirm.clear()
        self.meter.update_password("")
        self._clear_field_errors()
        self.clear_banners()
        self._touched = False
        self.name.setFocus()

    def set_email(self, email: str) -> None:
        self.email.setText(email)
