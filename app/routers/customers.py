"""Customer (kunder) routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Customer, IncomeEntry, Invoice
from ..security import get_session
from ..swedish import normalize_org_nr, normalize_vat_number
from ..webutil import L, flash, parse_bool, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/kunder", tags=["customers"])


def _fill(c: Customer, form: dict, warnings: list) -> None:
    c.name = (form.get("name") or "").strip()
    c.is_business = parse_bool(form.get("is_business"))
    c.customer_no = (form.get("customer_no") or "").strip()
    org = (form.get("org_nr") or "").strip()
    if org:
        try:
            if c.is_business and len([ch for ch in org if ch.isdigit()]) == 10:
                c.org_nr = normalize_org_nr(org)
            else:
                c.org_nr = org  # personnr or foreign id kept as typed
        except ValueError as exc:
            warnings.append(str(exc))
            c.org_nr = org
    else:
        c.org_nr = ""
    vatn = (form.get("vat_number") or "").strip()
    if vatn:
        try:
            c.vat_number = normalize_vat_number(vatn)
        except ValueError as exc:
            warnings.append(str(exc))
            c.vat_number = vatn.upper()
    else:
        c.vat_number = ""
    for field_ in ("address_line1", "address_line2", "postal_code", "city", "email", "phone", "reference", "notes"):
        setattr(c, field_, (form.get(field_) or "").strip())
    c.country = (form.get("country") or "Sverige").strip() or "Sverige"


@router.get("")
def list_customers(request: Request, db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    customers = db.execute(select(Customer).order_by(Customer.name)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "customers.html", tpl_context(
        request, db, sess, customers=customers, edit_id=0))


@router.post("/ny")
def create(request: Request, csrf: str = Form(""),
           name: str = Form(...), customer_no: str = Form(""), is_business: str = Form(""),
           org_nr: str = Form(""), vat_number: str = Form(""),
           address_line1: str = Form(""), address_line2: str = Form(""),
           postal_code: str = Form(""), city: str = Form(""), country: str = Form("Sverige"),
           email: str = Form(""), phone: str = Form(""), reference: str = Form(""), notes: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/kunder", status_code=302)
    if not (name or "").strip():
        flash(db, sess, "error", L(request, "Namn krävs.")); db.commit()
        return RedirectResponse("/kunder", status_code=302)
    form = dict(name=name, customer_no=customer_no, is_business=is_business, org_nr=org_nr,
                vat_number=vat_number, address_line1=address_line1, address_line2=address_line2,
                postal_code=postal_code, city=city, country=country, email=email, phone=phone,
                reference=reference, notes=notes)
    c = Customer()
    warnings: list[str] = []
    _fill(c, form, warnings)
    db.add(c)
    db.flush()
    audit.log(db, user.username, "create", "Customer", c.id, summary=f"Kund skapad: {c.name}")
    db.commit()
    msg = L(request, "Kund sparad") + f": {c.name}."
    if warnings:
        msg += " " + L(request, "Varningar:") + " " + " ".join(warnings)
    flash(db, sess, "warning" if warnings else "success", msg); db.commit()
    return RedirectResponse("/kunder", status_code=302)


@router.post("/{customer_id}/redigera")
def update(customer_id: int, request: Request, csrf: str = Form(""),
           name: str = Form(...), customer_no: str = Form(""), is_business: str = Form(""),
           org_nr: str = Form(""), vat_number: str = Form(""),
           address_line1: str = Form(""), address_line2: str = Form(""),
           postal_code: str = Form(""), city: str = Form(""), country: str = Form("Sverige"),
           email: str = Form(""), phone: str = Form(""), reference: str = Form(""), notes: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    c = db.get(Customer, customer_id)
    if c is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/kunder", status_code=302)
    before = audit.snapshot(c)
    form = dict(name=name, customer_no=customer_no, is_business=is_business, org_nr=org_nr,
                vat_number=vat_number, address_line1=address_line1, address_line2=address_line2,
                postal_code=postal_code, city=city, country=country, email=email, phone=phone,
                reference=reference, notes=notes)
    warnings: list[str] = []
    _fill(c, form, warnings)
    changes = audit.diff(before, c)
    if changes:
        audit.log(db, user.username, "update", "Customer", c.id, summary=f"Kund ändrad: {c.name}", changes=changes)
    db.commit()
    msg = L(request, "Kund uppdaterad.")
    if warnings:
        msg += " " + L(request, "Varningar:") + " " + " ".join(warnings)
    flash(db, sess, "warning" if warnings else "success", msg); db.commit()
    return RedirectResponse("/kunder", status_code=302)


@router.post("/{customer_id}/radera")
def delete(customer_id: int, request: Request, csrf: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    c = db.get(Customer, customer_id)
    if c is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/kunder", status_code=302)
    has_invoices = db.execute(select(Invoice.id).where(Invoice.customer_id == c.id).limit(1)).first()
    has_income = db.execute(select(IncomeEntry.id).where(IncomeEntry.customer_id == c.id).limit(1)).first()
    if has_invoices or has_income:
        flash(db, sess, "error",
              L(request, "Kunden har fakturor/intäkter och kan inte raderas (bokföringshistorik ska bevaras)."))
        db.commit()
        return RedirectResponse("/kunder", status_code=302)
    audit.log(db, user.username, "delete", "Customer", c.id, summary=f"Kund raderad: {c.name}",
              changes={"row": audit.snapshot(c)})
    db.delete(c)
    db.commit()
    flash(db, sess, "success", L(request, "Kund raderad.")); db.commit()
    return RedirectResponse("/kunder", status_code=302)
