"""Data management: backups, restore, full export, audit trail view."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, backup as backupmod, config
from ..db import get_db
from ..models import (
    AuditLog, CompanyProfile, Customer, Expense, IncomeEntry, Invoice,
    OwnerTransaction, SettingsKV, VatReport,
)
from ..security import get_session
from ..webutil import L, flash, parse_int, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/data", tags=["data"])


@router.get("")
def data_page(request: Request, db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    backups = backupmod.list_backups()
    db_size = config.DB_PATH.stat().st_size if config.DB_PATH.exists() else 0
    upload_size = sum(f.stat().st_size for f in config.UPLOAD_DIR.rglob("*") if f.is_file()) \
        if config.UPLOAD_DIR.exists() else 0
    return request.app.state.templates.TemplateResponse(request, "data.html", tpl_context(
        request, db, sess, backups=backups, db_size=db_size, upload_size=upload_size,
        db_path=str(config.DB_PATH),
    ))


@router.post("/backup")
def do_backup(request: Request, csrf: str = Form(""),
              db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/data", status_code=302)
    db.commit()  # flush everything before the snapshot
    try:
        path = backupmod.create_backup()
        audit.log(db, user.username, "backup", "System", None, summary=f"Backup skapad: {path.name}", commit=True)
        flash(db, sess, "success", L(request, "Backup skapad") + f": {path.name}")
    except Exception as exc:
        flash(db, sess, "error", L(request, "Backup misslyckades") + f": {exc}")
    db.commit()
    return RedirectResponse("/data", status_code=302)


@router.post("/restore")
def do_restore(request: Request, csrf: str = Form(""), name: str = Form(""),
               confirm: str = Form(""),
               db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/data", status_code=302)
    if confirm.strip().upper() != "ÅTERSTÄLL":
        flash(db, sess, "error", L(request, "Skriv exakt 'ÅTERSTÄLL' för att bekräfta.")); db.commit()
        return RedirectResponse("/data", status_code=302)
    audit.log(db, user.username, "restore", "System", None,
              summary=f"Återställning från {name}", commit=True)
    db.commit()
    try:
        safety = backupmod.restore_backup(name)
        flash(db, sess, "success",
              f"Återställd från '{name}'. Nuvarande data sparades i '{safety.name}'. "
              f"LADDA OM SIDAN (data har bytts ut under körning).")
    except Exception as exc:
        flash(db, sess, "error", L(request, "Återställning misslyckades") + f": {exc}")
    # Flash must survive: it's stored in the (now replaced) DB session row,
    # so also set a cookie-based hint.
    resp = RedirectResponse("/login", status_code=302)
    return resp


@router.get("/export.json")
def export_json(request: Request, db: Session = Depends(get_db), user=Depends(web_guard)):
    def enc(o):
        if isinstance(o, (Decimal,)):
            return str(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)

    def rows(model):
        out = []
        for obj in db.execute(select(model)).scalars().all():
            out.append({c.name: getattr(obj, c.name) for c in obj.__table__.columns})
        return out

    data = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "app": "Firmabok 1.0.0",
        "company_profile": rows(CompanyProfile),
        "customers": rows(Customer),
        "income_entries": rows(IncomeEntry),
        "expenses": rows(Expense),
        "invoices": rows(Invoice),
        "owner_transactions": rows(OwnerTransaction),
        "vat_reports": rows(VatReport),
        "settings": rows(SettingsKV),
    }
    content = json.dumps(data, ensure_ascii=False, indent=1, default=enc)
    return Response(content=content, media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="firmabok-export-{date.today():%Y%m%d}.json"'})


@router.get("/download.db")
def download_db(request: Request, db: Session = Depends(get_db), user=Depends(web_guard)):
    """Consistent point-in-time copy of the SQLite file (uses the online
    backup API so WAL contents are included)."""
    db.commit()
    tmp = Path(tempfile.mkdtemp(prefix="firmabok-")) / f"firmabok-{date.today():%Y%m%d}.db"
    src = sqlite3.connect(str(config.DB_PATH))
    dst = sqlite3.connect(str(tmp))
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    return FileResponse(tmp, filename=tmp.name, media_type="application/octet-stream")


@router.get("/audit")
def audit_page(request: Request, limit: str = "200", entity: str = "",
               db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    n = min(1000, max(10, parse_int(limit, 200)))
    stmt = select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc()).limit(n)
    if entity:
        stmt = stmt.where(AuditLog.entity_type == entity)
    entries = db.execute(stmt).scalars().all()
    entity_types = sorted({r[0] for r in db.execute(select(AuditLog.entity_type).distinct()).all()})
    return request.app.state.templates.TemplateResponse(request, "audit.html", tpl_context(
        request, db, sess, entries=entries, entity=entity, limit=n,
        entity_types=entity_types,
    ))
