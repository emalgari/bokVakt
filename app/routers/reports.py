"""Reports: P&L, monthly/yearly summaries, category breakdown, exports."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from .. import reports
from ..db import get_db
from ..invoices import get_profile
from ..pdf import PdfError, render_pdf
from ..i18n import lang_from_request
from ..security import get_session
from ..swedish import fiscal_year_bounds, fiscal_year_of, period_of
from ..webutil import flash, parse_int, tpl_context
from .deps import web_guard

router = APIRouter(prefix="/rapporter", tags=["reports"])


def _fy_params(request: Request, db: Session, year: str):
    profile = get_profile(db)
    today = date.today()
    fy = parse_int(year, fiscal_year_of(today, profile.fiscal_year_start_month))
    start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
    return profile, fy, start, end


@router.get("")
def reports_page(request: Request, year: str = "",
                 db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile, fy, start, end = _fy_params(request, db, year)
    months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
    year_totals = reports.yearly_summary(db, fy, profile.fiscal_year_start_month)
    cats = reports.expense_by_category(db, start, end)
    pl = reports.pl_report(db, start, end)
    return request.app.state.templates.TemplateResponse(request, "reports.html", tpl_context(
        request, db, sess, fy=fy, months=months, year_totals=year_totals,
        categories=cats, pl=pl, years=[fy - 2, fy - 1, fy, fy + 1],
    ))


def _csv_response(content: str, filename: str) -> Response:
    return Response(content="\ufeff" + content,
                    media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/journal.csv")
def journal_csv(request: Request, year: str = "",
                db: Session = Depends(get_db), user=Depends(web_guard)):
    profile, fy, start, end = _fy_params(request, db, year)
    content = reports.export_journal_csv(db, start, end, lang=lang_from_request(request))
    return _csv_response(content, f"bokforingsorder_{fy}.csv")


@router.get("/ne-bilaga.csv")
def ne_csv(request: Request, year: str = "",
           db: Session = Depends(get_db), user=Depends(web_guard)):
    profile, fy, start, end = _fy_params(request, db, year)
    content = reports.export_ne_bilaga_csv(db, fy, profile.fiscal_year_start_month, lang=lang_from_request(request))
    return _csv_response(content, f"ne_bilaga_underlag_{fy}.csv")


@router.get("/manad.csv")
def month_csv(request: Request, year: str = "", month: str = "",
              db: Session = Depends(get_db), user=Depends(web_guard)):
    profile, fy, start, end = _fy_params(request, db, year)
    m = parse_int(month, 0)
    if not 1 <= m <= 12:
        m = date.today().month
    p = period_of("month", fy, m, profile.fiscal_year_start_month)
    content = reports.export_journal_csv(db, p.start, p.end, lang=lang_from_request(request))
    return _csv_response(content, f"bokforingsorder_{p.label}.csv")


@router.get("/resultat.pdf")
def pl_pdf(request: Request, year: str = "",
           db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile, fy, start, end = _fy_params(request, db, year)
    pl = reports.pl_report(db, start, end)
    months = reports.monthly_summary(db, fy, profile.fiscal_year_start_month)
    try:
        lang = lang_from_request(request)
        pdf = render_pdf("report_pdf.html", {
            "profile": profile, "title": f"Resultatrapport {fy}" if lang == "sv" else f"Profit & loss report {fy}",
            "period_text": f"{start.isoformat()} – {end.isoformat()}",
            "pl": pl, "months": months,
            "generated": date.today().isoformat(),
            "lang": lang, "_": lambda t: __import__("app.i18n", fromlist=["translate"]).translate(lang, t),
        })
    except PdfError as exc:
        flash(db, sess, "error", str(exc)); db.commit()
        return RedirectResponse("/rapporter", status_code=302)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="resultat_{fy}.pdf"'})
