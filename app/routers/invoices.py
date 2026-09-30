"""Invoice routes: drafts, gapless numbering, finalize, PDF, credit notes."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, vat as vatmod
from ..db import get_db
from ..invoices import (
    InvoiceError, create_credit_note, delete_draft, finalize_invoice,
    get_profile, mark_paid, peek_next_number, recalc_invoice,
)
from ..models import Customer, IncomeEntry, Invoice, InvoiceLine, InvoiceStatus
from ..money import ZERO, q2
from ..pdf import PdfError, invoice_pdf
from ..security import get_session
from ..webutil import L, flash, parse_bool, parse_date, parse_decimal, parse_int, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/fakturor", tags=["invoices"])

MAX_FORM_LINES = 40


def _customers(db: Session):
    return db.execute(select(Customer).order_by(Customer.name)).scalars().all()


@router.get("")
def list_invoices(request: Request, status: str = "", year: str = "",
                  db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    stmt = select(Invoice)
    if status in {s.value for s in InvoiceStatus}:
        stmt = stmt.where(Invoice.status == status)
    if year.isdigit():
        stmt = stmt.where(Invoice.series_year == int(year))
    invoices = db.execute(stmt.order_by(
        Invoice.invoice_date.desc().nullslast(), Invoice.id.desc())).scalars().all()
    next_number = peek_next_number(db, date.today().year)
    return request.app.state.templates.TemplateResponse(request, "invoice_list.html", tpl_context(
        request, db, sess, invoices=invoices, status=status, year=year,
        next_number=next_number, statuses=list(InvoiceStatus),
    ))


@router.get("/ny")
def new_form(request: Request, customer_id: str = "",
             db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    inv = Invoice(invoice_date=date.today(), payment_terms_days=profile.payment_terms_days,
                  notes=profile.invoice_notes, status=InvoiceStatus.DRAFT.value)
    if customer_id.isdigit():
        inv.customer_id = int(customer_id)
    return request.app.state.templates.TemplateResponse(request, "invoice_form.html", tpl_context(
        request, db, sess, invoice=inv, customers=_customers(db),
        sale_codes=list(vatmod.SALE_CODES.values()), profile=profile, is_new=True,
        blank_lines=3, next_number=peek_next_number(db, date.today().year),
    ))


def _parse_lines(descriptions, qtys, units, prices, codes, rates, arts=None):
    arts = arts or []
    lines = []
    n = max(len(descriptions), len(qtys), len(prices))
    for i in range(n):
        desc = (descriptions[i] if i < len(descriptions) else "").strip()
        art = (arts[i] if i < len(arts) else "").strip()
        qty = parse_decimal(qtys[i] if i < len(qtys) else "1", Decimal(1)) or Decimal(1)
        unit = (units[i] if i < len(units) else "st").strip() or "st"
        price = parse_decimal(prices[i] if i < len(prices) else "", None)
        code = (codes[i] if i < len(codes) else "SE25").strip() or "SE25"
        rate = parse_decimal(rates[i] if i < len(rates) else "", None)
        if not desc and price is None:
            continue  # empty row
        lines.append({"description": desc, "article_no": art, "quantity": qty, "unit": unit,
                      "unit_price": price if price is not None else ZERO,
                      "vat_code": code, "vat_rate": rate})
    return lines


@router.post("/ny")
def create(request: Request,
           csrf: str = Form(""),
           invoice_date: str = Form(...),
           delivery_date: str = Form(""),
           customer_id: str = Form(""),
           payment_terms_days: str = Form("30"),
           customer_reference: str = Form(""),
           our_reference: str = Form(""),
           notes: str = Form(""),
           finalize_now: str = Form(""),
           arts: list[str] = Form([]),
           descriptions: list[str] = Form([]),
           qtys: list[str] = Form([]),
           units: list[str] = Form([]),
           prices: list[str] = Form([]),
           codes: list[str] = Form([]),
           rates: list[str] = Form([]),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF-validering misslyckades.")); db.commit()
        return RedirectResponse("/fakturor/ny", status_code=302)

    profile = get_profile(db)
    d = parse_date(invoice_date) or date.today()
    errors = []
    if not customer_id.isdigit():
        errors.append(L(request, "Välj kund."))
    rows = _parse_lines(descriptions, qtys, units, prices, codes, rates, arts)
    if not rows:
        errors.append(L(request, "Lägg till minst en fakturarad med beskrivning och pris."))
    for r in rows:
        if r["vat_code"] not in vatmod.SALE_CODES:
            errors.append(L(request, "Okänd momskod på rad") + f": {r['vat_code']}")
            break
        if not r["description"]:
            errors.append(L(request, "Alla rader med pris måste ha en beskrivning."))
            break
    if errors:
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse("/fakturor/ny", status_code=302)

    inv = Invoice(status=InvoiceStatus.DRAFT.value, invoice_date=d,
                  delivery_date=parse_date(delivery_date) or d,
                  customer_id=int(customer_id),
                  payment_terms_days=max(0, parse_int(payment_terms_days, profile.payment_terms_days)),
                  customer_reference=customer_reference.strip(),
                  our_reference=our_reference.strip(),
                  notes=notes.strip() or profile.invoice_notes)
    db.add(inv)
    db.flush()
    for i, r in enumerate(rows):
        rate = r["vat_rate"]
        if rate is None:
            rate = vatmod.default_rate_for(r["vat_code"])
        db.add(InvoiceLine(invoice_id=inv.id, position=i, description=r["description"],
                           article_no=r["article_no"],
                           quantity=r["quantity"], unit=r["unit"], unit_price=q2(r["unit_price"]),
                           vat_code=r["vat_code"], vat_rate=q2(rate)))
    db.flush()
    recalc_invoice(inv, round_to_krona=bool(profile.round_total_to_krona))
    audit.log(db, user.username, "create", "Invoice", inv.id,
              summary=f"Faktura-utkast skapat, {inv.gross_total} kr inkl moms")
    db.commit()
    if parse_bool(finalize_now):
        try:
            finalize_invoice(db, inv, username=user.username, book_income=True)
            db.commit()
            flash(db, sess, "success",
                  L(request, "Faktura skapad och fastställd") + f": {inv.number}. "
                  + L(request, "Betalning kan registreras senare."))
        except InvoiceError as exc:
            db.rollback()
            flash(db, sess, "warning", f"{exc} " + L(request, "Fakturan sparades som utkast."))
            db.commit()
    else:
        flash(db, sess, "success", L(request, "Utkast skapat") + f". {L(request, 'Nästa lediga nummer')}: {peek_next_number(db, d.year)}.")
        db.commit()
    return RedirectResponse(f"/fakturor/{inv.id}", status_code=302)


@router.get("/{invoice_id}")
def detail(invoice_id: int, request: Request,
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        flash(db, sess, "error", L(request, "Fakturan finns inte.")); db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    profile = get_profile(db)
    from ..invoices import customer_snapshot, vat_breakdown
    snapshot = customer_snapshot(inv)
    linked_income = db.execute(select(IncomeEntry).where(IncomeEntry.invoice_id == inv.id)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "invoice_detail.html", tpl_context(
        request, db, sess, invoice=inv, profile=profile, customer=snapshot,
        breakdown=vat_breakdown(inv), linked_income=linked_income,
        customers=_customers(db), sale_codes=list(vatmod.SALE_CODES.values()),
        next_number=peek_next_number(db, (inv.invoice_date or date.today()).year),
        statuses=list(InvoiceStatus), today=date.today().isoformat(),
    ))


@router.post("/{invoice_id}/rader")
def update_lines(invoice_id: int, request: Request,
                 csrf: str = Form(""),
                 arts: list[str] = Form([]),
                 descriptions: list[str] = Form([]),
                 qtys: list[str] = Form([]),
                 units: list[str] = Form([]),
                 prices: list[str] = Form([]),
                 codes: list[str] = Form([]),
                 rates: list[str] = Form([]),
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    """Replace all lines of a DRAFT invoice (simple, consistent model)."""
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    if inv.status != InvoiceStatus.DRAFT.value:
        flash(db, sess, "error", L(request, "Endast utkast kan redigeras. För fastställda fakturor: använd kreditfaktura."))
        db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)

    rows = _parse_lines(descriptions, qtys, units, prices, codes, rates, arts)
    if not rows:
        flash(db, sess, "error", L(request, "Fakturan måste ha minst en rad.")); db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)
    before = audit.snapshot(inv)
    inv.lines.clear()
    db.flush()
    for i, r in enumerate(rows):
        rate = r["vat_rate"] if r["vat_rate"] is not None else vatmod.default_rate_for(r["vat_code"])
        inv.lines.append(InvoiceLine(position=i, description=r["description"],
                                     article_no=r["article_no"],
                                     quantity=r["quantity"], unit=r["unit"],
                                     unit_price=q2(r["unit_price"]),
                                     vat_code=r["vat_code"], vat_rate=q2(rate)))
    db.flush()
    recalc_invoice(inv, round_to_krona=bool(get_profile(db).round_total_to_krona))
    audit.log(db, user.username, "update", "Invoice", inv.id, summary="Rader uppdaterade (utkast)",
              changes=audit.diff(before, inv))
    db.commit()
    flash(db, sess, "success", L(request, "Rader sparade.")); db.commit()
    return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/metadata")
def update_meta(invoice_id: int, request: Request,
                csrf: str = Form(""),
                invoice_date: str = Form(...),
                delivery_date: str = Form(""),
                customer_id: str = Form(""),
                payment_terms_days: str = Form("30"),
                customer_reference: str = Form(""),
                our_reference: str = Form(""),
                notes: str = Form(""),
                db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    if inv.status != InvoiceStatus.DRAFT.value:
        flash(db, sess, "error", L(request, "Endast utkast kan redigeras.")); db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)
    before = audit.snapshot(inv)
    inv.invoice_date = parse_date(invoice_date) or inv.invoice_date
    dd = parse_date(delivery_date)
    if dd:
        inv.delivery_date = dd
    if customer_id.isdigit():
        inv.customer_id = int(customer_id)
    inv.payment_terms_days = max(0, parse_int(payment_terms_days, inv.payment_terms_days))
    inv.customer_reference = customer_reference.strip()
    inv.our_reference = our_reference.strip()
    inv.notes = notes.strip()
    audit.log(db, user.username, "update", "Invoice", inv.id, summary="Metadata uppdaterad (utkast)",
              changes=audit.diff(before, inv))
    db.commit()
    flash(db, sess, "success", L(request, "Sparat.")); db.commit()
    return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/faststall")
def finalize(invoice_id: int, request: Request, csrf: str = Form(""),
             book_income: str = Form(""),
             db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    try:
        finalize_invoice(db, inv, username=user.username, book_income=parse_bool(book_income))
        db.commit()
        flash(db, sess, "success",
              f"Faktura {inv.number} fastställd. Förfallodatum {inv.due_date}. "
              f"{'Intäkten bokfördes automatiskt.' if parse_bool(book_income) else 'OBS: intäkt bokfördes ej — lägg in den manuellt under Intäkter.'}")
    except InvoiceError as exc:
        db.rollback()
        flash(db, sess, "error", str(exc))
    db.commit()
    return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/skicka")
def mark_sent(invoice_id: int, request: Request, csrf: str = Form(""),
              db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv and check_csrf(sess, csrf) and inv.status == InvoiceStatus.FINALIZED.value:
        inv.status = InvoiceStatus.SENT.value
        audit.log(db, user.username, "update", "Invoice", inv.id, summary=f"Faktura {inv.number} markerad som skickad")
        db.commit()
        flash(db, sess, "success", L(request, "Markerad som skickad."))
    db.commit()
    return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/betalning")
def register_payment(invoice_id: int, request: Request, csrf: str = Form(""),
                     amount: str = Form(""), payment_date: str = Form(""),
                     db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    if inv.status not in (InvoiceStatus.FINALIZED.value, InvoiceStatus.SENT.value, InvoiceStatus.PAID.value):
        flash(db, sess, "error", L(request, "Betalning kan bara registreras på fastställda fakturor.")); db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)
    amt = parse_decimal(amount, inv.amount_to_pay)
    mark_paid(db, inv, amt, parse_date(payment_date) or date.today())
    audit.log(db, user.username, "update", "Invoice", inv.id,
              summary=f"Betalning {amt} kr registrerad på {inv.number} (status: {inv.status})")
    db.commit()
    flash(db, sess, "success", L(request, "Betalning registrerad") + f": {amt} kr."); db.commit()
    return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/kreditera")
def credit(invoice_id: int, request: Request, csrf: str = Form(""), reason: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    try:
        credit_inv = create_credit_note(db, inv, username=user.username, reason=reason)
        db.commit()
        flash(db, sess, "success", f"Kreditfaktura-utkast skapat (id {credit_inv.id}). Granska och fastställ.")
        return RedirectResponse(f"/fakturor/{credit_inv.id}", status_code=302)
    except InvoiceError as exc:
        db.rollback()
        flash(db, sess, "error", str(exc)); db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)


@router.post("/{invoice_id}/radera")
def delete(invoice_id: int, request: Request, csrf: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None or not check_csrf(sess, csrf):
        db.commit()
        return RedirectResponse("/fakturor", status_code=302)
    try:
        for e in db.execute(select(IncomeEntry).where(IncomeEntry.invoice_id == inv.id)).scalars():
            e.invoice_id = None
        delete_draft(db, inv)
        audit.log(db, user.username, "delete", "Invoice", invoice_id, summary="Utkast raderat")
        db.commit()
        flash(db, sess, "success", L(request, "Utkast raderat (nummerserien opåverkad)."))
    except InvoiceError as exc:
        db.rollback()
        flash(db, sess, "error", str(exc))
    db.commit()
    return RedirectResponse("/fakturor", status_code=302)


@router.get("/{invoice_id}/pdf")
def download_pdf(invoice_id: int, request: Request,
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        return RedirectResponse("/fakturor", status_code=302)
    try:
        pdf = invoice_pdf(db, inv)
    except PdfError as exc:
        flash(db, sess, "error", str(exc)); db.commit()
        return RedirectResponse(f"/fakturor/{invoice_id}", status_code=302)
    fname = f"{'kreditfaktura' if inv.is_credit_note else 'faktura'}_{inv.number or 'utkast'}.pdf"
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
