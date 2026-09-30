"""Salary slip PDF: Swedish-only under any UI language, single A4 page."""
from __future__ import annotations

from decimal import Decimal

import pytest

from firmabok.core import employees as emp
from firmabok.core import pdf as core_pdf
from firmabok.core.models import Employee, SalarySlip, SalarySlipSeries
from firmabok.i18n import init_language


@pytest.fixture(autouse=True)
def _clean(db):
    db.query(SalarySlip).delete()
    db.query(SalarySlipSeries).delete()
    db.query(Employee).delete()
    db.commit()
    yield
    db.query(SalarySlip).delete()
    db.query(SalarySlipSeries).delete()
    db.query(Employee).delete()
    db.commit()


@pytest.fixture()
def slip(db, profile):
    profile.company_name = "Test Konsult"
    profile.org_nr = "830116-0571"
    e = Employee(name="Sven Testsson", personnummer="010101-1234",
                 address_line1="Testgatan 1", postal_code="111 11", city="Stockholm",
                 employment_type="monthly", monthly_salary=Decimal("30000.00"),
                 bank_account="Konto 1234-5678", tax_table_note="Tabell 35")
    db.add(e)
    db.commit()
    s = emp.create_slip(db, e, 2026, 5, a_tax=Decimal("9000"))
    db.commit()
    return s


def _page_count(data: bytes) -> int:
    # page objects may live in compressed object streams; use the renderer API
    html = data  # unused; kept for signature symmetry
    del html
    return -1


def test_slip_html_swedish_under_english_ui(db, slip):
    init_language("en")
    try:
        html = core_pdf.render_salary_slip_html(db, slip)
    finally:
        init_language("sv")
    for sv in ["LÖNESPECIFIKATION", "Bruttoslön", "NETTOLÖN", "Arbetsgivaravgifter",
               "Skatteavdrag (A-skatt)", "Utbetalas till", "Löneperiod", "Mottagare (anställd)",
               "Organisationsnr"]:
        assert sv in html, f"missing Swedish label: {sv}"
    for en in ["Gross salary", "Net salary", "Employer contributions", "Salary slip",
               "Pay period", "Recipient"]:
        assert en not in html, f"English leaked into salary slip: {en}"
    # personnummer masked on the slip (local storage decision)
    assert "010101-1234" not in html
    assert "1234" in html


def test_slip_html_identical_across_languages(db, slip):
    init_language("sv")
    html_sv = core_pdf.render_salary_slip_html(db, slip)
    init_language("en")
    try:
        html_en = core_pdf.render_salary_slip_html(db, slip)
    finally:
        init_language("sv")
    assert html_sv == html_en


def test_slip_pdf_bytes_single_page(db, slip):
    data = core_pdf.render_salary_slip_pdf(db, slip.id)
    assert data.startswith(b"%PDF")
    assert len(data) > 2000
    try:
        import weasyprint
    except (ImportError, OSError):
        pytest.skip("weasyprint native libs unavailable")
    html = core_pdf.render_salary_slip_html(db, slip)
    doc = weasyprint.HTML(string=html).render()
    assert len(doc.pages) == 1


def test_missing_slip_raises(db):
    from firmabok.core.errors import DomainError
    with pytest.raises(DomainError) as exc:
        core_pdf.render_salary_slip_pdf(db, 999999)
    assert exc.value.key == "emp.slip_not_found"
