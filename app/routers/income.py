"""Income (intäkter) routes."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, vat as vatmod
from ..db import get_db
from ..invoices import get_profile, recalc_invoice
from ..models import (
    Customer, IncomeEntry, Invoice, InvoiceLine, InvoiceStatus, PaymentStatus,
)
from ..money import ZERO, net_from_gross, q2, sum_money, vat_amount
from ..security import get_session
from ..swedish import fiscal_year_of
from ..webutil import L, flash, parse_date, parse_decimal, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/intakter", tags=["income"])


def _sale_codes():
    return list(vatmod.SALE_CODES.values())


def _amounts(mode: str, amount: Decimal, rate: Decimal, code: str):
    """Compute (net, vat, gross) from either a net or gross input amount."""
    info = vatmod.get_code(code)
    if info.side == "sale" and not info.domestic_sale_vat:
        rate = ZERO  # exempt / EU / reverse-charge sales carry no Swedish VAT
    if mode == "gross":
        net = net_from_gross(amount, rate)
        vat = q2(amount - net)
        gross = q2(amount)
    else:
        net = q2(amount)
        vat = vat_amount(net, rate)
        gross = q2(net + vat)
    return net, vat, gross, rate


def _base_query(request: Request):
    return {k: v for k, v in request.query_params.items()}


@router.get("")
def list_income(request: Request,
                year: str = "", month: str = "", q: str = "", status: str = "",
                db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    today = date.today()
    fy = int(year) if year.isdigit() else fiscal_year_of(today, profile.fiscal_year_start_month)
    from ..swedish import fiscal_year_bounds
    start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
    stmt = select(IncomeEntry).where(IncomeEntry.entry_date >= start, IncomeEntry.entry_date <= end)
    if month.isdigit() and 1 <= int(month) <= 12:
        from sqlalchemy import extract
        stmt = stmt.where(extract("month", IncomeEntry.entry_date) == int(month))
    if status in ("unpaid", "paid", "partial"):
        stmt = stmt.where(IncomeEntry.payment_status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            IncomeEntry.description.ilike(like)
            | IncomeEntry.customer_name.ilike(like)
            | IncomeEntry.invoice_ref.ilike(like))
    entries = db.execute(stmt.order_by(IncomeEntry.entry_date.desc(), IncomeEntry.id.desc())).scalars().all()

    totals = {
        "net": sum_money(e.net_amount for e in entries),
        "vat": sum_money(e.vat_amount for e in entries),
        "gross": sum_money(e.gross_amount for e in entries),
        "count": len(entries),
    }
    customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "income_list.html", tpl_context(
        request, db, sess, entries=entries, totals=totals, fy=fy, month=month,
        q=q, status=status, customers=customers, sale_codes=_sale_codes(),
        today=today, profile=profile,
    ))


@router.get("/ny")
def new_form(request: Request, customer_id: str = "", d: str = "",
             db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    entry = IncomeEntry(entry_date=parse_date(d) or date.today(),
                        vat_rate=profile.default_vat_rate)
    if customer_id.isdigit():
        entry.customer_id = int(customer_id)
    return request.app.state.templates.TemplateResponse(request, "income_form.html", tpl_context(
        request, db, sess, entry=entry, customers=customers,
        sale_codes=_sale_codes(), profile=profile, mode="net", is_new=True,
    ))


@router.post("/ny")
def create(request: Request,
           csrf: str = Form(""),
           entry_date: str = Form(...),
           customer_id: str = Form(""),
           customer_name: str = Form(""),
           description: str = Form(""),
           vat_code: str = Form("SE25"),
           amount_mode: str = Form("net"),
           amount: str = Form(...),
           vat_rate: str = Form(""),
           payment_status: str = Form("unpaid"),
           payment_date: str = Form(""),
           invoice_ref: str = Form(""),
           notes: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF-validering misslyckades.")); db.commit()
        return RedirectResponse("/intakter/ny", status_code=302)

    d = parse_date(entry_date)
    amt = parse_decimal(amount)
    errors = []
    if d is None:
        errors.append(L(request, "Ogiltigt datum."))
    if amt is None or amt == 0:
        errors.append(L(request, "Ogiltigt belopp."))
    if vat_code not in vatmod.SALE_CODES:
        errors.append(L(request, "Okänd momskod."))
    if not customer_name.strip() and not customer_id.isdigit():
        errors.append(L(request, "Ange kund (välj ur listan eller skriv namn)."))
    if payment_status not in {p.value for p in PaymentStatus}:
        payment_status = "unpaid"
    if errors:
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse("/intakter/ny", status_code=302)

    rate = parse_decimal(vat_rate, vatmod.default_rate_for(vat_code)) or vatmod.default_rate_for(vat_code)
    net, vat, gross, rate = _amounts(amount_mode, amt, rate, vat_code)

    cust = db.get(Customer, int(customer_id)) if customer_id.isdigit() else None
    entry = IncomeEntry(
        entry_date=d,
        customer_id=cust.id if cust else None,
        customer_name=(cust.name if cust else customer_name).strip(),
        description=description.strip(),
        vat_code=vat_code,
        net_amount=net, vat_rate=rate, vat_amount=vat, gross_amount=gross,
        payment_status=payment_status,
        payment_date=parse_date(payment_date) if payment_status == "paid" else None,
        invoice_ref=invoice_ref.strip(),
        notes=notes.strip(),
    )
    db.add(entry)
    db.flush()
    audit.log(db, user.username, "create", "IncomeEntry", entry.id,
              summary=f"Intäkt {entry.entry_date} {net} kr exkl moms ({vat_code})")
    db.commit()
    flash(db, sess, "success", L(request, "Intäkt sparad") + f": {net} kr {L(request, 'exkl. moms')}, {L(request, 'Moms').lower()} {vat} kr.")
    db.commit()
    return RedirectResponse("/intakter", status_code=302)


@router.get("/{entry_id}/redigera")
def edit_form(entry_id: int, request: Request,
              db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    entry = db.get(IncomeEntry, entry_id)
    if entry is None:
        flash(db, sess, "error", L(request, "Intäkten finns inte.")); db.commit()
        return RedirectResponse("/intakter", status_code=302)
    customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "income_form.html", tpl_context(
        request, db, sess, entry=entry, customers=customers,
        sale_codes=_sale_codes(), profile=get_profile(db), mode="net", is_new=False,
    ))


@router.post("/{entry_id}/redigera")
def update(entry_id: int, request: Request,
           csrf: str = Form(""),
           entry_date: str = Form(...),
           customer_id: str = Form(""),
           customer_name: str = Form(""),
           description: str = Form(""),
           vat_code: str = Form("SE25"),
           amount_mode: str = Form("net"),
           amount: str = Form(...),
           vat_rate: str = Form(""),
           payment_status: str = Form("unpaid"),
           payment_date: str = Form(""),
           invoice_ref: str = Form(""),
           notes: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    entry = db.get(IncomeEntry, entry_id)
    if entry is None or not check_csrf(sess, csrf):
        flash(db, sess, "error", "Kunde inte spara (finns ej eller CSRF)."); db.commit()
        return RedirectResponse("/intakter", status_code=302)
    if entry.invoice_id is not None:
        flash(db, sess, "error",
              L(request, "Intäkten är länkad till en faktura och bör ändras via fakturan/kreditfaktura. Ta bort länken först om du verkligen vill ändra här.")); db.commit()
        return RedirectResponse("/intakter", status_code=302)

    before = audit.snapshot(entry)
    d = parse_date(entry_date) or entry.entry_date
    amt = parse_decimal(amount, entry.net_amount) or ZERO
    rate = parse_decimal(vat_rate, entry.vat_rate)
    if rate is None:
        rate = vatmod.default_rate_for(vat_code)
    net, vat, gross, rate = _amounts(amount_mode, amt, rate, vat_code)
    cust = db.get(Customer, int(customer_id)) if customer_id.isdigit() else None

    entry.entry_date = d
    entry.customer_id = cust.id if cust else (entry.customer_id if not customer_id else None)
    entry.customer_name = (cust.name if cust else customer_name).strip() or entry.customer_name
    entry.description = description.strip()
    entry.vat_code = vat_code
    entry.net_amount, entry.vat_rate, entry.vat_amount, entry.gross_amount = net, rate, vat, gross
    entry.payment_status = payment_status
    entry.payment_date = parse_date(payment_date) if payment_status == "paid" else None
    entry.invoice_ref = invoice_ref.strip()
    entry.notes = notes.strip()

    changes = audit.diff(before, entry)
    if changes:
        audit.log(db, user.username, "update", "IncomeEntry", entry.id,
                  summary="Intäkt ändrad", changes=changes)
    db.commit()
    flash(db, sess, "success", L(request, "Intäkt uppdaterad.")); db.commit()
    return RedirectResponse("/intakter", status_code=302)


@router.post("/{entry_id}/betald")
def mark_paid(entry_id: int, request: Request, csrf: str = Form(""),
              payment_date: str = Form(""),
              db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    entry = db.get(IncomeEntry, entry_id)
    if entry and check_csrf(sess, csrf):
        before = audit.snapshot(entry)
        entry.payment_status = PaymentStatus.PAID.value
        entry.payment_date = parse_date(payment_date) or date.today()
        audit.log(db, user.username, "update", "IncomeEntry", entry.id,
                  summary="Markerad som betald", changes=audit.diff(before, entry))
        db.commit()
        flash(db, sess, "success", L(request, "Markerad som betald."))
    db.commit()
    return RedirectResponse(request.headers.get("referer", "/intakter"), status_code=302)


@router.post("/{entry_id}/radera")
def delete(entry_id: int, request: Request, csrf: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    entry = db.get(IncomeEntry, entry_id)
    if entry is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/intakter", status_code=302)
    if entry.invoice_id is not None:
        flash(db, sess, "error", L(request, "Intäkten är länkad till faktura och kan inte raderas. Kreditera fakturan i stället."))
        db.commit()
        return RedirectResponse("/intakter", status_code=302)
    audit.log(db, user.username, "delete", "IncomeEntry", entry.id,
              summary=f"Intäkt raderad: {entry.net_amount} kr exkl moms ({entry.entry_date})",
              changes={"row": audit.snapshot(entry)})
    db.delete(entry)
    db.commit()
    flash(db, sess, "success", L(request, "Intäkt raderad.")); db.commit()
    return RedirectResponse("/intakter", status_code=302)


@router.post("/{entry_id}/skapa-faktura")
def create_invoice_from_income(entry_id: int, request: Request, csrf: str = Form(""),
                               db: Session = Depends(get_db), user=Depends(web_guard)):
    """Create a draft invoice from an income entry (recommended flow so the
    sale is counted exactly once in VAT reports)."""
    sess = get_session(request, db)
    entry = db.get(IncomeEntry, entry_id)
    if entry is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/intakter", status_code=302)
    if entry.invoice_id is not None:
        flash(db, sess, "error", L(request, "Intäkten har redan en faktura."))
        db.commit()
        return RedirectResponse("/intakter", status_code=302)
    if entry.customer_id is None:
        flash(db, sess, "error", L(request, "Välj en registrerad kund på intäkten innan faktura skapas (engångskunder: lägg upp dem under Kunder)."))
        db.commit()
        return RedirectResponse("/intakter", status_code=302)

    profile = get_profile(db)
    inv = Invoice(
        status=InvoiceStatus.DRAFT.value,
        invoice_date=date.today(),
        payment_terms_days=profile.payment_terms_days,
        customer_id=entry.customer_id,
        customer_reference="",
        notes=profile.invoice_notes,
    )
    db.add(inv)
    db.flush()
    unit_price = q2(entry.net_amount)
    db.add(InvoiceLine(
        invoice_id=inv.id, position=0,
        description=entry.description or "Fakturerat arbete",
        quantity=Decimal(1), unit="st", unit_price=unit_price,
        vat_code=entry.vat_code, vat_rate=entry.vat_rate,
    ))
    db.flush()
    recalc_invoice(inv)
    entry.invoice_id = inv.id
    entry.invoice_ref = inv.number or ""
    audit.log(db, user.username, "create", "Invoice", inv.id,
              summary=f"Faktura-utkast skapat från intäkt #{entry.id}")
    db.commit()
    flash(db, sess, "success", L(request, "Fakturautkast skapat (rad motsvarar beloppet exkl moms). Kontrollera rader, antal och pris innan fastställning.").replace("beloppet", f"{unit_price} kr"))
    db.commit()
    return RedirectResponse(f"/fakturor/{inv.id}", status_code=302)
