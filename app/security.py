"""Local authentication, sessions and CSRF protection.

* Password hashing: hashlib.scrypt (stdlib) with per-user random salt.
* Sessions: opaque random token stored server-side (DB), HttpOnly cookie.
* CSRF: per-session token, double-submit (hidden form field `csrf` or
  header `X-CSRF-Token`).
* No cloud, no external services.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .models import User, UserSession

COOKIE_NAME = "firma_session"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}  # naive in-memory rate limit


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return dk.hex(), salt.hex()


def verify_password(password: str, password_hash: str, salt_hex: str) -> bool:
    try:
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), password_hash)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session(db: Session, user: User) -> UserSession:
    now = datetime.now(timezone.utc)
    sess = UserSession(
        token=secrets.token_urlsafe(48),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + timedelta(days=config.SESSION_DAYS),
        flash="",
    )
    db.add(sess)
    db.commit()
    return sess


def get_session(request: Request, db: Session) -> UserSession | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    sess = db.get(UserSession, token)
    if sess is None:
        return None
    if sess.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(sess)
        db.commit()
        return None
    return sess


def destroy_session(request: Request, db: Session) -> None:
    sess = get_session(request, db)
    if sess is not None:
        db.delete(sess)
        db.commit()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=config.SESSION_DAYS * 86400,
        httponly=True, samesite="lax", secure=False,  # local http only
        path="/",
    )


# ---------------------------------------------------------------------------
# Login throttling
# ---------------------------------------------------------------------------

def check_login_throttle(key: str) -> None:
    now = time.monotonic()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(key, []) if now - t < 300]
    _LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="För många inloggningsförsök. Vänta 5 minuter.")


def record_failed_login(key: str) -> None:
    _LOGIN_ATTEMPTS.setdefault(key, []).append(time.monotonic())


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    sess = get_session(request, db)
    if sess is None:
        raise HTTPException(status_code=401, detail="Inte inloggad")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Inte inloggad")
    return user


def current_session_dep(request: Request, db: Session = Depends(get_db)) -> UserSession:
    sess = get_session(request, db)
    if sess is None:
        raise HTTPException(status_code=401, detail="Inte inloggad")
    return sess


def csrf_ok(sess: UserSession, supplied: str | None) -> bool:
    """Compare a supplied CSRF value (form field `csrf`, header
    `X-CSRF-Token`, or query param) with the session token."""
    return bool(supplied) and hmac.compare_digest(supplied or "", sess.csrf_token)


def require_csrf(request: Request, db: Session = Depends(get_db)) -> None:
    """Dependency form of CSRF validation: checks the X-CSRF-Token header
    or `_csrf` query param. HTML form routes instead pass the `_csrf` form
    field through csrf_ok() in the router (see routers/*.py)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sess = get_session(request, db)
    if sess is None:
        raise HTTPException(status_code=401, detail="Inte inloggad")
    supplied = request.headers.get("X-CSRF-Token") or request.query_params.get("_csrf")
    if not csrf_ok(sess, supplied):
        raise HTTPException(status_code=403, detail="CSRF-validering misslyckades. Ladda om sidan och försök igen.")
