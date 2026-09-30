"""VAT (moms) module: declaration per period, Skatteverket boxes, exports."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, reports, vat as vatmod
from ..db import get_db
from ..invoices import get_profile
from ..models import VatReport
from ..money import ZERO
from ..pdf import PdfError, render_pdf
from ..i18n import lang_from_request
from ..security import get_session
from ..swedish import fiscal_year_of
from ..webutil import L, flash, parse_int, tpl_context
from .deps import check_csrf, web_guard

router = APIRouter(prefix="/moms", tags=["vat"])

KIND_LABELS = {"month": "Månadsvis", "quarter": "Kvartalsvis", "year": "Årsvis"}


def _resolve(request_kind: str, year: str, number: str, profile, today):
    kind = request_kind if request_kind in KIND_LABELS else (profile.vat_period or "quarter")
    fy = parse_int(year, fiscal_year_of(today, profile.fiscal_year_start_month))
    max_n = {"month": 12, "quarter": 4, "year": 1}[kind]
    if kind == "year":
        num = 1
    else:
        num = parse_int(number, 0)
        if not 1 <= num <= max_n:
            # default to the current period of that kind
            m_in_fy = ((today.month - profile.fiscal_year_start_month) % 12) + 1
            num = m_in_fy if kind == "month" else (m_in_fy - 1) // 3 + 1
            if fiscal_year_of(today, profile.fiscal_year_start_month) != fy:
                num = 1
    return kind, fy, num


@router.get("")
def vat_page(request: Request, kind: str = "", year: str = "", number: str = "",
             db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    from datetime import date
    kind, fy, num = _resolve(kind, year, number, profile, date.today())
    report, decl, period = reports.build_vat_report(
        db, kind, fy, num, profile.fiscal_year_start_month,
        vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
    db.commit()

    stored = db.execute(select(VatReport).order_by(VatReport.start_date.desc()).limit(24)).scalars().all()
    boxes_rows = []
    for b in vatmod.ALL_BOXES:
        exact = decl.boxes.get(b, ZERO)
        kronor = decl.boxes_kronor.get(b, 0)
        if b == "49" or exact != 0 or kronor != 0:
            boxes_rows.append({"box": b, "label": vatmod.BOX_LABELS_SV.get(b, ""),
                               "kronor": kronor, "exact": exact})

    period_labels = {
        "month": [(n, "Månad") for n in range(1, 13)],
        "quarter": [(n, "Kvartal") for n in range(1, 5)],
        "year": [(1, "Hela året")],
    }[kind]

    from ..swedish import filing_due
    method_label = ("Bokslutsmetoden (kontantmetoden) — moms redovisas när betalning sker"
                    if profile.vat_method == "bokslut" else
                    "Fakturametoden — moms redovisas per faktureringsdatum")

    return request.app.state.templates.TemplateResponse(request, "vat.html", tpl_context(
        request, db, sess,
        kind=kind, fy=fy, num=num, period=period, report=report, decl=decl,
        boxes_rows=boxes_rows, stored_reports=stored, period_labels=period_labels,
        kind_labels=KIND_LABELS, years=[fy - 1, fy, fy + 1],
        method_label=method_label, vat_method=profile.vat_method,
        due_date=filing_due(period.end),
    ))


@router.post("/spara")
def save_report(request: Request, csrf: str = Form(""),
                kind: str = Form("quarter"), year: str = Form(...), number: str = Form("1"),
                action: str = Form("save"),
                db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    if not check_csrf(sess, csrf):
        flash(db, sess, "error", L(request, "CSRF-validering misslyckades.")); db.commit()
        return RedirectResponse("/moms", status_code=302)
    profile = get_profile(db)
    fy = parse_int(year, fiscal_year_of(__import__("datetime").date.today(), profile.fiscal_year_start_month))
    num = parse_int(number, 1)
    report, decl, period = reports.build_vat_report(
        db, kind, fy, num, profile.fiscal_year_start_month,
        vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)

    if report.locked and action != "unlock":
        flash(db, sess, "error", L(request, "Perioden är låst (deklarerad). Lås upp först om du gjort ändringar."))
        db.commit()
        return RedirectResponse(f"/moms?kind={kind}&year={fy}&number={num}", status_code=302)

    if action == "lock":
        report.locked = True
        from datetime import datetime, timezone
        report.filed_at = datetime.now(timezone.utc)
        audit.log(db, user.username, "finalize", "VatReport", report.id,
                  summary=f"Momsperiod {period.label} låst/deklarerad. Fält 49: {decl.net_vat_kronor} kr")
        db.commit()
        flash(db, sess, "success", f"{L(request, 'Period')} {period.label} {L(request, 'sparad och låst')}. "
                                   f"{L(request, 'Moms att betala') if decl.net_vat_kronor >= 0 else L(request, 'Moms att få tillbaka')}: "
                                   f"{abs(decl.net_vat_kronor)} kr ({L(request, 'fält')} 49).")
    elif action == "unlock":
        report.locked = False
        report.filed_at = None
        audit.log(db, user.username, "update", "VatReport", report.id,
                  summary=f"Momsperiod {period.label} upplåst")
        db.commit()
        flash(db, sess, "success", f"{L(request, 'Period')} {period.label} {L(request, 'upplåst')}. "
                                   + L(request, "Kom ihåg att rätta deklarationen hos Skatteverket om den lämnats in."))
    else:
        audit.log(db, user.username, "update", "VatReport", report.id,
                  summary=f"Momsrapport {period.label} sparad (olåst)")
        db.commit()
        flash(db, sess, "success", f"{L(request, 'Rapport för')} {period.label} {L(request, 'sparad (ej låst)')}.")
    db.commit()
    return RedirectResponse(f"/moms?kind={kind}&year={fy}&number={num}", status_code=302)


@router.get("/export.csv")
def export_csv(request: Request, kind: str = "", year: str = "", number: str = "",
               db: Session = Depends(get_db), user=Depends(web_guard)):
    profile = get_profile(db)
    from datetime import date
    kind, fy, num = _resolve(kind, year, number, profile, date.today())
    report, decl, period = reports.build_vat_report(
        db, kind, fy, num, profile.fiscal_year_start_month,
        vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
    db.commit()
    content = reports.export_vat_declaration_csv(decl, lang=lang_from_request(request))
    filename = f"momsdeklaration_{period.label}.csv"
    return Response(
        content="\ufeff" + content,  # BOM for Excel
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export.pdf")
def export_pdf(request: Request, kind: str = "", year: str = "", number: str = "",
               db: Session = Depends(get_db), user=Depends(web_guard)):
    sess = get_session(request, db)
    profile = get_profile(db)
    from datetime import date
    kind, fy, num = _resolve(kind, year, number, profile, date.today())
    report, decl, period = reports.build_vat_report(
        db, kind, fy, num, profile.fiscal_year_start_month,
        vat_method=profile.vat_method, input_vat_on_payment=profile.input_vat_on_payment)
    db.commit()
    boxes_rows = [
        {"box": b, "label": vatmod.BOX_LABELS_SV.get(b, ""),
         "kronor": decl.boxes_kronor.get(b, 0), "exact": decl.boxes.get(b, ZERO)}
        for b in vatmod.ALL_BOXES
        if b == "49" or decl.boxes.get(b, ZERO) != 0 or decl.boxes_kronor.get(b, 0) != 0
    ]
    try:
        lang = lang_from_request(request)
        from ..i18n import translate as _tr
        pdf = render_pdf("vat_report_pdf.html", {
            "profile": profile, "period": period, "decl": decl,
            "boxes_rows": boxes_rows, "report": report,
            "kind_label": _tr(lang, KIND_LABELS[kind]),
            "lang": lang, "_": _tr and (lambda t: _tr(lang, t)),
        })
    except PdfError as exc:
        flash(db, sess, "error", str(exc)); db.commit()
        return RedirectResponse(f"/moms?kind={kind}&year={fy}&number={num}", status_code=302)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="momsrapport_{period.label}.pdf"'})
