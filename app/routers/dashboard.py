"""Dashboard: year overview, monthly grid, weekly income, VAT status."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from .. import reports
from ..db import get_db
from ..invoices import get_profile
from ..models import VatReport
from ..money import ZERO, q2
from ..security import get_session
from ..swedish import fiscal_year_of, period_of
from ..webutil import parse_int, tpl_context
from .deps import web_guard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(request: Request,
              year: str = "", month: str = "",
              db: Session = Depends(get_db),
              user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    today = date.today()
    fy = parse_int(year, fiscal_year_of(today, profile.fiscal_year_start_month))
    cur_month = parse_int(month, today.month) if parse_int(month, 0) else today.month

    months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
    year_totals = reports.yearly_summary(db, fy, profile.fiscal_year_start_month)
    weeks = reports.weekly_summary(db, today.year if cur_month == today.month else fy, cur_month)

    # Current VAT period status — uses the REGISTERED redovisningsmetod
    vat_period_kind = profile.vat_period or "quarter"
    try:
        if vat_period_kind == "month":
            pnum = ((today.month - profile.fiscal_year_start_month) % 12) + 1
        elif vat_period_kind == "quarter":
            month_in_fy = ((today.month - profile.fiscal_year_start_month) % 12) + 1
            pnum = (month_in_fy - 1) // 3 + 1
        else:
            pnum = 1
        cur_period = period_of(vat_period_kind, fiscal_year_of(today, profile.fiscal_year_start_month),
                               pnum, profile.fiscal_year_start_month)
        _report, cur_decl, _ = reports.build_vat_report(
            db, vat_period_kind, cur_period.year, pnum, profile.fiscal_year_start_month,
            vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
        db.rollback()  # do not persist the report snapshot from the dashboard
        filed = db.query(VatReport).filter_by(
            period_kind=vat_period_kind, fiscal_year=cur_period.year,
            period_number=pnum, locked=True).one_or_none()
    except Exception:
        cur_period, cur_decl, filed = None, None, None

    # Compliance warnings
    warnings = []
    if not profile.company_name:
        warnings.append("Företagsnamn saknas — fyll i Inställningar.")
    if not profile.org_nr:
        warnings.append("Organisationsnummer saknas (format XXXXXX-XXXX).")
    if not profile.vat_number:
        warnings.append("Momsregistreringsnummer (SE…01) saknas.")
    elif profile.org_nr:
        from ..swedish import vat_matches_org_nr
        if not vat_matches_org_nr(profile.vat_number, profile.org_nr):
            warnings.append("Momsreg.nr stämmer inte med org.nr (ska vara SE + orgnr + 01).")
    if not profile.f_skatt_registered:
        warnings.append("F-skatt är inte markerat — fakturor visar inte F-skatt-texten.")
    _pay = profile.payment_display or "bankgiro"
    _have_pay = (profile.bankgiro if _pay == "bankgiro" else
                 profile.plusgiro if _pay == "plusgiro" else
                 (profile.bank_account_number or profile.bank_name))
    if not _have_pay:
        warnings.append("Betalningsuppgifter saknas för valt betalningssätt "
                        f"({_pay}) — fyll i under Inställningar → Företagsprofil.")
    if profile.simplified_vat_mode:
        warnings.append("FÖRENKLAT LÄGE är aktivt: momssiffrorna där är EJ korrekta och får "
                        "INTE användas till Skatteverket.")

    simplified = None
    if profile.simplified_vat_mode:
        # Deliberately WRONG calculation, clearly labelled, off by default.
        simplified = {
            "profit": year_totals.profit,
            "fake_vat": q2(year_totals.profit * Decimal("0.25")) if year_totals.profit > 0 else ZERO,
        }

    return request.app.state.templates.TemplateResponse(request, "dashboard.html", tpl_context(
        request, db, sess,
        fy=fy, months=months, year_totals=year_totals, weeks=weeks,
        cur_month=cur_month, today=today,
        vat_period_kind=vat_period_kind, cur_period=cur_period,
        cur_decl=cur_decl, period_filed=filed,
        vat_method=profile.vat_method,
        warnings=warnings, simplified=simplified,
        years=sorted({fy - 1, fy, fy + 1, fiscal_year_of(today, profile.fiscal_year_start_month)}),
    ))
