"""Phase 1: local accounts — Argon2id hashing, recovery codes, rate limiting.

New file; no existing test is modified. The `db` fixture (conftest) does not
truncate `user_accounts`, so this module manages those rows itself.
"""
from __future__ import annotations

import re

import pytest
from argon2 import PasswordHasher, Type

from firmabok.core import accounts
from firmabok.core.errors import AuthError
from firmabok.core.models import UserAccount

EMAIL = "test@example.com"
PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "nytt-lösenord-9x"
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}(?:-[A-HJ-NP-Z2-9]{4}){3}$")


@pytest.fixture(autouse=True)
def _clean_accounts(db):
    db.query(UserAccount).delete()
    db.commit()
    accounts.reset_rate_limits()
    yield
    db.query(UserAccount).delete()
    db.commit()
    accounts.reset_rate_limits()


@pytest.fixture()
def clock(monkeypatch):
    """Fake monotonic clock: t[0] += n advances time by n seconds."""
    t = [1000.0]
    monkeypatch.setattr(accounts, "_monotonic", lambda: t[0])
    return t


def _make(db, email=EMAIL, password=PASSWORD, name="Test Testsson"):
    return accounts.create_account(db, name, email, password)


# ---------------------------------------------------------------------------
# Creation & hashing
# ---------------------------------------------------------------------------

def test_create_account_returns_account_and_recovery_code(db):
    account, code = _make(db)
    assert account.id is not None
    assert account.display_name == "Test Testsson"
    assert account.email == EMAIL
    assert CODE_RE.match(code), code
    assert account.created_at is not None
    assert account.last_login_at is None
    assert account.last_password_change_at is None
    assert account.last_recovery_regen_at is None


def test_passwords_and_codes_stored_as_argon2id_never_plaintext(db):
    account, code = _make(db)
    # Algorithm is Argon2id — asserted on the serialized hash itself.
    assert account.password_hash.startswith("$argon2id$v=19$")
    assert account.recovery_hash.startswith("$argon2id$v=19$")
    # The hasher is explicitly pinned to Argon2id.
    assert accounts._hasher.type is Type.ID
    # No plaintext anywhere in the stored values.
    assert PASSWORD not in account.password_hash
    assert code not in account.recovery_hash
    assert code.replace("-", "") not in account.recovery_hash
    # And the stored hashes really verify against the secrets.
    ph = PasswordHasher()
    assert ph.verify(account.password_hash, PASSWORD)
    assert ph.verify(account.recovery_hash, code)


def test_email_is_normalized(db):
    account, _ = _make(db, email="  Test@Example.COM ")
    assert account.email == "test@example.com"
    found = accounts.find_account(db, "TEST@example.com")
    assert found is not None and found.id == account.id


def test_duplicate_email_rejected(db):
    _make(db)
    with pytest.raises(AuthError) as exc:
        _make(db, email="TEST@example.com")
    assert exc.value.key == "auth.email_taken"


def test_validation_errors(db):
    with pytest.raises(AuthError) as exc:
        _make(db, password="short")
    assert exc.value.key == "auth.password_too_short"
    assert exc.value.params["min_length"] == accounts.MIN_PASSWORD_LENGTH
    with pytest.raises(AuthError) as exc:
        _make(db, email="inte-en-epost")
    assert exc.value.key == "auth.invalid_email"
    with pytest.raises(AuthError) as exc:
        _make(db, name="   ")
    assert exc.value.key == "auth.display_name_required"


# ---------------------------------------------------------------------------
# Login & rate limiting
# ---------------------------------------------------------------------------

def test_verify_login_success_updates_last_login(db):
    account, _ = _make(db)
    assert account.last_login_at is None
    logged_in = accounts.verify_login(db, EMAIL, PASSWORD)
    assert logged_in.id == account.id
    assert logged_in.last_login_at is not None
    # case/whitespace-insensitive email
    again = accounts.verify_login(db, " Test@Example.com ", PASSWORD)
    assert again.id == account.id


def test_verify_login_wrong_password(db):
    account, _ = _make(db)
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, EMAIL, "fel-lösenord")
    assert exc.value.key == "auth.invalid_credentials"
    db.refresh(account)
    assert account.last_login_at is None


def test_verify_login_unknown_email_same_generic_error(db):
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, "ingen@example.com", PASSWORD)
    assert exc.value.key == "auth.invalid_credentials"


def test_rate_limit_five_failures_then_60s_cooldown(db, clock):
    _make(db)
    for _ in range(accounts.MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError) as exc:
            accounts.verify_login(db, EMAIL, "wrong")
        assert exc.value.key == "auth.invalid_credentials"
    # The 5th failure starts the cooldown.
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, EMAIL, "wrong")
    assert exc.value.key == "auth.too_many_attempts"
    assert exc.value.params["retry_after"] == 60
    # Even the CORRECT password is rejected while locked out.
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, EMAIL, PASSWORD)
    assert exc.value.key == "auth.too_many_attempts"
    # Just before the window ends: still locked.
    clock[0] += accounts.LOCKOUT_SECONDS - 1
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, EMAIL, PASSWORD)
    assert exc.value.key == "auth.too_many_attempts"
    assert 1 <= exc.value.params["retry_after"] <= 2
    # After the cooldown: login works and the counter is cleared.
    clock[0] += 2
    account = accounts.verify_login(db, EMAIL, PASSWORD)
    assert account.last_login_at is not None
    with pytest.raises(AuthError) as exc:
        accounts.verify_login(db, EMAIL, "wrong")
    assert exc.value.key == "auth.invalid_credentials"  # counter restarted


def test_successful_login_clears_failure_counter(db):
    _make(db)
    for _ in range(3):
        with pytest.raises(AuthError):
            accounts.verify_login(db, EMAIL, "wrong")
    accounts.verify_login(db, EMAIL, PASSWORD)  # resets
    for _ in range(4):
        with pytest.raises(AuthError) as exc:
            accounts.verify_login(db, EMAIL, "wrong")
        assert exc.value.key == "auth.invalid_credentials"  # never hit the limit


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------

def test_recovery_code_reset_flow(db):
    account, code = _make(db)
    new_code = accounts.reset_password_with_recovery_code(db, EMAIL, code, NEW_PASSWORD)
    assert CODE_RE.match(new_code) and new_code != code
    db.refresh(account)
    assert account.last_password_change_at is not None
    assert account.last_recovery_regen_at is not None
    # New password works, old does not.
    accounts.verify_login(db, EMAIL, NEW_PASSWORD)
    with pytest.raises(AuthError):
        accounts.verify_login(db, EMAIL, PASSWORD)
    # The used code is consumed (single-use).
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, EMAIL, code, "annat-lösen-1")
    assert exc.value.key == "auth.invalid_recovery_code"
    # The fresh code works.
    accounts.reset_password_with_recovery_code(db, EMAIL, new_code, "tredje-lösen-1")
    accounts.verify_login(db, EMAIL, "tredje-lösen-1")


def test_recovery_code_typed_lowercase_without_dashes(db):
    _, code = _make(db)
    messy = f"  {code.replace('-', '').lower()} "
    new_code = accounts.reset_password_with_recovery_code(db, EMAIL, messy, NEW_PASSWORD)
    assert CODE_RE.match(new_code)
    accounts.verify_login(db, EMAIL, NEW_PASSWORD)


def test_recovery_code_wrong(db):
    account, _ = _make(db)
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, EMAIL, "FEL1-KOD2-HAR3-Nu4",
                                                   NEW_PASSWORD)
    assert exc.value.key == "auth.invalid_recovery_code"
    # Password unchanged; the account still has its (unconsumed) code.
    with pytest.raises(AuthError):
        accounts.verify_login(db, EMAIL, NEW_PASSWORD)
    accounts.verify_login(db, EMAIL, PASSWORD)
    db.refresh(account)
    assert account.recovery_hash != ""


def test_recovery_code_missing(db):
    account, _ = _make(db)
    account.recovery_hash = ""  # consumed / never issued
    db.commit()
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, EMAIL, "VAD1-SOM2-HELST3",
                                                   NEW_PASSWORD)
    assert exc.value.key == "auth.no_recovery_code"


def test_recovery_reset_unknown_email(db):
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, "ingen@example.com", "X", NEW_PASSWORD)
    assert exc.value.key == "auth.account_not_found"


def test_recovery_reset_weak_new_password_keeps_code(db):
    _, code = _make(db)
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, EMAIL, code, "kort")
    assert exc.value.key == "auth.password_too_short"
    # The code was NOT consumed by the failed attempt.
    new_code = accounts.reset_password_with_recovery_code(db, EMAIL, code, NEW_PASSWORD)
    assert new_code != code


# ---------------------------------------------------------------------------
# Password change & recovery regeneration
# ---------------------------------------------------------------------------

def test_change_password(db):
    account, _ = _make(db)
    accounts.change_password(db, account.id, PASSWORD, NEW_PASSWORD)
    db.refresh(account)
    assert account.last_password_change_at is not None
    accounts.verify_login(db, EMAIL, NEW_PASSWORD)
    with pytest.raises(AuthError):
        accounts.verify_login(db, EMAIL, PASSWORD)


def test_change_password_wrong_current(db):
    account, _ = _make(db)
    with pytest.raises(AuthError) as exc:
        accounts.change_password(db, account.id, "fel-aktuellt", NEW_PASSWORD)
    assert exc.value.key == "auth.current_password_wrong"
    accounts.verify_login(db, EMAIL, PASSWORD)  # unchanged


def test_change_password_unknown_account(db):
    with pytest.raises(AuthError) as exc:
        accounts.change_password(db, 999999, PASSWORD, NEW_PASSWORD)
    assert exc.value.key == "auth.account_not_found"


def test_regenerate_recovery_code(db):
    account, old_code = _make(db)
    new_code = accounts.regenerate_recovery_code(db, account.id, PASSWORD)
    assert CODE_RE.match(new_code) and new_code != old_code
    db.refresh(account)
    assert account.last_recovery_regen_at is not None
    # Old code no longer accepted, new code is.
    with pytest.raises(AuthError) as exc:
        accounts.reset_password_with_recovery_code(db, EMAIL, old_code, NEW_PASSWORD)
    assert exc.value.key == "auth.invalid_recovery_code"
    accounts.reset_password_with_recovery_code(db, EMAIL, new_code, NEW_PASSWORD)
    accounts.verify_login(db, EMAIL, NEW_PASSWORD)


def test_regenerate_recovery_code_requires_current_password(db):
    account, old_code = _make(db)
    with pytest.raises(AuthError) as exc:
        accounts.regenerate_recovery_code(db, account.id, "fel-lösenord")
    assert exc.value.key == "auth.current_password_wrong"
    # The old code is still valid (nothing was regenerated).
    accounts.reset_password_with_recovery_code(db, EMAIL, old_code, NEW_PASSWORD)


def test_find_account_unknown_returns_none(db):
    assert accounts.find_account(db, "ingen@example.com") is None
