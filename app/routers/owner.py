"""Owner finances: egna uttag / egna insättningar.

IMPORTANT: owner withdrawals and contributions are private transactions
between the owner and the business. They are NOT business expenses or
income, do not affect profit, and have no VAT consequences. This module
keeps them strictly separated.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..invoices import get_profile
from ..models import OwnerTransaction, OwnerTxType
from ..money import q2, sum_money
from ..security import get_session
from ..swedish import fiscal_year_bounds, fiscal_year_of
from ..webutil import L, flash, parse_date, parse_decimal, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/agare", tags=["owner"])


@router.get("")
def owner_page(request: Request, year: str = "",
               db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    today = date.today()
    fy = int(year) if year.isdigit() else fiscal_year_of(today, profile.fiscal_year_start_month)
    start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
    txs = db.execute(
        select(OwnerTransaction)
        .where(OwnerTransaction.tx_date >= start, OwnerTransaction.tx_date <= end)
        .order_by(OwnerTransaction.tx_date.desc(), OwnerTransaction.id.desc())
    ).scalars().all()
    uttag = sum_money(t.amount for t in txs if t.tx_type == OwnerTxType.UTTAG.value)
    insatt = sum_money(t.amount for t in txs if t.tx_type == OwnerTxType.INSATTNING.value)
    return request.app.state.templates.TemplateResponse(request, "owner.html", tpl_context(
        request, db, sess, txs=txs, fy=fy, uttag=uttag, insattning=insatt,
        years=[fy - 1, fy, fy + 1], today=today,
    ))


@router.post("/ny")
def create(request: Request, csrf: str = Form(""),
           tx_date: str = Form(...), tx_type: str = Form("uttag"),
           amount: str = Form(...), description: str = Form(""), reference: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/agare", status_code=302)
    d = parse_date(tx_date)
    amt = parse_decimal(amount)
    errors = []
    if d is None:
        errors.append(L(request, "Ogiltigt datum."))
    if amt is None or amt <= 0:
        errors.append(L(request, "Ange ett positivt belopp."))
    if tx_type not in {t.value for t in OwnerTxType}:
        errors.append(L(request, "Ogiltig typ."))
    if errors:
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse("/agare", status_code=302)
    tx = OwnerTransaction(tx_date=d, tx_type=tx_type, amount=q2(amt),
                          description=(description or "").strip(),
                          reference=(reference or "").strip())
    db.add(tx)
    db.flush()
    label = L(request, "Eget uttag") if tx_type == OwnerTxType.UTTAG.value else L(request, "Egen insättning")
    audit.log(db, user.username, "create", "OwnerTransaction", tx.id,
              summary=f"{label} {amt} kr {d}")
    db.commit()
    flash(db, sess, "success", f"{label} {amt} kr — " + L(request, "sparad. (Påverkar varken resultat eller moms.)"))
    db.commit()
    return RedirectResponse("/agare", status_code=302)


@router.post("/{tx_id}/radera")
def delete(tx_id: int, request: Request, csrf: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    tx = db.get(OwnerTransaction, tx_id)
    if tx and check_csrf(sess, csrf):
        audit.log(db, user.username, "delete", "OwnerTransaction", tx.id,
                  summary=f"Ägartransaktion raderad: {tx.tx_type} {tx.amount} kr",
                  changes={"row": audit.snapshot(tx)})
        db.delete(tx)
        db.commit()
        flash(db, sess, "success", L(request, "Raderad."))
    db.commit()
    return RedirectResponse("/agare", status_code=302)
