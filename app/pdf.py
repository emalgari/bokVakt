"""PDF generation with WeasyPrint (HTML + CSS → PDF), fully local.

WeasyPrint requires native libraries (pango, cairo, gdk-pixbuf, ...).
The Nix flake provides them; the import is lazy so the rest of the app
works even if they are missing, with a clear error message.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from . import config
from . import i18n
from .money import format_int_lang, format_qty, format_qty2, format_sek_lang
from .models import Invoice
from .swedish import format_date_sv

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)
# PDF-miljön: fakturor alltid svenska; rapporter följer `lang` i kontexten
# (standard sv) via pass_context-filter.


from jinja2 import pass_context as _pass_context


@_pass_context
def _sek_pdf(ctx, value):
    return format_sek_lang(value, ctx.get("lang", "sv"), symbol=False)


@_pass_context
def _money_pdf(ctx, value):
    return format_sek_lang(value, ctx.get("lang", "sv"), symbol=True)


@_pass_context
def _kronor_pdf(ctx, value):
    return format_int_lang(value, ctx.get("lang", "sv"))


_env.filters["sek"] = _sek_pdf
_env.filters["money"] = _money_pdf
_env.filters["kronor"] = _kronor_pdf
_env.filters["qty"] = format_qty
_env.filters["qty2"] = format_qty2
_env.filters["dsv"] = format_date_sv
from jinja2 import pass_context as _pc


@_pc
def _month_name_pdf(ctx, m):
    return i18n.month_name(ctx.get("lang", "sv"), m)


_env.globals["month_name"] = _month_name_pdf


class PdfError(Exception):
    pass


_NIX_LIB_EXPR = (
    "with import <nixpkgs> {}; lib.makeLibraryPath [pango cairo gdk-pixbuf "
    "harfbuzz fontconfig glib libffi zlib libjpeg openjpeg freetype libxml2 "
    "libxslt shared-mime-info]"
)


def _nix_library_path() -> str:
    """Ask nixpkgs for the colon-separated lib dirs WeasyPrint needs."""
    try:
        # NB: --raw finns inte i äldre Nix (<=2.3); --eval citerar strängen,
        # så vi strippar citattecken manuellt — fungerar på alla versioner.
        r = subprocess.run(
            ["nix-instantiate", "--eval", "-E", _NIX_LIB_EXPR],
            capture_output=True, text=True, timeout=180)
        return r.stdout.strip().strip('"')
    except Exception:
        return ""


def _weasyprint():
    try:
        import weasyprint  # noqa: WPS433
        return weasyprint
    except OSError as exc:  # missing native libs
        # Självreparation på NixOS: om skal-miljön saknar LD_LIBRARY_PATH
        # (t.ex. .venv startad utanför nix-shell), beräkna den från nixpkgs
        # och starta om processen en gång med rätt miljö.
        if Path("/nix/store").is_dir() and not os.environ.get("FIRMA_NIX_LIBS_TRIED"):
            libs = _nix_library_path()
            if libs:
                os.environ["FIRMA_NIX_LIBS_TRIED"] = "1"
                prev = os.environ.get("LD_LIBRARY_PATH", "")
                os.environ["LD_LIBRARY_PATH"] = libs + (f":{prev}" if prev else "")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        raise PdfError(
            "WeasyPrint kan inte ladda sina systembibliotek (pango/cairo/gdk-pixbuf). "
            "På NixOS: kör `scripts/run.sh`, `nix develop` eller flakans paket. "
            f"Detaljer: {exc}"
        ) from exc
    except ImportError as exc:
        raise PdfError("WeasyPrint är inte installerat (uv sync / pip install weasyprint).") from exc


def render_pdf(template_name: str, context: dict) -> bytes:
    html = _env.get_template(template_name).render(**context)
    wp = _weasyprint()
    base_url = str(config.UPLOAD_DIR) + "/"
    return wp.HTML(string=html, base_url=base_url).write_pdf()


def invoice_pdf(db: Session, invoice: Invoice) -> bytes:
    """Render a finalized invoice (or draft preview) to PDF."""
    from .invoices import customer_snapshot, get_profile, vat_breakdown

    profile = get_profile(db)
    snapshot = customer_snapshot(invoice)
    breakdown = vat_breakdown(invoice)

    # NB: inga varningar/varningar på själva fakturadokumentet — kundfakturan
    # ska vara ren. Kompletthetskontroller visas endast i webbgränssnittet
    # (dashboard/varningssidor), aldrig på PDF:en.
    context = {
        "profile": profile,
        "invoice": invoice,
        "customer": snapshot,
        "breakdown": breakdown,
        "logo_path": (f"logos/{Path(profile.logo_path).name}" if profile.logo_path else ""),
        "is_credit_note": invoice.is_credit_note,
        # Momsreg.nr visas i footern endast vid gränsöverskridande försäljning
        # (krav vid EU/export) — inhemska fakturor följer mallen exakt.
        "show_vat_number": any(l.vat_code in {"EU_GOODS", "EU_SERVICES",
                                              "EXPORT_GOODS", "SERVICES_ABROAD"}
                               for l in invoice.lines),
    }
    return render_pdf("invoice_pdf.html", context)
