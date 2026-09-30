"""Expense (utgifter) routes, including receipt attachments."""
from __future__ import annotations

import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from .. import audit, config, vat as vatmod
from ..db import get_db
from ..invoices import get_profile
from ..models import Expense, ExpenseCategory
from ..money import ZERO, net_from_gross, q2, sum_money, vat_amount
from ..security import get_session
from ..swedish import fiscal_year_of
from ..webutil import L, flash, parse_date, parse_decimal, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/utgifter", tags=["expenses"])


def _purchase_codes():
    return list(vatmod.PURCHASE_CODES.values())


def _amounts(mode: str, amount: Decimal, rate: Decimal, code: str):
    """Compute (net, vat, gross). 'gross' mode: the entered amount includes
    VAT (typical for receipts/kvitton); 'net' mode: entered amount is exkl."""
    if mode == "gross":
        gross = q2(amount)
        net = net_from_gross(gross, rate)
        vat = q2(gross - net)
    else:
        net = q2(amount)
        vat = vat_amount(net, rate)
        gross = q2(net + vat)
    return net, vat, gross


@router.get("")
def list_expenses(request: Request,
                  year: str = "", month: str = "", category: str = "", q: str = "",
                  db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    today = date.today()
    fy = int(year) if year.isdigit() else fiscal_year_of(today, profile.fiscal_year_start_month)
    from ..swedish import fiscal_year_bounds
    start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
    stmt = select(Expense).where(Expense.expense_date >= start, Expense.expense_date <= end)
    if month.isdigit() and 1 <= int(month) <= 12:
        stmt = stmt.where(extract("month", Expense.expense_date) == int(month))
    if category:
        stmt = stmt.where(Expense.category_name == category)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Expense.supplier.ilike(like) | Expense.description.ilike(like))
    expenses = db.execute(stmt.order_by(Expense.expense_date.desc(), Expense.id.desc())).scalars().all()

    totals = {
        "gross": sum_money(e.gross_amount for e in expenses),
        "net": sum_money(e.net_amount for e in expenses),
        "vat": sum_money(e.vat_amount for e in expenses),
        "deductible": sum_money(min(e.deductible_vat or ZERO, e.vat_amount or ZERO) for e in expenses),
        "cost": sum_money(e.book_cost for e in expenses),
        "count": len(expenses),
    }
    categories = db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "expense_list.html", tpl_context(
        request, db, sess, expenses=expenses, totals=totals, fy=fy, month=month,
        category=category, q=q, categories=categories, purchase_codes=_purchase_codes(),
        today=today,
    ))


@router.get("/ny")
def new_form(request: Request, d: str = "",
             db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    categories = db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name)).scalars().all()
    exp = Expense(expense_date=parse_date(d) or date.today(), vat_rate=Decimal("25"))
    return request.app.state.templates.TemplateResponse(request, "expense_form.html", tpl_context(
        request, db, sess, expense=exp, categories=categories,
        purchase_codes=_purchase_codes(), profile=profile, mode="gross", is_new=True,
    ))


def _validate_and_fill(exp: Expense, form: dict, file: UploadFile | None, errors: list,
                       db: Session, user, existing_receipt: tuple[str, str] | None = None) -> None:
    d = parse_date(form.get("expense_date"))
    if d is None:
        errors.append(L(request, "Ogiltigt datum."))
        exp.expense_date = exp.expense_date or date.today()
    else:
        exp.expense_date = d

    code = form.get("vat_code", "SE25_P")
    if code not in vatmod.PURCHASE_CODES:
        errors.append(L(request, "Okänd momskod."))
        code = "SE25_P"
    exp.vat_code = code
    rate = parse_decimal(form.get("vat_rate"), vatmod.default_rate_for(code))
    if rate is None:
        rate = vatmod.default_rate_for(code)
    if rate not in (Decimal("0"), Decimal("6"), Decimal("12"), Decimal("25")):
        errors.append(L(request, "Momssats X% är inte en giltig svensk sats (0/6/12/25).").replace("X%", f"{rate}%"))
    exp.vat_rate = rate

    mode = form.get("amount_mode", "gross")
    amt = parse_decimal(form.get("amount"))
    if amt is None or amt <= 0:
        errors.append(L(request, "Ogiltigt belopp (ange positivt belopp)."))
        amt = Decimal("0.00")
    net, vat, gross = _amounts(mode, amt, rate, code)
    exp.net_amount, exp.vat_amount, exp.gross_amount = net, vat, gross

    deductible = parse_decimal(form.get("deductible_vat"), vat)
    if deductible is None:
        deductible = vat
    if code == "NON_DEDUCTIBLE_P":
        deductible = ZERO
    deductible = max(ZERO, min(deductible, vat))
    exp.deductible_vat = q2(deductible)

    exp.supplier = (form.get("supplier") or "").strip()
    exp.description = (form.get("description") or "").strip()
    exp.payment_method = (form.get("payment_method") or "").strip()
    exp.notes = (form.get("notes") or "").strip()

    cat_id = form.get("category_id") or ""
    cat_name = (form.get("category_name_new") or "").strip()
    if cat_id.isdigit():
        cat = db.get(ExpenseCategory, int(cat_id))
        if cat:
            exp.category_id = cat.id
            exp.category_name = cat.name
    elif cat_name:
        cat = db.execute(select(ExpenseCategory).where(ExpenseCategory.name == cat_name)).scalar_one_or_none()
        if cat is None:
            cat = ExpenseCategory(name=cat_name)
            db.add(cat)
            db.flush()
            audit.log(db, user.username, "create", "ExpenseCategory", cat.id, summary=f"Ny kategori: {cat_name}")
        exp.category_id = cat.id
        exp.category_name = cat.name
    else:
        exp.category_id = None
        exp.category_name = "Övrigt"

    # Receipt
    if file is not None and file.filename:
        ctype = (file.content_type or "").lower()
        if ctype not in config.ALLOWED_RECEIPT_TYPES:
            errors.append(L(request, "Kvitto måste vara bild (jpg/png/webp/heic) eller PDF."))
        else:
            data = file.file.read()
            if len(data) > config.MAX_UPLOAD_BYTES:
                errors.append(L(request, "Kvittot är större än 10 MB."))
            else:
                subdir = config.UPLOAD_DIR / "receipts" / str(exp.expense_date.year if exp.expense_date else date.today().year)
                subdir.mkdir(parents=True, exist_ok=True)
                ext = config.ALLOWED_RECEIPT_TYPES[ctype]
                stored = f"{date.today():%Y%m%d}-{secrets.token_hex(6)}{ext}"
                (subdir / stored).write_bytes(data)
                exp.receipt_path = f"receipts/{subdir.name}/{stored}"
                exp.receipt_original_name = Path(file.filename).name[:250]


@router.post("/ny")
async def create(request: Request,
                 csrf: str = Form(""),
                 expense_date: str = Form(...),
                 supplier: str = Form(""),
                 category_id: str = Form(""),
                 category_name_new: str = Form(""),
                 description: str = Form(""),
                 vat_code: str = Form("SE25_P"),
                 amount_mode: str = Form("gross"),
                 amount: str = Form(...),
                 vat_rate: str = Form(""),
                 deductible_vat: str = Form(""),
                 payment_method: str = Form(""),
                 payment_date: str = Form(""),
                 notes: str = Form(""),
                 receipt: UploadFile | None = None,
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF-validering misslyckades.")); db.commit()
        return RedirectResponse("/utgifter/ny", status_code=302)

    exp = Expense()
    errors: list[str] = []
    form = dict(expense_date=expense_date, supplier=supplier, category_id=category_id,
                category_name_new=category_name_new, description=description, vat_code=vat_code,
                amount_mode=amount_mode, amount=amount, vat_rate=vat_rate,
                deductible_vat=deductible_vat, payment_method=payment_method, notes=notes)
    _validate_and_fill(exp, form, receipt, errors, db, user)
    exp.payment_date = parse_date(payment_date)
    if errors:
        db.rollback()
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse("/utgifter/ny", status_code=302)

    db.add(exp)
    db.flush()
    audit.log(db, user.username, "create", "Expense", exp.id,
              summary=f"Utgift {exp.expense_date} {exp.gross_amount} kr inkl moms ({exp.category_name})")
    db.commit()
    flash(db, sess, "success",
          L(request, "Utgift sparad") + f": {exp.net_amount} kr {L(request, 'exkl. moms')}, "
          f"{L(request, 'Avdragsgill moms (kr)').split(' (')[0].lower()} {exp.deductible_vat} kr.")
    db.commit()
    return RedirectResponse("/utgifter", status_code=302)


@router.get("/{expense_id}/redigera")
def edit_form(expense_id: int, request: Request,
              db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    exp = db.get(Expense, expense_id)
    if exp is None:
        flash(db, sess, "error", "Utgiften finns inte."); db.commit()
        return RedirectResponse("/utgifter", status_code=302)
    categories = db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name)).scalars().all()
    return request.app.state.templates.TemplateResponse(request, "expense_form.html", tpl_context(
        request, db, sess, expense=exp, categories=categories,
        purchase_codes=_purchase_codes(), profile=get_profile(db), mode="gross", is_new=False,
    ))


@router.post("/{expense_id}/redigera")
async def update(expense_id: int, request: Request,
                 csrf: str = Form(""),
                 expense_date: str = Form(...),
                 supplier: str = Form(""),
                 category_id: str = Form(""),
                 category_name_new: str = Form(""),
                 description: str = Form(""),
                 vat_code: str = Form("SE25_P"),
                 amount_mode: str = Form("gross"),
                 amount: str = Form(...),
                 vat_rate: str = Form(""),
                 deductible_vat: str = Form(""),
                 payment_method: str = Form(""),
                 payment_date: str = Form(""),
                 notes: str = Form(""),
                 receipt: UploadFile | None = None,
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    exp = db.get(Expense, expense_id)
    if exp is None or not check_csrf(sess, csrf):
        db.rollback()
        flash(db, sess, "error", L(request, "Kunde inte spara.")); db.commit()
        return RedirectResponse("/utgifter", status_code=302)

    before = audit.snapshot(exp)
    errors: list[str] = []
    form = dict(expense_date=expense_date, supplier=supplier, category_id=category_id,
                category_name_new=category_name_new, description=description, vat_code=vat_code,
                amount_mode=amount_mode, amount=amount, vat_rate=vat_rate,
                deductible_vat=deductible_vat, payment_method=payment_method, notes=notes)
    _validate_and_fill(exp, form, receipt, errors, db, user)
    exp.payment_date = parse_date(payment_date)
    if errors:
        db.rollback()
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse(f"/utgifter/{expense_id}/redigera", status_code=302)

    changes = audit.diff(before, exp)
    if changes:
        audit.log(db, user.username, "update", "Expense", exp.id, summary="Utgift ändrad", changes=changes)
    db.commit()
    flash(db, sess, "success", L(request, "Utgift uppdaterad.")); db.commit()
    return RedirectResponse("/utgifter", status_code=302)


@router.post("/{expense_id}/radera")
def delete(expense_id: int, request: Request, csrf: str = Form(""),
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    exp = db.get(Expense, expense_id)
    if exp and check_csrf(sess, csrf):
        if exp.receipt_path:
            p = config.UPLOAD_DIR / exp.receipt_path
            if p.exists():
                p.unlink()
        audit.log(db, user.username, "delete", "Expense", exp.id,
                  summary=f"Utgift raderad: {exp.gross_amount} kr ({exp.expense_date})",
                  changes={"row": audit.snapshot(exp)})
        db.delete(exp)
        db.commit()
        flash(db, sess, "success", L(request, "Utgift raderad."))
    db.commit()
    return RedirectResponse("/utgifter", status_code=302)


@router.get("/{expense_id}/kvitto")
def view_receipt(expense_id: int, request: Request,
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    exp = db.get(Expense, expense_id)
    if exp is None or not exp.receipt_path:
        return RedirectResponse("/utgifter", status_code=302)
    p = config.UPLOAD_DIR / exp.receipt_path
    if not p.exists():
        return RedirectResponse("/utgifter", status_code=302)
    return FileResponse(p, filename=exp.receipt_original_name or p.name, media_type="application/octet-stream"
                        if p.suffix == ".pdf" else None)


@router.post("/kategorier/ny")
def add_category(request: Request, csrf: str = Form(""), name: str = Form(...),
                 bas: str = Form(""),
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    name = (name or "").strip()
    if name and check_csrf(sess, csrf):
        exists = db.execute(select(ExpenseCategory).where(ExpenseCategory.name == name)).scalar_one_or_none()
        if exists is None:
            cat = ExpenseCategory(name=name, bas_account_hint=(bas or "").strip())
            db.add(cat)
            db.flush()
            audit.log(db, user.username, "create", "ExpenseCategory", cat.id, summary=f"Ny kategori: {name}")
            db.commit()
            flash(db, sess, "success", L(request, "Kategori tillagd") + f": {name}")
        else:
            flash(db, sess, "error", L(request, "Kategorin finns redan."))
    db.commit()
    return RedirectResponse("/utgifter", status_code=302)
