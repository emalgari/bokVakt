"""Phase 2: AuthGate orchestration — entry decision, screen navigation,
signup/login/forgot flows end-to-end, .bokvakt archive import, Esc handling.
New file; no existing test is modified.
"""
from __future__ import annotations

import contextlib
import re

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog

from firmabok.core import accounts
from firmabok.core import config as core_config
from firmabok.core.backup import create_backup_archive
from firmabok.core.db import get_engine, get_session_factory
from firmabok.core.models import UserAccount
from firmabok.i18n import i18n, init_language
from firmabok.ui.auth.gate import AuthGate, accounts_exist
from firmabok.ui.auth.login_screen import REMEMBER_KEY
from firmabok.ui.auth.welcome_screen import WelcomeScreen

EMAIL = "gate@example.com"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "nytt-lösenord-9x"
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){5}$")

_LIVE: list = []


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
    while _LIVE:
        g = _LIVE.pop()
        with contextlib.suppress(RuntimeError):  # C++ object already deleted
            g.detach()
    db.query(UserAccount).delete()
    db.commit()
    accounts.reset_rate_limits()
    st = core_config.settings()
    st.set(REMEMBER_KEY, "")
    st.set("language", "sv")
    st.save()
    init_language("sv")


def _gate(qtbot) -> AuthGate:
    g = AuthGate()
    qtbot.addWidget(g)
    _LIVE.append(g)
    return g


def _make_account(db, email=EMAIL, password=PASSWORD, name="Gate Testsson"):
    return accounts.create_account(db, name, email, password)


def _esc(widget):
    widget.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))


# ---------------------------------------------------------------------------
# Entry decision
# ---------------------------------------------------------------------------

def test_entry_welcome_when_no_accounts(qtbot):
    assert not accounts_exist()
    g = _gate(qtbot)
    assert g.stack.currentWidget() is g.welcome
    assert g.result() != QDialog.DialogCode.Accepted


def test_entry_login_when_accounts_exist(qtbot, db):
    _make_account(db)
    assert accounts_exist()
    g = _gate(qtbot)
    assert g.stack.currentWidget() is g.login


# ---------------------------------------------------------------------------
# Full flows through the gate
# ---------------------------------------------------------------------------

def test_signup_flow_through_gate(qtbot):
    g = _gate(qtbot)
    g.welcome.create.click()
    assert g.stack.currentWidget() is g.signup
    g.signup.name.setText("Ny Person")
    g.signup.email.setText("Ny@Example.com")
    g.signup.password.setText(PASSWORD)
    g.signup.confirm.setText(PASSWORD)
    g.signup.submit()
    assert g.stack.currentWidget() is g.recovery
    code = g.recovery.code_label.text()
    assert CODE_RE.match(code)
    assert not g.recovery.button.isEnabled()      # must confirm saving first
    g.recovery.saved_check.setChecked(True)
    g.recovery.button.click()
    assert g.result() == QDialog.DialogCode.Accepted
    assert g.account is not None
    assert g.account.email == "ny@example.com"
    # the account really exists in the DB
    db = get_session_factory()()
    try:
        assert accounts.find_account(db, EMAIL.replace("gate@", "ny@")) is not None
    finally:
        db.close()


def test_login_flow_through_gate(qtbot, db):
    _make_account(db)
    g = _gate(qtbot)
    g.login.email.setText(EMAIL)
    g.login.password.setText(PASSWORD)
    g.login.remember.setChecked(True)
    g.login.submit()
    assert g.result() == QDialog.DialogCode.Accepted
    assert g.account.email == EMAIL
    assert core_config.settings().get(REMEMBER_KEY) == EMAIL


def test_forgot_flow_through_gate_auto_logs_in(qtbot, db):
    _, old_code = _make_account(db)
    g = _gate(qtbot)
    g.login.email.setText(EMAIL)
    g.login.forgot.click()
    assert g.stack.currentWidget() is g.forgot
    assert g.forgot.email.text() == EMAIL          # prefilled from login
    g.forgot.go_next()                             # → step 2
    g.forgot.code.setText(old_code)
    g.forgot.go_next()                             # → step 3
    g.forgot.password.setText(NEW_PASSWORD)
    g.forgot.confirm.setText(NEW_PASSWORD)
    g.forgot.go_next()                             # → submit reset
    assert g.stack.currentWidget() is g.recovery
    new_code = g.recovery.code_label.text()
    assert CODE_RE.match(new_code) and new_code != old_code
    assert g.recovery.heading.text() == "Din nya återställningskod"
    g.recovery.saved_check.setChecked(True)
    g.recovery.button.click()                      # → auto-login → accept
    assert g.result() == QDialog.DialogCode.Accepted
    assert g.account.email == EMAIL
    assert g.account.last_login_at is not None     # auto-login went through verify_login
    # the new password works
    s = get_session_factory()()
    try:
        accounts.verify_login(s, EMAIL, NEW_PASSWORD)
    finally:
        s.close()


def test_lost_code_link_round_trip(qtbot, db):
    _make_account(db)
    g = _gate(qtbot)
    g.login.forgot.click()
    g.forgot.set_step(1)
    g.forgot.lost.click()
    assert g.stack.currentWidget() is g.lost
    g.lost.back.click()
    assert g.stack.currentWidget() is g.login


# ---------------------------------------------------------------------------
# Esc navigation
# ---------------------------------------------------------------------------

def test_esc_back_on_subscreens_quit_on_login(qtbot, db):
    _make_account(db)
    g = _gate(qtbot)
    g.login.signup.click()
    assert g.stack.currentWidget() is g.signup
    _esc(g)
    assert g.stack.currentWidget() is g.login      # Esc = back on signup
    g.login.forgot.click()
    g.forgot.set_step(2)
    _esc(g)
    assert g.forgot.stack.currentIndex() == 1      # Esc = back one step
    _esc(g)
    assert g.forgot.stack.currentIndex() == 0
    _esc(g)
    assert g.stack.currentWidget() is g.login      # step 0 Esc = back to login
    _esc(g)
    assert g.result() == QDialog.DialogCode.Rejected  # Esc on login = quit


def test_esc_on_welcome_quits(qtbot):
    g = _gate(qtbot)
    assert isinstance(g.stack.currentWidget(), WelcomeScreen)
    _esc(g)
    assert g.result() == QDialog.DialogCode.Rejected


# ---------------------------------------------------------------------------
# Archive import (.bokvakt) — reuses the Phase 1 backup API
# ---------------------------------------------------------------------------

def _arm_import(gate, monkeypatch, path, password):
    monkeypatch.setattr(gate, "_pick_archive", lambda: path)
    monkeypatch.setattr(gate, "_ask_archive_password", lambda: password)


def test_import_archive_restores_accounts_and_shows_login(qtbot, db, monkeypatch, tmp_path):
    _make_account(db)
    archive = tmp_path / "import-me.bokvakt"
    create_backup_archive(archive, password="archive-pw")
    # wipe the live accounts so the restore is observable
    db.query(UserAccount).delete()
    db.commit()
    get_engine().dispose()
    assert not accounts_exist()

    g = _gate(qtbot)
    assert g.stack.currentWidget() is g.welcome
    _arm_import(g, monkeypatch, str(archive), "archive-pw")
    g.import_archive()

    assert accounts_exist()
    assert g.stack.currentWidget() is g.login
    assert "Importen är klar" in g.login.info_text.text()
    # imported credentials work again
    s = get_session_factory()()
    try:
        account = accounts.verify_login(s, EMAIL, PASSWORD)
        assert account.email == EMAIL
    finally:
        s.close()


def test_import_wrong_password_changes_nothing(qtbot, db, monkeypatch, tmp_path):
    _make_account(db)
    archive = tmp_path / "sealed.bokvakt"
    create_backup_archive(archive, password="right-pw")
    db.query(UserAccount).delete()
    db.commit()
    get_engine().dispose()

    g = _gate(qtbot)
    _arm_import(g, monkeypatch, str(archive), "wrong-pw")
    g.import_archive()

    assert g.stack.currentWidget() is g.welcome    # stayed put
    assert not g.login.error_banner.isHidden() or not g.welcome.error_banner.isHidden()
    assert "Fel lösenord" in g.welcome.error_text.text()
    assert not accounts_exist()                    # live data untouched


def test_import_cancel_keeps_state(qtbot, monkeypatch):
    g = _gate(qtbot)
    monkeypatch.setattr(g, "_pick_archive", lambda: "")   # dialog cancelled
    g.import_archive()
    assert g.stack.currentWidget() is g.welcome
    monkeypatch.setattr(g, "_pick_archive", lambda: "/tmp/x.bokvakt")
    monkeypatch.setattr(g, "_ask_archive_password", lambda: None)  # password cancelled
    g.import_archive()
    assert g.stack.currentWidget() is g.welcome


def test_import_archive_without_accounts_stays_on_welcome(qtbot, db, monkeypatch, tmp_path):
    archive = tmp_path / "no-accounts.bokvakt"
    create_backup_archive(archive, password="pw12345")     # no accounts exist yet
    g = _gate(qtbot)
    _arm_import(g, monkeypatch, str(archive), "pw12345")
    g.import_archive()
    assert g.stack.currentWidget() is g.welcome
    assert "inga konton" in g.welcome.info_text.text()


def test_import_adopts_restored_language(qtbot, db, monkeypatch, tmp_path):
    _make_account(db)
    i18n.set_language("en")                       # persisted into settings.json
    archive = tmp_path / "english.bokvakt"
    create_backup_archive(archive, password="pw12345")
    i18n.set_language("sv")                       # user switched back since
    db.query(UserAccount).delete()
    db.commit()
    get_engine().dispose()

    g = _gate(qtbot)
    _arm_import(g, monkeypatch, str(archive), "pw12345")
    g.import_archive()

    assert i18n.language == "en"                  # restored settings win
    assert g.login.heading.text() == "Log in"     # every screen retranslated
    assert g.welcome.create.text() == "Create account"
    i18n.set_language("sv")


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def test_gate_detach_unsubscribes(qtbot):
    g = _gate(qtbot)
    n_before = len(i18n._subscribers)
    g.detach()
    assert len(i18n._subscribers) < n_before
    g.detach()                                    # idempotent
