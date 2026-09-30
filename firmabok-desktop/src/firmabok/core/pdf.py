"""PDF generation (WeasyPrint, HTML+CSS → PDF), fully local.

INVOICE PDF RULE (legal): ``render_invoice_pdf()`` is HARD-LOCKED to
Swedish. It takes no language parameter, renders only persisted DB state
(finalized invoice, frozen customer snapshot, company profile) and asserts
the Swedish locale. Tests render it under an English UI session and require
byte-identical Swedish output.

Report PDFs (vat_report_pdf.html, report_pdf.html) are support material and
DO follow the UI language via an explicit ``lang`` parameter.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from . import config
from .errors import DomainError
from .models import Invoice
from .money import format_qty, format_qty2, format_sek_lang
from .swedish import format_date_sv, month_name_sv

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
INVOICE_LOCALE = "sv"  # locked — never change (Skatteverket/legal)

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
_env.filters["sek"] = lambda v: format_sek_lang(v, INVOICE_LOCALE, symbol=False)
_env.filters["money"] = lambda v: format_sek_lang(v, INVOICE_LOCALE, symbol=True)
_env.filters["qty"] = format_qty
_env.filters["qty2"] = format_qty2
_env.filters["dsv"] = format_date_sv
_env.globals["month_name"] = lambda m: month_name_sv(m).capitalize()  # sv only


class PdfError(DomainError):
    key = "pdf.engine_missing"


def _weasyprint():
    try:
        import weasyprint  # noqa: PLC0415
        return weasyprint
    except OSError as exc:  # missing native libs
        raise PdfError("pdf.native_missing", detail=str(exc)) from exc
    except ImportError as exc:
        raise PdfError("pdf.not_installed") from exc


def _render(template_name: str, context: dict) -> bytes:
    html = _env.get_template(template_name).render(**context)
    wp = _weasyprint()
    base_url = str(config.UPLOAD_DIR) + "/"
    return wp.HTML(string=html, base_url=base_url).write_pdf()


def render_invoice_html(db: Session, invoice: Invoice) -> str:
    """Swedish invoice HTML (also used by the UI preview pane)."""
    from .invoices import customer_snapshot, get_profile, vat_breakdown  # noqa: PLC0415

    assert INVOICE_LOCALE == "sv", "invoice locale must stay Swedish"
    profile = get_profile(db)
    context = {
        "profile": profile,
        "invoice": invoice,
        "customer": customer_snapshot(invoice),
        "breakdown": vat_breakdown(invoice),
        "warnings": [],           # legal doc stays clean; guidance lives in the UI
        "logo_path": (f"logos/{Path(profile.logo_path).name}" if profile.logo_path else ""),
        "is_credit_note": invoice.is_credit_note,
        "show_vat_number": any(line.vat_code in {"EU_GOODS", "EU_SERVICES",
                                                 "EXPORT_GOODS", "SERVICES_ABROAD"}
                               for line in invoice.lines),
        # deliberate: no `_`, no lang — template contains only Swedish literals
    }
    return _env.get_template("invoice_pdf.html").render(**context)


def render_invoice_pdf(db: Session, invoice_id: int) -> bytes:
    """Swedish-only invoice PDF, rendered from persisted DB state."""
    invoice = db.get(Invoice, invoice_id)
    if invoice is None:
        raise DomainError("inv.not_found")
    html = render_invoice_html(db, invoice)
    wp = _weasyprint()
    return wp.HTML(string=html, base_url=str(config.UPLOAD_DIR) + "/").write_pdf()


def render_report_pdf(template_name: str, context: dict) -> bytes:
    """Report PDF; context must include ``lang`` ('sv' or 'en') and ``_``."""
    assert template_name in {"vat_report_pdf.html", "report_pdf.html"}
    return _render(template_name, context)


# ---------------------------------------------------------------------------
# Salary slip PDF — SWEDISH-ONLY, same rule as the invoice PDF.
# ---------------------------------------------------------------------------

SALARY_LOCALE = "sv"  # locked — never change (Skatteverket-facing document)
_EMPLOYMENT_SV = {
    "monthly": "Fast månadslön",
    "hourly": "Timlön",
    "revenue_pct": "Procent av omsättning",
    "contract": "Kontrakt (fritext)",
}


def render_salary_slip_html(db: Session, slip) -> str:
    """Swedish salary-slip HTML, rendered only from persisted DB state."""
    from decimal import Decimal  # noqa: PLC0415

    from . import employees as emp  # noqa: PLC0415
    from .invoices import get_profile  # noqa: PLC0415
    from .migrate import ensure_tax_parameters  # noqa: PLC0415

    assert SALARY_LOCALE == "sv", "salary slip locale must stay Swedish"
    profile = get_profile(db)
    employee = db.get(emp.Employee, slip.employee_id)
    if employee is None:
        raise DomainError("emp.not_found")
    params = ensure_tax_parameters(db)
    lines = []
    for ln in emp.slip_lines(slip):
        lines.append({"label": ln.get("label", ""),
                      "amount_dec": Decimal(str(ln.get("amount", "0")))})
    context = {
        "profile": profile,
        "employee": employee,
        "employee_pnr_masked": emp.mask_personnummer(employee.personnummer),
        "slip": slip,
        "lines": lines,
        "period_label": emp.period_label(slip),
        "employment_type_sv": _EMPLOYMENT_SV.get(employee.employment_type, ""),
        "params_note": params.source_note,
        "created_at": slip.created_at.date() if slip.created_at else None,
        # deliberate: no `_`, no lang — template contains only Swedish literals
    }
    return _env.get_template("salary_slip_pdf.html").render(**context)


def render_salary_slip_pdf(db: Session, slip_id: int) -> bytes:
    """Swedish-only salary slip PDF, rendered from persisted DB state."""
    from .models import SalarySlip  # noqa: PLC0415

    slip = db.get(SalarySlip, slip_id)
    if slip is None:
        raise DomainError("emp.slip_not_found")
    html = render_salary_slip_html(db, slip)
    wp = _weasyprint()
    return wp.HTML(string=html, base_url=str(config.UPLOAD_DIR) + "/").write_pdf()
