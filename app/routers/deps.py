"""Shared router dependencies."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, UserSession
from ..security import csrf_ok, get_session


def web_guard(request: Request, db: Session = Depends(get_db)) -> User:
    """Page-level auth: raises 401 (redirected to /login by the app's
    exception handler for HTML requests)."""
    sess = get_session(request, db)
    if sess is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Inte inloggad")
    user = db.get(User, sess.user_id)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Inte inloggad")
    return user


def session_of(request: Request, db: Session) -> UserSession | None:
    return get_session(request, db)


def check_csrf(sess: UserSession, value: str | None) -> bool:
    return csrf_ok(sess, value)
