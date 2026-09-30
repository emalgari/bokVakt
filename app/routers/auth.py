"""Authentication routes: first-run setup, login, logout."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User
from ..security import (
    check_login_throttle, create_session, destroy_session, hash_password,
    record_failed_login, set_session_cookie, verify_password,
)
from ..security import get_session as get_sess
from ..webutil import tpl_context

router = APIRouter(tags=["auth"])


def templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", include_in_schema=False)
def root(request: Request):
    return RedirectResponse(url="/dashboard", status_code=302)


@router.get("/lang")
def set_lang(request: Request, lang: str = "sv", next: str = "/"):
    """Switch UI language (cookie). Invoices/PDFs remain Swedish always."""
    from ..i18n import COOKIE_NAME, LANGS
    target = next if next.startswith("/") else "/"
    resp = RedirectResponse(url=target, status_code=302)
    if lang in LANGS:
        resp.set_cookie(COOKIE_NAME, lang, max_age=365 * 86400, samesite="lax", path="/")
    return resp


@router.get("/setup")
def setup_page(request: Request, error: str = "", db: Session = Depends(get_db)):
    if db.execute(select(User).limit(1)).scalar_one_or_none() is not None:
        return RedirectResponse(url="/login", status_code=302)
    sess = get_sess(request, db)
    from ..i18n import lang_from_request, translate as _tr
    err_txt = _tr(lang_from_request(request), error.replace("+", " ")) if error else ""
    return templates(request).TemplateResponse(
        request, "setup.html", tpl_context(request, db, sess, action="/setup",
                                  error=err_txt))


@router.post("/setup")
def setup_submit(request: Request,
                 username: str = Form(...),
                 password: str = Form(...),
                 password2: str = Form(...),
                 db: Session = Depends(get_db)):
    if db.execute(select(User).limit(1)).scalar_one_or_none() is not None:
        return RedirectResponse(url="/login", status_code=302)
    username = (username or "").strip()
    errors = []
    if len(username) < 3:
        errors.append("Användarnamn måste vara minst 3 tecken.")
    if len(password or "") < 8:
        errors.append("Lösenord måste vara minst 8 tecken.")
    if password != password2:
        errors.append("Lösenorden matchar inte.")
    if errors:
        return RedirectResponse(url="/setup?error=" + "+".join(errors), status_code=302)

    pw_hash, salt = hash_password(password)
    user = User(username=username, password_hash=pw_hash, password_salt=salt)
    db.add(user)
    db.commit()
    audit.log(db, username, "create", "User", user.id, summary="Lokalt användarkonto skapat", commit=True)

    sess = create_session(db, user)
    resp = RedirectResponse(url="/dashboard", status_code=302)
    set_session_cookie(resp, sess.token)
    return resp


@router.get("/login")
def login_page(request: Request, next: str = "", error: str = "",
               db: Session = Depends(get_db)):
    sess = get_sess(request, db)
    if sess is not None:
        return RedirectResponse(url="/dashboard", status_code=302)
    has_user = db.execute(select(User).limit(1)).scalar_one_or_none() is not None
    if not has_user:
        return RedirectResponse(url="/setup", status_code=302)
    return templates(request).TemplateResponse(
        request, "login.html", tpl_context(request, db, sess, next=next,
                                  error="Fel användarnamn eller lösenord." if error else ""))


@router.post("/login")
def login_submit(request: Request,
                 username: str = Form(...),
                 password: str = Form(...),
                 next: str = Form(""),
                 db: Session = Depends(get_db)):
    client_ip = request.client.host if request.client else "local"
    check_login_throttle(client_ip)
    user = db.execute(select(User).where(User.username == (username or "").strip())).scalar_one_or_none()
    if user is None or not verify_password(password or "", user.password_hash, user.password_salt):
        record_failed_login(client_ip)
        return RedirectResponse(url="/login?error=1", status_code=302)

    user.last_login_at = datetime.now(timezone.utc)
    sess = create_session(db, user)
    audit.log(db, user.username, "login", "User", user.id, summary="Inloggning", commit=True)
    resp = RedirectResponse(url=(next or "/dashboard") if (next or "").startswith("/") else "/dashboard",
                            status_code=302)
    set_session_cookie(resp, sess.token)
    return resp


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    sess = get_sess(request, db)
    if sess is not None:
        audit.log(db, "", "logout", "User", sess.user_id, summary="Utloggning", commit=True)
    destroy_session(request, db)
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("firma_session")
    return resp
