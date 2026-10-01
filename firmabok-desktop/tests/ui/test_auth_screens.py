"""Phase 2: auth screens — login, signup, recovery code, forgot password,
recovery-lost, welcome. Standalone-screen behavior; gate orchestration lives
in test_auth_gate.py. New file; no existing test is modified.
"""
from __future__ import annotations

import contextlib
import re

import pytest
from PySide6.QtWidgets import QApplication

from firmabok.core import accounts
from firmabok.core import config as core_config
from firmabok.core.models import UserAccount
from firmabok.i18n import i18n, init_language
from firmabok.ui.auth.common import password_strength
from firmabok.ui.auth.forgot_password_screen import ForgotPasswordScreen
from firmabok.ui.auth.login_screen import REMEMBER_KEY, LoginScreen
from firmabok.ui.auth.recovery_code_screen import RecoveryCodeScreen
from firmabok.ui.auth.recovery_lost_screen import RecoveryLostScreen
from firmabok.ui.auth.signup_screen import SignupScreen
from firmabok.ui.auth.welcome_screen import WelcomeScreen

EMAIL = "ui@example.com"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "nytt-lösenord-9x"
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){5}$")


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(UserAccount).delete()
    db.commit()
    accounts.reset_rate_limits()
    st = core_config.settings()
    st.set(REMEMBER_KEY, "")
    st.save()
    init_language("sv")
    yield
    db.query(UserAccount).delete()
    db.commit()
    accounts.reset_rate_limits()
    st = core_config.settings()
    st.set(REMEMBER_KEY, "")
    st.set("language", "sv")
    st.save()
    init_language("sv")
    while _LIVE:
        widget = _LIVE.pop()
        with contextlib.suppress(RuntimeError):  # C++ object already deleted
            widget.detach_i18n()


@pytest.fixture()
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(accounts, "_monotonic", lambda: t[0])
    return t


def _make_account(db, email=EMAIL, password=PASSWORD, name="UI Testsson"):
    return accounts.create_account(db, name, email, password)


_LIVE: list = []


def _managed(qtbot, screen):
    qtbot.addWidget(screen)
    _LIVE.append(screen)
    return screen


# ---------------------------------------------------------------------------
# Login screen
# ---------------------------------------------------------------------------

def test_login_success_emits_account(qtbot, db):
    _make_account(db)
    s = _managed(qtbot, LoginScreen())
    got = []
    s.login_succeeded.connect(got.append)
    s.email.setText(EMAIL)
    s.password.setText(PASSWORD)
    s.submit()
    assert len(got) == 1
    assert got[0].email == EMAIL
    assert got[0].last_login_at is not None
    assert s.password.text() == ""  # cleared after success


def test_login_wrong_password_shows_generic_error(qtbot, db):
    _make_account(db)
    s = _managed(qtbot, LoginScreen())
    got = []
    s.login_succeeded.connect(got.append)
    s.email.setText(EMAIL)
    s.password.setText("fel-lösenord")
    s.submit()
    assert not got
    assert not s.error_banner.isHidden()
    assert s.error_text.text() == "Fel e-postadress eller lösenord."
    init_language("en")
    s.submit()
    assert s.error_text.text() == "Incorrect email or password."


def test_login_unknown_email_same_error(qtbot, db):
    s = _managed(qtbot, LoginScreen())
    s.email.setText("ingen@example.com")
    s.password.setText("x" * 12)
    s.submit()
    assert s.error_text.text() == "Fel e-postadress eller lösenord."


def test_login_empty_email_inline_error(qtbot):
    s = _managed(qtbot, LoginScreen())
    s.submit()
    assert not s.email_field.error.isHidden()
    assert s.email_field.error.text() == "Ogiltig e-postadress."


def test_login_rate_limit_feedback(qtbot, db, clock):
    _make_account(db)
    s = _managed(qtbot, LoginScreen())
    # pre-arm the core lockout (5 recorded failures, 60 s cooldown)
    accounts._attempts[EMAIL] = [float(accounts.MAX_FAILED_ATTEMPTS),
                                 accounts._monotonic() + 60]
    s.email.setText(EMAIL)
    s.password.setText(PASSWORD)
    s.submit()
    assert not s.error_banner.isHidden()
    assert "För många" in s.error_text.text()
    assert s._lockout_timer.isActive()
    s._lockout_timer.stop()  # drive the countdown deterministically
    assert not s.button.isEnabled()
    assert not s.email.isEnabled() and not s.password.isEnabled()
    assert s._lock_left == 60
    assert s.button.text() == "Vänta 60 s…"
    i18n.set_language("en")
    try:
        assert s.button.text() == "Wait 60 s…"
    finally:
        i18n.set_language("sv")


def test_login_countdown_ticks_and_reenables(qtbot):
    s = _managed(qtbot, LoginScreen())
    s.begin_lockout(2)
    s._lockout_timer.stop()  # drive ticks manually
    assert not s.button.isEnabled() and s.button.text() == "Vänta 2 s…"
    s.tick_lockout()
    assert s.button.text() == "Vänta 1 s…"
    s.tick_lockout()
    assert s.button.isEnabled()
    assert s.button.text() == "Logga in"
    assert s.email.isEnabled() and s.password.isEnabled()


def test_login_rate_limit_end_to_end(qtbot, db, clock):
    """5 real failures through the UI start the lockout (5th attempt)."""
    _make_account(db)
    s = _managed(qtbot, LoginScreen())
    s.email.setText(EMAIL)
    for _ in range(accounts.MAX_FAILED_ATTEMPTS - 1):
        s.password.setText("fel")
        s.submit()
        assert s.button.isEnabled()  # not locked yet
    s.password.setText("fel")
    s.submit()  # 5th failure → lockout begins
    s._lockout_timer.stop()
    assert not s.button.isEnabled()
    assert s._lock_left == int(accounts.LOCKOUT_SECONDS)
    # locked-out submits are ignored entirely
    s._busy = False
    s.password.setText(PASSWORD)
    s.submit()
    assert s._lock_left > 0


def test_remember_me_prefills_and_persists(qtbot, db):
    _make_account(db)
    core_config.settings().set(REMEMBER_KEY, EMAIL)
    s = _managed(qtbot, LoginScreen())
    assert s.email.text() == EMAIL
    assert s.remember.isChecked()
    s.password.setText(PASSWORD)
    s.submit()
    assert core_config.settings().get(REMEMBER_KEY) == EMAIL
    # unchecking clears the stored email on next success
    s2 = _managed(qtbot, LoginScreen())
    s2.remember.setChecked(False)
    s2.password.setText(PASSWORD)
    s2.submit()
    assert core_config.settings().get(REMEMBER_KEY) == ""


def test_login_screen_translates(qtbot):
    s = _managed(qtbot, LoginScreen())
    assert s.heading.text() == "Logga in"
    assert s.remember.text() == "Kom ihåg mig"
    assert s.forgot.text() == "Glömt lösenord?"
    assert s.signup.text() == "Skapa konto"
    i18n.set_language("en")
    try:
        assert s.heading.text() == "Log in"
        assert s.subtitle.text() == "Log in to continue"
        assert s.remember.text() == "Remember me"
        assert s.forgot.text() == "Forgot password?"
        assert s.signup.text() == "Create account"
        assert s.button.text() == "Log in"
    finally:
        i18n.set_language("sv")


# ---------------------------------------------------------------------------
# Signup screen
# ---------------------------------------------------------------------------

def test_signup_inline_validation(qtbot):
    s = _managed(qtbot, SignupScreen())
    got = []
    s.account_created.connect(lambda a, c: got.append((a, c)))
    s.submit()  # everything empty → inline errors, no signal
    assert not got
    assert s.name_field.error.text() == "Visningsnamn krävs."
    s.name.setText("Ny användare")
    s.email.setText("inte-en-mejl")
    s.password.setText("kort")
    s.confirm.setText("annat")
    s.submit()
    assert not got
    assert s.email_field.error.text() == "Ogiltig e-postadress."
    assert "minst 8" in s.password_field.error.text()
    assert s.confirm_field.error.text() == "Lösenorden matchar inte."


def test_signup_creates_account_and_emits_code(qtbot, db):
    s = _managed(qtbot, SignupScreen())
    got = []
    s.account_created.connect(lambda a, c: got.append((a, c)))
    s.name.setText("Ny användare")
    s.email.setText(" Ny@Example.COM ")
    s.password.setText(PASSWORD)
    s.confirm.setText(PASSWORD)
    s.submit()
    assert len(got) == 1
    account, code = got[0]
    assert account.email == "ny@example.com"
    assert CODE_RE.match(code)
    stored = db.query(UserAccount).one()
    assert stored.email == "ny@example.com"
    assert stored.password_hash != PASSWORD


def test_signup_duplicate_email_maps_to_field(qtbot, db):
    _make_account(db)
    s = _managed(qtbot, SignupScreen())
    s.name.setText("Kopia")
    s.email.setText(EMAIL)
    s.password.setText(PASSWORD)
    s.confirm.setText(PASSWORD)
    s.submit()
    assert s.email_field.error.text() == "E-postadressen används redan av ett konto."
    assert s.error_banner.isHidden()


def test_signup_strength_meter_live(qtbot):
    s = _managed(qtbot, SignupScreen())
    assert s.meter.update_password("") == 0
    s.password.setText("password")
    assert s.meter.label.text() == "Mycket svagt"
    s.password.setText("Abcdefghijklmno1!")
    assert s.meter.label.text() == "Starkt"
    i18n.set_language("en")
    try:
        assert s.meter.label.text() == "Strong"
        assert s.meter.caption.text() == "Password strength"
    finally:
        i18n.set_language("sv")


def test_password_strength_levels():
    assert password_strength("") == 0
    assert password_strength("abc12") == 0                     # too short
    assert password_strength("abcdefgh") == 1                  # minimal
    assert password_strength("password") == 1                  # blocklisted
    assert password_strength("PASSWORD") == 1                  # case-insensitive
    assert password_strength("abcdefghijkl") == 2              # long, 1 class
    assert password_strength("Abcdefghijkl") == 3              # long, 2 classes
    assert password_strength("Abcdefghijklmno1") == 4          # longer, 3 classes
    assert password_strength("Abcdefghijklmno1!xyz") == 4      # capped


def test_signup_screen_translates(qtbot):
    s = _managed(qtbot, SignupScreen())
    assert s.heading.text() == "Skapa konto"
    assert s.name_field.label.text() == "Visningsnamn *"
    assert s.back.text() == "Tillbaka"
    i18n.set_language("en")
    try:
        assert s.heading.text() == "Create account"
        assert s.subtitle.text() == "All data stays on your computer."
        assert s.name_field.label.text() == "Display name *"
        assert s.button.text() == "Create account"
        assert s.back.text() == "Back"
    finally:
        i18n.set_language("sv")


# ---------------------------------------------------------------------------
# Recovery code screen
# ---------------------------------------------------------------------------

def test_recovery_code_display_and_gate(qtbot):
    s = _managed(qtbot, RecoveryCodeScreen())
    code = "K7QM-4TXA-9PZR-2WDH-J6NB-8FKS"
    s.set_code(code)
    assert s.code_label.text() == code
    assert s.heading.text() == "Din återställningskod"
    assert not s.button.isEnabled()          # gated by the checkbox
    s.saved_check.setChecked(True)
    assert s.button.isEnabled()
    s.saved_check.setChecked(False)
    assert not s.button.isEnabled()
    s.set_code(code, is_new=True)
    assert s.heading.text() == "Din nya återställningskod"
    assert not s.button.isEnabled()          # checkbox reset with a new code


def test_recovery_code_copy(qtbot):
    s = _managed(qtbot, RecoveryCodeScreen())
    code = "K7QM-4TXA-9PZR-2WDH-J6NB-8FKS"
    s.set_code(code)
    s.copy_code()
    assert QApplication.clipboard().text() == code
    assert s.btn_copy.text() == "Kopierad!"
    s._end_flash()
    assert s.btn_copy.text() == "Kopiera"


def test_recovery_code_download(qtbot, monkeypatch, tmp_path):
    s = _managed(qtbot, RecoveryCodeScreen())
    code = "K7QM-4TXA-9PZR-2WDH-J6NB-8FKS"
    s.set_code(code)
    target = tmp_path / "code-download"          # no .txt on purpose
    monkeypatch.setattr(s, "_pick_save_path", lambda: str(target))
    s.download_code()
    written = tmp_path / "code-download.txt"     # suffix appended
    assert written.is_file()
    body = written.read_text(encoding="utf-8")
    assert code in body
    assert "bokVakt" in body
    assert not s.info_banner.isHidden()
    # cancelling the dialog writes nothing
    monkeypatch.setattr(s, "_pick_save_path", lambda: "")
    s.download_code()
    assert len(list(tmp_path.iterdir())) == 1


def test_recovery_code_print_handler(qtbot, monkeypatch):
    from PySide6 import QtPrintSupport
    s = _managed(qtbot, RecoveryCodeScreen())
    s.set_code("K7QM-4TXA-9PZR-2WDH-J6NB-8FKS")
    opened = []

    class FakeDialog:
        def __init__(self, printer, parent=None):
            opened.append(printer)

        def setWindowTitle(self, title):
            pass

        def exec(self):
            return 0  # rejected → nothing is printed

    monkeypatch.setattr(QtPrintSupport, "QPrintDialog", FakeDialog)
    s.print_code()
    assert len(opened) == 1


def test_recovery_screen_translates(qtbot):
    s = _managed(qtbot, RecoveryCodeScreen())
    s.set_code("K7QM-4TXA-9PZR-2WDH-J6NB-8FKS")
    assert s.btn_copy.text() == "Kopiera"
    assert s.saved_check.text() == "Jag har sparat min återställningskod"
    assert "visas bara en gång" in s.warning_text.text()
    i18n.set_language("en")
    try:
        assert s.btn_copy.text() == "Copy"
        assert s.btn_download.text() == "Download"
        assert s.btn_print.text() == "Print"
        assert s.saved_check.text() == "I have saved my recovery code"
        assert "shown only once" in s.warning_text.text()
    finally:
        i18n.set_language("sv")


# ---------------------------------------------------------------------------
# Forgot password screen
# ---------------------------------------------------------------------------

def test_forgot_step_navigation(qtbot):
    s = _managed(qtbot, ForgotPasswordScreen())
    assert s.stack.currentIndex() == 0
    s.go_next()  # empty email → blocked
    assert s.stack.currentIndex() == 0
    assert not s.email_field.error.isHidden()
    s.email.setText(EMAIL)
    s.go_next()
    assert s.stack.currentIndex() == 1
    assert s.subtitle.text() == "Ange din återställningskod"
    s.go_next()  # incomplete code → blocked
    assert s.stack.currentIndex() == 1
    assert not s.code_field.error.isHidden()
    s.code.setText("k7qm4txa9pzr2wdhj6nb8fks")
    s.go_next()
    assert s.stack.currentIndex() == 2
    assert s.subtitle.text() == "Välj ett nytt lösenord"
    s.go_back()
    assert s.stack.currentIndex() == 1
    s.go_back()
    assert s.stack.currentIndex() == 0
    backs = []
    s.back_clicked.connect(lambda: backs.append(1))
    s.go_back()
    assert backs == [1]


def test_forgot_reset_success_emits_new_code(qtbot, db):
    _, old_code = _make_account(db)
    s = _managed(qtbot, ForgotPasswordScreen())
    got = []
    s.reset_completed.connect(lambda e, p, c: got.append((e, p, c)))
    s.email.setText(EMAIL)
    s.set_step(1)
    s.code.setText(old_code)
    s.set_step(2)
    s.password.setText(NEW_PASSWORD)
    s.confirm.setText(NEW_PASSWORD)
    s.go_next()
    assert len(got) == 1
    email, password, new_code = got[0]
    assert email == EMAIL
    assert password == NEW_PASSWORD
    assert CODE_RE.match(new_code) and new_code != old_code
    # the new password works, the consumed code is dead (fresh session —
    # the db fixture still caches the pre-reset row)
    from firmabok.core.db import get_session_factory
    s2 = get_session_factory()()
    try:
        accounts.verify_login(s2, EMAIL, NEW_PASSWORD)
        with pytest.raises(accounts.AuthError):
            accounts.reset_password_with_recovery_code(s2, EMAIL, old_code, "x" * 12)
    finally:
        s2.close()


def test_forgot_wrong_code_returns_to_step2(qtbot, db):
    _make_account(db)
    s = _managed(qtbot, ForgotPasswordScreen())
    s.email.setText(EMAIL)
    s.set_step(1)
    s.code.setText("AAAA-BBBB-CCCC-DDDD-EEEE-FFFF")
    s.set_step(2)
    s.password.setText(NEW_PASSWORD)
    s.confirm.setText(NEW_PASSWORD)
    s.go_next()
    assert s.stack.currentIndex() == 1
    assert s.code_field.error.text() == "Återställningskoden är fel."


def test_forgot_unknown_email_returns_to_step1(qtbot, db):
    s = _managed(qtbot, ForgotPasswordScreen())
    got = []
    s.reset_completed.connect(lambda *a: got.append(a))
    s.email.setText("ingen@example.com")
    s.set_step(1)
    s.code.setText("AAAA-BBBB-CCCC-DDDD-EEEE-FFFF")
    s.set_step(2)
    s.password.setText(NEW_PASSWORD)
    s.confirm.setText(NEW_PASSWORD)
    s.go_next()
    assert not got
    assert s.stack.currentIndex() == 0
    assert s.email_field.error.text() == "Inget konto med den e-postadressen."


def test_forgot_password_mismatch_blocks(qtbot, db):
    _, code = _make_account(db)
    s = _managed(qtbot, ForgotPasswordScreen())
    got = []
    s.reset_completed.connect(lambda *a: got.append(a))
    s.email.setText(EMAIL)
    s.set_step(1)
    s.code.setText(code)
    s.set_step(2)
    s.password.setText(NEW_PASSWORD)
    s.confirm.setText("helt-annat-lösen")
    s.go_next()
    assert not got
    assert s.confirm_field.error.text() == "Lösenorden matchar inte."
    assert s.stack.currentIndex() == 2


def test_forgot_screen_translates(qtbot):
    s = _managed(qtbot, ForgotPasswordScreen())
    assert s.heading.text() == "Glömt lösenord?"
    assert s.lost.text() == "Har du tappat bort din återställningskod?"
    i18n.set_language("en")
    try:
        assert s.heading.text() == "Forgot password?"
        assert s.subtitle.text() == "Enter the email address of your account"
        assert s.next1.text() == "Next"
        assert s.lost.text() == "Lost your recovery code?"
        s.set_step(2)
        assert s.reset_btn.text() == "Reset password"
    finally:
        init_language("sv")
        s.set_step(0)


# ---------------------------------------------------------------------------
# Recovery-lost & welcome screens
# ---------------------------------------------------------------------------

def test_lost_screen_message_and_back(qtbot):
    s = _managed(qtbot, RecoveryLostScreen())
    assert s.heading.text() == "Tappat bort din återställningskod?"
    assert "bakdörr" in s.message.text()
    backs = []
    s.back_clicked.connect(lambda: backs.append(1))
    s.back.click()
    assert backs == [1]
    i18n.set_language("en")
    try:
        assert s.heading.text() == "Lost your recovery code?"
        assert "backdoor" in s.message.text()
        assert s.back.text() == "Back to login"
    finally:
        i18n.set_language("sv")


def test_welcome_signals_and_translation(qtbot):
    s = _managed(qtbot, WelcomeScreen())
    assert s.heading.text() == "Välkommen till bokVakt"
    creates, imports = [], []
    s.create_account_clicked.connect(lambda: creates.append(1))
    s.import_clicked.connect(lambda: imports.append(1))
    s.create.click()
    s.import_btn.click()
    assert creates == [1] and imports == [1]
    i18n.set_language("en")
    try:
        assert s.heading.text() == "Welcome to bokVakt"
        assert s.create.text() == "Create account"
        assert s.import_btn.text() == "Import existing data"
    finally:
        i18n.set_language("sv")


# ---------------------------------------------------------------------------
# Shared bits: language pill + password field toggle
# ---------------------------------------------------------------------------

def test_language_toggle_switches_instantly(qtbot):
    s = _managed(qtbot, LoginScreen())
    assert s.lang_toggle.buttons["sv"].isChecked()
    s.lang_toggle.buttons["en"].click()
    assert i18n.language == "en"
    assert s.heading.text() == "Log in"
    s.lang_toggle.buttons["sv"].click()
    assert i18n.language == "sv"
    assert s.heading.text() == "Logga in"


def test_password_field_show_hide(qtbot):
    from PySide6.QtWidgets import QLineEdit
    s = _managed(qtbot, SignupScreen())
    pw = s.password
    assert pw.echoMode() == QLineEdit.EchoMode.Password
    pw._toggle.trigger()
    assert pw.echoMode() == QLineEdit.EchoMode.Normal
    pw._toggle.trigger()
    assert pw.echoMode() == QLineEdit.EchoMode.Password
