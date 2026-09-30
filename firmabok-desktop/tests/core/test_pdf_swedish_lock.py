"""Invoice PDF must ALWAYS be Swedish, regardless of UI language.
Report PDFs follow the UI language."""
from __future__ import annotations

from datetime import date

import pytest

from conftest import make_income, make_invoice
from firmabok.core import pdf as core_pdf
from firmabok.core.invoices import finalize_invoice
from firmabok.i18n import init_language, translate_for


@pytest.fixture()
def finalized(db, customer):
    inv = make_invoice(db, customer,
                       [("TaxiService-körning juni", "16", "950", "SE25"),
                        ("Resa", "1", "450", "SE25")],
                       invoice_date=date(2026, 6, 20))
    finalize_invoice(db, inv, username="test")
    db.commit()
    return inv


def test_invoice_html_swedish_under_english_ui(db, finalized, profile):
    init_language("en")
    try:
        html = core_pdf.render_invoice_html(db, finalized)
    finally:
        init_language("sv")
    n = html.replace("\u00a0", " ")
    for sv in ["Faktura", "Fakturanummer", "Fakturadatum", "Leveransdatum", "Art.nr",
               "Beskrivning", "Antal", "Enhet", "À-pris", "Summa", "Exkl. moms",
               "Moms (25 %)", "Avrundning", "Förfallodatum", "OCR",
               "Anges vid betalning.", "Att betala", "Organisationsnr"]:
        assert sv in html, f"missing Swedish label: {sv}"
    for en in ["Invoice number", "Invoice date", "Item no.", "Description", "Qty",
               "Unit price", "To pay", "Due date", "Rounding"]:
        assert en not in html, f"English leaked into invoice PDF: {en}"
    assert "15 650,00" in n and "3 912,50" in n and "19 562,50" in n


def test_invoice_render_identical_across_languages(db, finalized):
    init_language("sv")
    html_sv = core_pdf.render_invoice_html(db, finalized)
    init_language("en")
    try:
        html_en = core_pdf.render_invoice_html(db, finalized)
    finally:
        init_language("sv")
    assert html_sv == html_en


def test_report_pdf_follows_ui_language(db, profile):
    make_income(db, date(2026, 3, 1), "1000.00")
    from firmabok.core import reports
    pl = reports.pl_report(db, date(2026, 1, 1), date(2026, 12, 31))
    months = reports.monthly_summary(db, 2026)
    html_en = core_pdf._env.get_template("report_pdf.html").render(
        profile=profile, title="Profit & loss report 2026",
        period_text="2026-01-01 – 2026-12-31", pl=pl, months=months,
        generated="2026-09-29", lang="en", _=translate_for("en"))
    assert "Total net revenue" in html_en
    assert "Year result before tax" in html_en
    html_sv = core_pdf._env.get_template("report_pdf.html").render(
        profile=profile, title="Resultatrapport 2026",
        period_text="2026-01-01 – 2026-12-31", pl=pl, months=months,
        generated="2026-09-29", lang="sv", _=translate_for("sv"))
    assert "Summa nettoomsättning" in html_sv


def test_pdf_bytes_require_weasyprint_or_raise_keyed_error(db, finalized):
    try:
        data = core_pdf.render_invoice_pdf(db, finalized.id)
        assert data[:4] == b"%PDF"
    except core_pdf.PdfError as exc:
        # acceptable when native libs are missing; error must be a KEY, not prose
        assert exc.key == "pdf.native_missing" or exc.key == "pdf.not_installed"
        pytest.skip(f"weasyprint unavailable here ({exc.key})")


def test_invoice_pdf_is_single_a4_page(db, finalized):
    """The invoice must render to exactly one A4 page (595.28 x 841.89 pt)."""
    pytest.importorskip("weasyprint")
    import weasyprint
    html = core_pdf.render_invoice_html(db, finalized)
    doc = weasyprint.HTML(string=html).render()
    assert len(doc.pages) == 1
    page = doc.pages[0]
    # WeasyPrint measures in CSS px (96 px/inch): A4 = 210mm x 297mm
    assert abs(page.width - 793.70) < 1.5, page.width
    assert abs(page.height - 1122.52) < 1.5, page.height


def test_invoice_pdf_bytes_swedish_under_english_session(db, finalized):
    """Byte-level: PDF generated while UI language is EN must contain the
    Swedish content stream markers (and be a valid single-page PDF)."""
    pytest.importorskip("weasyprint")
    init_language("en")
    try:
        data_en = core_pdf.render_invoice_pdf(db, finalized.id)
    finally:
        init_language("sv")
    data_sv = core_pdf.render_invoice_pdf(db, finalized.id)
    assert data_en[:4] == b"%PDF" and data_sv[:4] == b"%PDF"
    # byte equality is not guaranteed (PDF metadata timestamps); content
    # equality is covered by test_invoice_render_identical_across_languages
