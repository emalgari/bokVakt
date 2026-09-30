"""Settings: company profile, invoice defaults, bookkeeping options, logo,
password change, and the clearly-labelled non-compliant simplified mode."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import audit, config
from ..db import get_db
from ..invoices import get_profile
from ..security import get_session, hash_password, verify_password
from ..swedish import normalize_org_nr, normalize_vat_number, vat_matches_org_nr
from ..webutil import L, flash, parse_bool, parse_decimal, parse_int, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/installningar", tags=["settings"])


@router.get("")
def settings_page(request: Request, db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    return request.app.state.templates.TemplateResponse(request, "settings.html", tpl_context(
        request, db, sess, profile=profile, user=user,
    ))


@router.post("/foretag")
async def save_company(request: Request, csrf: str = Form(""),
                       company_name: str = Form(""),
                       org_nr: str = Form(""), vat_number: str = Form(""),
                       f_skatt_registered: str = Form(""), f_skatt_text: str = Form(""),
                       address_line1: str = Form(""), address_line2: str = Form(""),
                       postal_code: str = Form(""), city: str = Form(""), country: str = Form("Sverige"),
                       phone: str = Form(""), email: str = Form(""), website: str = Form(""),
                       bank_name: str = Form(""), bankgiro: str = Form(""), plusgiro: str = Form(""),
                       iban: str = Form(""), bic: str = Form(""),
                       bank_account_number: str = Form(""),
                       business_description: str = Form(""), sni_codes: str = Form(""),
                       logo: UploadFile | None = None,
                       db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)

    before = audit.snapshot(profile)
    errors, warnings = [], []

    org = (org_nr or "").strip()
    if org:
        try:
            profile.org_nr = normalize_org_nr(org)
        except ValueError as exc:
            errors.append(L(request, str(exc)))
    else:
        profile.org_nr = ""

    vatn = (vat_number or "").replace(" ", "").strip()
    if vatn:
        try:
            profile.vat_number = normalize_vat_number(vatn)
            if profile.org_nr and not vat_matches_org_nr(profile.vat_number, profile.org_nr):
                warnings.append("Momsreg.nr motsvarar inte org.nr (förväntat SE" +
                                profile.org_nr.replace("-", "") + "01).")
        except ValueError as exc:
            errors.append(L(request, str(exc)))
    else:
        profile.vat_number = ""

    if errors:
        db.rollback()
        flash(db, sess, "error", " ".join(errors)); db.commit()
        return RedirectResponse("/installningar", status_code=302)

    profile.company_name = (company_name or "").strip()
    profile.f_skatt_registered = parse_bool(f_skatt_registered)
    profile.f_skatt_text = (f_skatt_text or "").strip() or "Godkänd för F-skatt"
    for f_ in ("address_line1", "address_line2", "postal_code", "city", "phone", "email",
               "website", "bank_name", "iban", "bic", "bank_account_number",
               "business_description", "sni_codes"):
        setattr(profile, f_, (locals()[f_] or "").strip())
    profile.country = (country or "Sverige").strip() or "Sverige"
    # Bankgiro: 7-9 digits, often shown as 123,456-7 — store digits+dash normalized
    bg = "".join(ch for ch in (bankgiro or "") if ch.isdigit() or ch == "-")
    if bg and "-" not in bg and len(bg) in (8, 9):
        bg = bg[:-1] + "-" + bg[-1:]
    profile.bankgiro = bg
    pg = "".join(ch for ch in (plusgiro or "") if ch.isdigit() or ch == "-")
    if pg and "-" not in pg and len(pg) in (8, 9, 10):
        pg = pg[:-1] + "-" + pg[-1:]
    profile.plusgiro = pg

    if logo is not None and logo.filename:
        ctype = (logo.content_type or "").lower()
        if ctype not in config.ALLOWED_LOGO_TYPES:
            warnings.append(L(request, "Logotyp måste vara jpg/png/svg/pdf — filen sparades inte."))
        else:
            data = logo.file.read()
            if len(data) > config.MAX_UPLOAD_BYTES:
                warnings.append(L(request, "Logotypen är större än 10 MB — sparades inte."))
            else:
                config.UPLOAD_DIR.joinpath("logos").mkdir(parents=True, exist_ok=True)
                ext = config.ALLOWED_LOGO_TYPES[ctype]
                stored = f"logo-{secrets.token_hex(4)}{ext}"
                (config.UPLOAD_DIR / "logos" / stored).write_bytes(data)
                profile.logo_path = f"logos/{stored}"

    changes = audit.diff(before, profile)
    if changes:
        audit.log(db, user.username, "update", "CompanyProfile", 1,
                  summary="Företagsprofil uppdaterad", changes=changes)
    db.commit()
    msg = L(request, "Företagsinställningar sparade.")
    if warnings:
        msg += " " + " ".join(warnings)
    flash(db, sess, "warning" if warnings else "success", msg); db.commit()
    return RedirectResponse("/installningar", status_code=302)


@router.post("/faktura")
def save_invoice_settings(request: Request, csrf: str = Form(""),
                          payment_terms_days: str = Form("30"),
                          late_interest_rate: str = Form(""),
                          late_interest_text: str = Form(""),
                          round_total_to_krona: str = Form(""),
                          payment_display: str = Form("bankgiro"),
                          invoice_show_ocr: str = Form(""),
                          invoice_notes: str = Form(""),
                          invoice_number_prefix: str = Form(""),
                          invoice_number_digits: str = Form("4"),
                          invoice_number_start: str = Form("1"),
                          db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    before = audit.snapshot(profile)
    profile.payment_terms_days = max(0, parse_int(payment_terms_days, 30))
    lir = parse_decimal(late_interest_rate, profile.late_interest_rate)
    if lir is not None and lir >= 0:
        profile.late_interest_rate = lir
    profile.invoice_notes = (invoice_notes or "").strip()
    profile.late_interest_text = (late_interest_text or "").strip() or (
        "Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.")
    profile.round_total_to_krona = parse_bool(round_total_to_krona)
    if payment_display in ("bankgiro", "plusgiro", "bankaccount"):
        profile.payment_display = payment_display
    profile.invoice_show_ocr = parse_bool(invoice_show_ocr)
    profile.invoice_number_prefix = (invoice_number_prefix or "").strip()[:8]
    profile.invoice_number_digits = max(2, min(8, parse_int(invoice_number_digits, 4)))
    profile.invoice_number_start = max(1, parse_int(invoice_number_start, 1))
    changes = audit.diff(before, profile)
    if changes:
        audit.log(db, user.username, "update", "CompanyProfile", 1,
                  summary="Fakturainställningar uppdaterade", changes=changes)
    db.commit()
    flash(db, sess, "success", L(request, "Fakturainställningar sparade. OBS: nummerseriens start gäller bara serier som ännu inte påbörjats.")); db.commit()
    return RedirectResponse("/installningar", status_code=302)


@router.post("/bokforing")
def save_bookkeeping(request: Request, csrf: str = Form(""),
                     fiscal_year_start_month: str = Form("1"),
                     vat_period: str = Form("quarter"),
                     vat_method: str = Form("faktura"),
                     input_vat_on_payment: str = Form(""),
                     default_vat_rate: str = Form("25"),
                     simplified_vat_mode: str = Form(""),
                     simplified_confirm: str = Form(""),
                     db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    before = audit.snapshot(profile)

    m = parse_int(fiscal_year_start_month, 1)
    if not 1 <= m <= 12:
        m = 1
    profile.fiscal_year_start_month = m
    if vat_period in ("month", "quarter", "year"):
        profile.vat_period = vat_period
    if vat_method in ("faktura", "bokslut"):
        profile.vat_method = vat_method
    profile.input_vat_on_payment = parse_bool(input_vat_on_payment)
    from decimal import Decimal
    rate = parse_decimal(default_vat_rate, profile.default_vat_rate)
    if rate in (Decimal("0"), Decimal("6"), Decimal("12"), Decimal("25")):
        profile.default_vat_rate = rate

    want_simplified = parse_bool(simplified_vat_mode)
    if want_simplified and simplified_confirm.strip().upper() != "JAG FÖRSTÅR":
        flash(db, sess, "error",
              "Förenklat läge kräver bekräftelse: skriv exakt 'JAG FÖRSTÅR' i bekräftelsefältet. "
              "Läget är EJ korrekt och får INTE användas för Skatteverket.")
        db.rollback(); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    profile.simplified_vat_mode = want_simplified

    changes = audit.diff(before, profile)
    if changes:
        audit.log(db, user.username, "update", "CompanyProfile", 1,
                  summary="Bokföringsinställningar uppdaterade", changes=changes)
    db.commit()
    if want_simplified:
        flash(db, sess, "warning",
              "Förenklat läge AKTIVERAT: momssiffror på dashboarden är beräknade på vinst och är "
              "FELAKTIGA ur svensk momssynpunkt. Använd dem INTE till Skatteverket. "
              "Momsmodulen visar fortsatt korrekta siffror.")
    else:
        flash(db, sess, "success", L(request, "Bokföringsinställningar sparade (korrekt momsläge)."))
    db.commit()
    return RedirectResponse("/installningar", status_code=302)


@router.post("/losenord")
def change_password(request: Request, csrf: str = Form(""),
                    current_password: str = Form(""),
                    new_password: str = Form(""), new_password2: str = Form(""),
                    db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    if not verify_password(current_password or "", user.password_hash, user.password_salt):
        flash(db, sess, "error", L(request, "Nuvarande lösenord är fel.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    if len(new_password or "") < 8:
        flash(db, sess, "error", L(request, "Nytt lösenord måste vara minst 8 tecken.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    if new_password != new_password2:
        flash(db, sess, "error", L(request, "De nya lösenorden matchar inte.")); db.commit()
        return RedirectResponse("/installningar", status_code=302)
    pw_hash, salt = hash_password(new_password)
    user.password_hash, user.password_salt = pw_hash, salt
    audit.log(db, user.username, "update", "User", user.id, summary="Lösenord ändrat")
    db.commit()
    flash(db, sess, "success", L(request, "Lösenord ändrat.")); db.commit()
    return RedirectResponse("/installningar", status_code=302)


@router.post("/logotyp/radera")
def remove_logo(request: Request, csrf: str = Form(""),
                db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    if check_csrf(sess, csrf) and profile.logo_path:
        p = config.UPLOAD_DIR / profile.logo_path
        if p.exists():
            p.unlink()
        profile.logo_path = ""
        audit.log(db, user.username, "update", "CompanyProfile", 1, summary="Logotyp borttagen")
        db.commit()
        flash(db, sess, "success", L(request, "Logotyp borttagen."))
    db.commit()
    return RedirectResponse("/installningar", status_code=302)
