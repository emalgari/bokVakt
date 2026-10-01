"""Forgot-password flow: email → recovery code → new password.

Step 1 deliberately does NOT check whether the account exists (no existence
leak); verification happens inside ``reset_password_with_recovery_code``
whose keyed errors are mapped back to the right step/field. On success the
used code is consumed and a NEW code is returned — the gate shows it on the
RecoveryCodeScreen and then auto-logs-in (``reset_completed``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import accounts
from ...core.errors import AuthError
from ...i18n import i18n, tr
from .. import theme
from .common import (
    AuthField,
    AuthScreenBase,
    PasswordField,
    PasswordStrengthMeter,
    ghost_button,
)

_CODE_MASK = ">" + "-".join("N" * accounts.CODE_GROUP_LEN
                            for _ in range(accounts.CODE_GROUPS))


class ForgotPasswordScreen(AuthScreenBase):
    reset_completed = Signal(str, str, str)   # email, new password, NEW recovery code
    back_clicked = Signal()
    recovery_lost_clicked = Signal()

    def __init__(self, session_factory=None, parent=None):
        super().__init__(session_factory, parent)
        self._busy = False

        self.stack = QStackedWidget()

        # ---- step 1: email ----
        s1 = QWidget()
        l1 = QVBoxLayout(s1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(12)
        self.email = QLineEdit()
        self.email.setPlaceholderText("namn@example.com")
        self.email_field = AuthField("E-post", self.email)
        l1.addWidget(self.email_field)
        self.next1 = QPushButton()
        self.next1.setDefault(True)
        self.next1.clicked.connect(self.go_next)
        l1.addWidget(self.next1)
        self.stack.addWidget(s1)

        # ---- step 2: recovery code ----
        s2 = QWidget()
        l2 = QVBoxLayout(s2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(12)
        self.code = QLineEdit()
        self.code.setInputMask(_CODE_MASK)
        self.code_field = AuthField("Återställningskod", self.code)
        l2.addWidget(self.code_field)
        self.lost = ghost_button("Har du tappat bort din återställningskod?")
        self.lost.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lost.clicked.connect(self.recovery_lost_clicked)
        l2.addWidget(self.lost, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.next2 = QPushButton()
        self.next2.setDefault(True)
        self.next2.clicked.connect(self.go_next)
        l2.addWidget(self.next2)
        self.stack.addWidget(s2)

        # ---- step 3: new password ----
        s3 = QWidget()
        l3 = QVBoxLayout(s3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(12)
        self.password = PasswordField()
        self.password_field = AuthField("Nytt lösenord (minst 8 tecken)", self.password)
        self.meter = PasswordStrengthMeter()
        self.confirm = PasswordField()
        self.confirm_field = AuthField("Upprepa lösenord", self.confirm)
        self.password.textChanged.connect(self._on_password_changed)
        self.confirm.textChanged.connect(lambda _: self._validate_live())
        l3.addWidget(self.password_field)
        l3.addWidget(self.meter)
        l3.addWidget(self.confirm_field)
        self.reset_btn = QPushButton()
        self.reset_btn.setIcon(theme.icon("key-round", color="#FFFFFF"))
        self.reset_btn.setDefault(True)
        self.reset_btn.clicked.connect(self.go_next)
        l3.addWidget(self.reset_btn)
        self.stack.addWidget(s3)

        self.back = ghost_button("Tillbaka", "arrow-left")
        self.back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back.clicked.connect(self.go_back)

        self.lay.addWidget(self.stack)
        self.lay.addWidget(self.back, alignment=Qt.AlignmentFlag.AlignHCenter)

        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.email.setFocus()

    # ------------------------------------------------------------- labels
    def _heading_key(self) -> str:
        return "Glömt lösenord?"

    def _subtitle_key(self) -> str:
        return ("Ange e-postadressen till ditt konto" if self.stack.currentIndex() == 0
                else "Ange din återställningskod" if self.stack.currentIndex() == 1
                else "Välj ett nytt lösenord")

    def retranslate(self) -> None:
        self.retranslate_base()
        self.next1.setText(tr("Nästa"))
        self.next2.setText(tr("Nästa"))
        self.lost.setText(tr("Har du tappat bort din återställningskod?"))
        if not self._busy:
            self.reset_btn.setText(tr("Återställ lösenord"))
        self.back.setText(tr("Tillbaka"))

    # --------------------------------------------------------- navigation
    def set_step(self, step: int) -> None:
        self.stack.setCurrentIndex(max(0, min(2, step)))
        self.clear_banners()
        self.retranslate()
        focus = (self.email, self.code, self.password)[self.stack.currentIndex()]
        focus.setFocus()

    def go_back(self) -> None:
        if self.stack.currentIndex() == 0:
            self.back_clicked.emit()
        else:
            self.set_step(self.stack.currentIndex() - 1)

    def go_next(self) -> None:
        step = self.stack.currentIndex()
        if step == 0:
            self.email_field.set_error(None)
            if not self.email.text().strip():
                self.email_field.set_error("auth.invalid_email")
                return
            self.set_step(1)
        elif step == 1:
            self.code_field.set_error(None)
            if not self.code.hasAcceptableInput():
                self.code_field.set_error("auth.invalid_recovery_code")
                return
            self.set_step(2)
        else:
            self._submit_reset()

    # ---------------------------------------------------------- validation
    def _validate_live(self, *_args, quiet: bool = False) -> None:
        pw = self.password.text()
        if not quiet:
            self.password_field.set_error(None)
            self.confirm_field.set_error(None)
        ok = True
        if pw and len(pw) < accounts.MIN_PASSWORD_LENGTH:
            if not quiet:
                self.password_field.set_error(
                    "auth.password_too_short", min_length=accounts.MIN_PASSWORD_LENGTH)
            ok = False
        if self.confirm.text() and self.confirm.text() != pw:
            if not quiet:
                self.confirm_field.set_error("Lösenorden matchar inte.")
            ok = False
        return ok

    def _on_password_changed(self, text: str) -> None:
        self.meter.update_password(text)
        self._validate_live()

    # -------------------------------------------------------------- submit
    def _submit_reset(self) -> None:
        if self._busy:
            return
        self.clear_banners()
        if not self._validate_live() or self.password.text() != self.confirm.text():
            self.confirm_field.set_error("Lösenorden matchar inte.")
            return
        self._busy = True
        self.reset_btn.setEnabled(False)
        self.reset_btn.setText(tr("Återställer…"))
        db = self.session()
        try:
            new_code = accounts.reset_password_with_recovery_code(
                db, self.email.text(), self.code.text(), self.password.text())
        except AuthError as exc:
            self._busy = False
            self.reset_btn.setEnabled(True)
            self.retranslate()
            if exc.key == "auth.account_not_found":
                self.set_step(0)
                self.email_field.set_error(exc.key, **exc.params)
            elif exc.key in ("auth.invalid_recovery_code", "auth.no_recovery_code"):
                self.set_step(1)
                self.code_field.set_error(exc.key, **exc.params)
            else:
                self.show_error_from(exc)
            return
        finally:
            db.close()
        self._busy = False
        self.reset_btn.setEnabled(True)
        email = self.email.text().strip()
        password = self.password.text()
        self.retranslate()
        self.reset_completed.emit(email, password, new_code)

    # ----------------------------------------------------------------- api
    def reset_flow(self, email: str = "") -> None:
        self.email.setText(email)
        self.code.clear()
        self.password.clear()
        self.confirm.clear()
        self.meter.update_password("")
        self.email_field.set_error(None)
        self.code_field.set_error(None)
        self.password_field.set_error(None)
        self.confirm_field.set_error(None)
        self.clear_banners()
        self.set_step(0)
