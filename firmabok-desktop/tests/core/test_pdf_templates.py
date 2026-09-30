"""PDF template tests.

The Jinja templates are always rendered to HTML (catches template errors).
The WeasyPrint step runs only when its native libraries are available
(pango/cairo — provided by the Nix flake on NixOS).
"""
from datetime import date

import pytest

from conftest import make_income, make_invoice
from firmabok.core import pdf as pdfmod
from firmabok.core import reports
from firmabok.core.invoices import finalize_invoice, vat_breakdown
from firmabok.core.models import IncomeEntry
from firmabok.core.money import ZERO
from firmabok.core.vat import ALL_BOXES, BOX_LABELS_SV, compute_declaration


def weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        weasyprint.HTML(string="<p>hej</p>").write_pdf()
        return True
    except Exception:
        return False


HAS_PDF = weasyprint_available()


def _finalized(db, customer):
    inv = make_invoice(db, customer,
                       [("Konsulttjänster mars", "16", "950", "SE25"),
                        ("Resekostnad", "1", "450", "SE25")],
                       invoice_date=date(2026, 3, 15))
    finalize_invoice(db, inv, username="test", book_income=True)
    db.commit()
    return inv


def test_invoice_template_renders_html(db, customer, profile):
    profile.company_name = "Test Konsult"
    profile.f_skatt_registered = True
    profile.bankgiro = "123,456-7"
    db.commit()
    inv = _finalized(db, customer)
    inv.lines[0].article_no = "11"
    db.commit()
    html = pdfmod._env.get_template("invoice_pdf.html").render(
        profile=profile, invoice=inv,
        customer={"name": "Testkund AB", "address_line1": "Gatan 1", "postal_code": "111 11",
                  "city": "Stockholm", "country": "Sverige", "org_nr": "", "vat_number": "",
                  "reference": "", "email": "", "customer_no": "22"},
        breakdown=vat_breakdown(inv),
        warnings=[], logo_path="", is_credit_note=False,
    )
    n = html.replace("\u00a0", " ")
    # Template labels from sample_Faktura.pdf
    for label in ["Faktura", "Fakturanummer", "2026-0001", "Kundnr", "Fakturadatum",
                  "Leveransdatum", "Dröjsmålsränta", "Art.nr", "Beskrivning", "Antal",
                  "Enhet", "À-pris", "Summa", "Exkl. moms", "Moms (25 %)", "Avrundning",
                  "Förfallodatum", "OCR", "Anges vid betalning.", "Bankgiro", "Att betala",
                  "Adress", "Telefon", "Organisationsnr", "Godkänd för F-skatt",
                  "Sida ", " debiteras ränta enligt räntelagen."]:
        assert label in html, f"saknas i PDF-mallen: {label}"
    assert "11" in html  # art.nr rendered
    # Totals: 16×950 + 450 = 15 650 net; 25 % = 3 912,50; gross 19 562,50
    assert "15 650,00" in n
    assert "3 912,50" in n
    assert "19 562,50" in n


@pytest.mark.skipif(not HAS_PDF, reason="WeasyPrint native libs not available in this env")
def test_invoice_pdf_bytes(db, customer, profile):
    inv = _finalized(db, customer)
    data = pdfmod.render_invoice_pdf(db, inv.id)
    assert data[:4] == b"%PDF"
    assert len(data) > 2000


def test_vat_report_template_renders_html(db, profile):
    make_income(db, date(2026, 4, 10), "10000.00")
    incomes = db.query(IncomeEntry).all()
    decl = compute_declaration(incomes, [], date(2026, 4, 1), date(2026, 6, 30))
    report, _, period = reports.build_vat_report(db, "quarter", 2026, 2)
    db.commit()
    boxes_rows = [{"box": b, "label": BOX_LABELS_SV.get(b, ""),
                   "kronor": decl.boxes_kronor.get(b, 0), "exact": decl.boxes.get(b, ZERO)}
                  for b in ALL_BOXES]
    html = pdfmod._env.get_template("vat_report_pdf.html").render(
        profile=profile, period=period, decl=decl, boxes_rows=boxes_rows,
        report=report, kind_label="Kvartal", lang="sv",
        _=lambda t: t,
    )
    assert "Momsredovisning" in html
    assert "2 500" in html or "2\u00a0500" in html


def test_report_pdf_template_renders_html(db, profile):
    make_income(db, date(2026, 3, 1), "1000.00")
    pl = reports.pl_report(db, date(2026, 1, 1), date(2026, 12, 31))
    months = reports.monthly_summary(db, 2026)
    html = pdfmod._env.get_template("report_pdf.html").render(
        profile=profile, title="Resultatrapport 2026",
        period_text="2026-01-01 – 2026-12-31", pl=pl, months=months,
        generated="2026-09-29", lang="sv", _=lambda t: t,
    )
    assert "Resultat" in html
    assert "1 000,00" in html or "1\u00a0000,00" in html


def test_invoice_template_stable_with_many_lines(db, customer, profile):
    """The bottom block must stay pinned without abspos: spacer row shrinks."""
    import re
    inv = make_invoice(db, customer,
                       [(f"Körning vecka {i}", "1", "1200", "SE25") for i in range(1, 13)],
                       invoice_date=date(2026, 3, 15))
    finalize_invoice(db, inv, username="test", book_income=True)
    db.commit()
    html = pdfmod._env.get_template("invoice_pdf.html").render(
        profile=profile, invoice=inv,
        customer={"name": "Kund", "address_line1": "G 1", "postal_code": "111 11",
                  "city": "Stan", "country": "Sverige", "org_nr": "", "vat_number": "",
                  "reference": "", "email": "", "customer_no": ""},
        breakdown=vat_breakdown(inv), warnings=[], logo_path="",
        is_credit_note=False, show_vat_number=False)
    m = re.search(r'class="spacer"><td colspan="6" style="height:([\d.]+)mm', html)
    assert m and float(m.group(1)) >= 4
    assert "Att betala" in html and "Exkl. moms" in html
    # no risky CSS in the invoice template (WeasyPrint stability)
    css = html[html.index("<style>"):html.index("</style>")]
    assert "position: absolute" not in css and "display: flex" not in css


def test_invoice_pdf_clean_no_warnings_and_toggles(db, customer, profile):
    """The invoice document must never carry warning messages; OCR and
    payment destination follow the settings."""
    profile.bankgiro = ""
    profile.plusgiro = ""
    profile.iban = ""
    profile.invoice_show_ocr = False
    profile.payment_display = "bankaccount"
    profile.bank_name = "Swedbank"
    profile.bank_account_number = "3456-7890"
    db.commit()
    inv = _finalized(db, customer)
    html = pdfmod._env.get_template("invoice_pdf.html").render(
        profile=profile, invoice=inv,
        customer={"name": "Kund", "address_line1": "G 1", "postal_code": "111 11",
                  "city": "Stan", "country": "Sverige", "org_nr": "", "vat_number": "",
                  "reference": "", "email": "", "customer_no": ""},
        breakdown=vat_breakdown(inv), warnings=[], logo_path="",
        is_credit_note=False, show_vat_number=False)
    assert "saknas" not in html.lower()
    assert "Bankuppgifter" not in html
    assert ">OCR<" not in html                      # OCR toggled off
    assert "Anges vid betalning." not in html
    assert "Kontonr" in html and "3456-7890" in html  # bank account destination
    assert "Swedbank" in html
    assert "Bankgiro" not in html

    # OCR back on
    profile.invoice_show_ocr = True
    db.commit()
    html2 = pdfmod._env.get_template("invoice_pdf.html").render(
        profile=profile, invoice=inv,
        customer={"name": "Kund", "address_line1": "G 1", "postal_code": "111 11",
                  "city": "Stan", "country": "Sverige", "org_nr": "", "vat_number": "",
                  "reference": "", "email": "", "customer_no": ""},
        breakdown=vat_breakdown(inv), warnings=[], logo_path="",
        is_credit_note=False, show_vat_number=False)
    assert ">OCR<" in html2 and "Anges vid betalning." in html2
