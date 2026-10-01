"""Local user accounts: Argon2id hashing, recovery codes, login rate limiting.

Pure core layer (Phase 1 foundation — no Qt, no UI, no network). Rules:

* Passwords are hashed with **Argon2id** (argon2-cffi). Plaintext is never
  stored, logged or returned; SHA/MD5/bcrypt are never used.
* A recovery code is shown to the user exactly once (at creation / reset /
  regeneration) and stored only as an Argon2id hash. Every successful use
  **consumes** the code — ``reset_password_with_recovery_code`` returns a
  fresh one.
* Failed logins are rate-limited in memory (per normalized email):
  ``MAX_FAILED_ATTEMPTS`` consecutive failures → ``LOCKOUT_SECONDS`` cooldown.
  The tracker resets on success, when the window elapses, or on app restart
  (deliberate: nothing about auth failures is persisted to disk).
* All errors are :class:`~firmabok.core.errors.AuthError` (a ``DomainError``)
  carrying translation KEYS (``auth.*``) with optional params — the UI
  translates at the boundary via ``i18n.tr(exc.key, **exc.params)``.
* Login never reveals whether an account exists: unknown email and wrong
  password both raise ``auth.invalid_credentials``, and a dummy hash is
  verified to keep timing uniform.

The legacy ``users``/``user_sessions`` tables and ``core.auth`` (scrypt app
lock in settings.json) are untouched; ``user_accounts`` is additive.

Convention (as everywhere in core): the caller passes an open SQLAlchemy
``Session`` as the first argument; functions here commit their own changes.
"""
from __future__ import annotations

import math
import re
import secrets
import time
from datetime import UTC, datetime

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .errors import AuthError
from .models import UserAccount

# ---------------------------------------------------------------------------
# Policy constants (product defaults, not legal values — safe to tune)
# ---------------------------------------------------------------------------

MIN_PASSWORD_LENGTH = 8
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 60.0

#: Argon2id with the argon2-cffi/OWASP interactive baseline (t=3, m=64 MiB,
#: p=4, 32-byte output, 16-byte salt). ``type=Type.ID`` is explicit so a
#: future library default change can never silently downgrade the algorithm.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)

#: Unambiguous alphabet for recovery codes (no I, O, 0, 1).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
#: Public so the UI (input mask / grouped display) always matches the core
#: format. Phase 2 upgrade (approved): 6 groups × 4 chars = 24 characters.
CODE_GROUPS = 6
CODE_GROUP_LEN = 4

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# In-memory rate-limit state: {email: [fail_count, locked_until_monotonic]}.
_attempts: dict[str, list[float]] = {}
_monotonic = time.monotonic  # module attribute so tests can inject a clock


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------

def _hash(secret: str) -> str:
    return _hasher.hash(secret)


def _verify(stored_hash: str, secret: str) -> bool:
    """Constant-time-ish Argon2id verify; False on mismatch or corrupt hash."""
    if not stored_hash or not secret:
        return False
    try:
        return _hasher.verify(stored_hash, secret)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


#: Verified when the email is unknown so response time does not reveal
#: account existence.
_DUMMY_HASH = _hash("bokvakt-dummy-hash-for-timing-equalization")


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _validate_email(email: str) -> str:
    normalized = _normalize_email(email)
    if not _EMAIL_RE.match(normalized):
        raise AuthError("auth.invalid_email")
    return normalized


def _validate_password(password: str) -> None:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError("auth.password_too_short", min_length=MIN_PASSWORD_LENGTH)


def generate_recovery_code() -> str:
    """A fresh single-use recovery code (24 chars), e.g.
    ``K7QM-4TXA-9PZR-2WDH-J6NB-8FKS``."""
    groups = ["".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_GROUP_LEN))
              for _ in range(CODE_GROUPS)]
    return "-".join(groups)


def _normalize_recovery_code(code: str) -> str:
    """Canonical form: upper-case, dash-separated groups of 4. Accepts codes
    typed without dashes / in lower case / with stray whitespace (and any
    group count — older 4-group codes still normalize correctly)."""
    compact = re.sub(r"[^A-Za-z0-9]", "", code or "").upper()
    groups = [compact[i:i + CODE_GROUP_LEN] for i in range(0, len(compact), CODE_GROUP_LEN)]
    return "-".join(groups)


def validate_email_format(email: str) -> str:
    """Public email-format check for UI-side inline validation. Returns the
    normalized (trimmed, lower-case) email; raises ``AuthError`` with key
    ``auth.invalid_email`` when the format is bad. Thin wrapper around the
    internal validator used by account creation/login — same single rule."""
    return _validate_email(email)


# ---------------------------------------------------------------------------
# Rate limiting (in-memory)
# ---------------------------------------------------------------------------

def _check_lockout(email: str) -> None:
    rec = _attempts.get(email)
    if rec is None:
        return
    fails, until = rec
    now = _monotonic()
    if fails >= MAX_FAILED_ATTEMPTS:
        if now < until:
            raise AuthError("auth.too_many_attempts",
                            retry_after=max(1, math.ceil(until - now)))
        _attempts.pop(email, None)  # window elapsed — fresh start


def _register_failure(email: str) -> None:
    """Count a failed login; raises ``auth.too_many_attempts`` once the
    threshold is reached (the 5th failure itself starts the cooldown)."""
    rec = _attempts.setdefault(email, [0.0, 0.0])
    rec[0] += 1
    if rec[0] >= MAX_FAILED_ATTEMPTS:
        rec[1] = _monotonic() + LOCKOUT_SECONDS
        raise AuthError("auth.too_many_attempts", retry_after=int(LOCKOUT_SECONDS))


def _clear_failures(email: str) -> None:
    _attempts.pop(email, None)


def reset_rate_limits() -> None:
    """Clear all in-memory lockout state (used by tests)."""
    _attempts.clear()


# ---------------------------------------------------------------------------
# Account lifecycle
# ---------------------------------------------------------------------------

def find_account(db: Session, email: str) -> UserAccount | None:
    """Look up an account by email (normalized); None when unknown."""
    return db.execute(
        select(UserAccount).where(UserAccount.email == _normalize_email(email))
    ).scalar_one_or_none()


def create_account(db: Session, display_name: str, email: str,
                   password: str) -> tuple[UserAccount, str]:
    """Create a local account. Returns ``(account, recovery_code)`` — the
    recovery code is shown to the user exactly once and never stored in
    plaintext (only its Argon2id hash is)."""
    display_name = (display_name or "").strip()
    if not display_name:
        raise AuthError("auth.display_name_required")
    normalized = _validate_email(email)
    _validate_password(password)
    if find_account(db, normalized) is not None:
        raise AuthError("auth.email_taken")

    recovery_code = generate_recovery_code()
    account = UserAccount(
        display_name=display_name,
        email=normalized,
        password_hash=_hash(password),
        recovery_hash=_hash(_normalize_recovery_code(recovery_code)),
        created_at=datetime.now(UTC),
    )
    db.add(account)
    db.commit()
    return account, recovery_code


def verify_login(db: Session, email: str, password: str) -> UserAccount:
    """Verify credentials; on success updates ``last_login_at`` (and rehashes
    transparently if the stored parameters are outdated). Raises
    ``auth.too_many_attempts`` while locked out, ``auth.invalid_credentials``
    otherwise — identical for unknown email and wrong password."""
    normalized = _normalize_email(email)
    _check_lockout(normalized)
    account = find_account(db, normalized)
    if account is None:
        _verify(_DUMMY_HASH, password or "")  # equalize timing
        ok = False
    else:
        ok = _verify(account.password_hash, password or "")
    if not ok:
        _register_failure(normalized)  # may raise auth.too_many_attempts (5th)
        raise AuthError("auth.invalid_credentials")
    _clear_failures(normalized)
    if _hasher.check_needs_rehash(account.password_hash):  # pragma: no cover
        account.password_hash = _hash(password)
    account.last_login_at = datetime.now(UTC)
    db.commit()
    return account


def change_password(db: Session, account_id: int, current_password: str,
                    new_password: str) -> UserAccount:
    """Change the password after verifying the current one. The recovery code
    is NOT touched (use ``regenerate_recovery_code`` for that)."""
    account = db.get(UserAccount, account_id)
    if account is None:
        raise AuthError("auth.account_not_found")
    if not _verify(account.password_hash, current_password or ""):
        raise AuthError("auth.current_password_wrong")
    _validate_password(new_password)
    account.password_hash = _hash(new_password)
    account.last_password_change_at = datetime.now(UTC)
    db.commit()
    return account


def reset_password_with_recovery_code(db: Session, email: str, recovery_code: str,
                                      new_password: str) -> str:
    """Password reset via recovery code. The used code is consumed; a NEW
    recovery code is generated, stored (hashed) and returned — show it to the
    user exactly once. Raises ``auth.account_not_found``,
    ``auth.no_recovery_code`` (missing/consumed) or
    ``auth.invalid_recovery_code`` (wrong)."""
    account = find_account(db, email)
    if account is None:
        raise AuthError("auth.account_not_found")
    if not account.recovery_hash:
        raise AuthError("auth.no_recovery_code")
    if not _verify(account.recovery_hash, _normalize_recovery_code(recovery_code)):
        raise AuthError("auth.invalid_recovery_code")
    _validate_password(new_password)
    now = datetime.now(UTC)
    new_code = generate_recovery_code()
    account.password_hash = _hash(new_password)
    account.recovery_hash = _hash(_normalize_recovery_code(new_code))
    account.last_password_change_at = now
    account.last_recovery_regen_at = now
    db.commit()
    return new_code


def regenerate_recovery_code(db: Session, account_id: int,
                             current_password: str) -> str:
    """Generate a fresh recovery code (invalidating the old one) after
    verifying the account password. Returns the new code — shown exactly
    once, stored only as an Argon2id hash."""
    account = db.get(UserAccount, account_id)
    if account is None:
        raise AuthError("auth.account_not_found")
    if not _verify(account.password_hash, current_password or ""):
        raise AuthError("auth.current_password_wrong")
    code = generate_recovery_code()
    account.recovery_hash = _hash(_normalize_recovery_code(code))
    account.last_recovery_regen_at = datetime.now(UTC)
    db.commit()
    return code
