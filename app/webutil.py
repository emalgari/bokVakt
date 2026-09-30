"""Shared web helpers: template context, flash messages, form parsing."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from fastapi import Request
from sqlalchemy.orm import Session

from . import i18n
from .invoices import get_profile
from .models import UserSession
from .money import to_decimal


# ---------------------------------------------------------------------------
# Flash messages (stored server-side on the session row)
# ---------------------------------------------------------------------------

def flash(db: Session, sess: UserSession | None, category: str, message: str) -> None:
    if sess is None:
        return
    try:
        items = json.loads(sess.flash or "[]")
    except json.JSONDecodeError:
        items = []
    items.append({"category": category, "message": message})
    sess.flash = json.dumps(items, ensure_ascii=False)
    db.commit()


def pop_flashes(sess: UserSession | None) -> list[dict]:
    if sess is None:
        return []
    try:
        items = json.loads(sess.flash or "[]")
    except json.JSONDecodeError:
        items = []
    if items:
        sess.flash = "[]"
    return items


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------

def L(request: Request, text: str) -> str:
    """Translate a string (flash messages etc.) using the request language."""
    return i18n.translate(i18n.lang_from_request(request), text)


def tpl_context(request: Request, db: Session, sess: UserSession | None, **extra) -> dict:
    profile = get_profile(db)
    lang = i18n.lang_from_request(request)
    ctx = {
        "request": request,
        "lang": lang,
        "_": lambda text: i18n.translate(lang, text),
        "month_name": lambda m: i18n.month_name(lang, int(m)),
        "company": profile,
        "csrf_token": sess.csrf_token if sess else "",
        "username": sess.user_id if sess else None,
        "flashes": pop_flashes(sess),
        "simplified_mode": bool(profile.simplified_vat_mode),
        "app_version": __import__("app").__version__ if hasattr(__import__("app"), "__version__") else "1.0.0",
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# Form parsing (Swedish-friendly)
# ---------------------------------------------------------------------------

_NUM_CLEAN = re.compile(r"[^\d,.\-]")


def parse_decimal(value: str | None, default: Decimal | None = None) -> Decimal | None:
    """Parse a Swedish-formatted decimal ('1 234,50 kr', '1234.50', '−5')."""
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    s = s.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    s = s.replace("\u2212", "-").replace("−", "-")
    s = _NUM_CLEAN.sub("", s)
    if not s or s in ("-",):
        return default
    if "," in s and "." in s:
        # assume last separator is the decimal one
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return to_decimal(s)
    except (InvalidOperation, ValueError):
        return default


def parse_date(value: str | None):
    from datetime import date as _date, datetime as _dt
    if not value:
        return None
    v = value.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return _dt.strptime(v, fmt).date()
        except ValueError:
            continue
    try:
        return _date.fromisoformat(v)
    except ValueError:
        return None


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip() or default)
    except (TypeError, ValueError):
        return default


def parse_bool(value) -> bool:
    return str(value).lower() in ("1", "true", "on", "yes", "ja")
