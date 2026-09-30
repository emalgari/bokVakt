"""i18n: catalogs, per-route switching, locale formatting, invariants.

Rules enforced here:
* sv.json / en.json key parity (coverage).
* Every literal used via _() in templates exists in both catalogs.
* Every main route renders in English without Swedish chrome leaking.
* Money formatting is locale-aware and consistent (never mixed).
* Language never affects calculations, VAT or invoice numbering.
* Invoice PDF remains Swedish even under an English session.
* CSV/report exports follow the UI language.
"""
from __future__ import annotations

import glob
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from app import i18n
from app.money import format_sek_lang
from conftest import csrf_of, make_income

LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"

ROUTES = [
    "/dashboard", "/intakter", "/intakter/ny", "/utgifter", "/utgifter/ny",
    "/moms", "/fakturor", "/fakturor/ny", "/kunder", "/agare", "/rapporter",
    "/installningar", "/data", "/data/audit",
]


def _catalog(lang):
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_catalogs_key_parity():
    sv, en = _catalog("sv"), _catalog("en")
    assert set(sv) == set(en), (set(sv) ^ set(en))
    # sv.json is identity by design (source strings)
    assert all(k == v for k, v in sv.items())
    # no empty translations
    assert all(v.strip() for v in en.values())


def test_all_template_keys_are_catalogued():
    sv, en = _catalog("sv"), _catalog("en")
    missing = set()
    for path in glob.glob(str(Path(__file__).resolve().parent.parent / "app" / "templates" / "*.html")):
        src = open(path, encoding="utf-8").read()
        for m in re.finditer(r"""_\(\s*(["'])((?:\\.|(?!\1).)*?)\1\s*\)""", src):
            key = m.group(2).replace('\\"', '"').replace("\\'", "'")
            if key not in en or key not in sv:
                missing.add((Path(path).name, key))
    assert not missing, sorted(missing)[:20]


def test_every_route_renders_in_english(auth_client):
    client = auth_client
    r = client.get("/lang?lang=en&next=/dashboard")
    assert r.status_code == 200
    for route in ROUTES:
        r = client.get(route)
        assert r.status_code == 200, route
        t = r.text
        # Swedish nav/chrome must be gone in EN mode
        assert ">Intäkter</a>" not in t, route
        assert ">Utgifter</a>" not in t, route
    dash = client.get("/dashboard").text
    assert ">Income</a>" in dash and ">Expenses</a>" in dash


def test_every_route_renders_in_swedish_again(auth_client):
    client = auth_client
    client.get("/lang?lang=en&next=/dashboard")
    client.get("/lang?lang=sv&next=/dashboard")
    dash = client.get("/dashboard").text
    assert ">Intäkter</a>" in dash and "Nettoomsättning" in dash


def test_language_toggle_markup_accessibility(auth_client):
    client = auth_client
    t = client.get("/dashboard").text
    assert 'role="group"' in t
    assert 'aria-label="Språk"' in t
    assert 'aria-pressed="true"' in t and 'aria-pressed="false"' in t
    assert 'class="lang-toggle"' in t
    # active language highlighted
    assert re.search(r'<a href="/lang\?lang=sv[^"]*"[^>]*class="on"', t)
    client.get("/lang?lang=en&next=/dashboard")
    t = client.get("/dashboard").text
    assert 'aria-label="Language"' in t
    assert re.search(r'<a href="/lang\?lang=en[^"]*"[^>]*class="on"', t)


def test_money_formatting_per_language():
    assert format_sek_lang("1234567.5", "sv") == "1\u00a0234\u00a0567,50 kr"
    assert format_sek_lang("1234567.5", "en") == "1,234,567.50 SEK"
    assert format_sek_lang("-5.5", "sv") == "\u22125,50 kr"
    assert format_sek_lang("-5.5", "en") == "\u22125.50 SEK"
    # consistency: never mixed separators within a language
    for lang, thou, dec in (("sv", "\u00a0", ","), ("en", ",", ".")):
        s = format_sek_lang("1234.5", lang)
        assert thou in s and dec in s


def test_web_money_formatting_switches_with_language(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-03-03", "customer_name": "Fmt AB",
        "description": "Formattest", "vat_code": "SE25", "amount_mode": "net",
        "amount": "123456.78", "payment_status": "unpaid"}, follow_redirects=True)
    sv = client.get("/intakter").text
    assert "123\u00a0456,78" in sv
    client.get("/lang?lang=en&next=/intakter")
    en = client.get("/intakter").text
    assert "123,456.78" in en
    assert "123\u00a0456,78" not in en


def test_language_does_not_affect_calculations_or_numbering(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-02-02", "customer_name": "Inv AB",
        "description": "Invariant", "vat_code": "SE25", "amount_mode": "net",
        "amount": "1000", "payment_status": "unpaid"}, follow_redirects=True)
    sv = client.get("/moms?kind=quarter&year=2026&number=1").text.replace("\u00a0", " ")
    client.get("/lang?lang=en&next=/moms")
    en = client.get("/moms?kind=quarter&year=2026&number=1").text.replace("\u00a0", " ")
    # exact VAT figures identical in both languages (1 000 kr income -> 250 kr VAT)
    assert "250,00" in sv
    assert "250.00" in en
    # box numbers present in both
    assert ">05<" in sv and ">05<" in en
    assert ">49<" in sv and ">49<" in en


def test_invoice_pdf_stays_swedish_under_english_session(db, customer, profile):
    from app import pdf as pdfmod
    from app.invoices import finalize_invoice, vat_breakdown
    from conftest import make_invoice
    inv = make_invoice(db, customer, [("Konsult", "1", "1000", "SE25")],
                       invoice_date=date(2026, 3, 1))
    finalize_invoice(db, inv, username="t")
    db.commit()
    # render with an English *session* context on purpose:
    html = pdfmod._env.get_template("invoice_pdf.html").render(
        profile=profile, invoice=inv,
        customer={"name": "Kund AB", "address_line1": "G 1", "postal_code": "111 11",
                  "city": "Stan", "country": "Sverige", "org_nr": "", "vat_number": "",
                  "reference": "", "email": "", "customer_no": ""},
        breakdown=vat_breakdown(inv), warnings=[], logo_path="",
        is_credit_note=False, show_vat_number=False, lang="en")
    assert "Fakturanummer" in html and "Att betala" in html
    assert "Invoice number" not in html and "To pay" not in html


def test_csv_exports_respect_language(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-03-04", "customer_name": "Csv AB",
        "description": "Exporttest", "vat_code": "SE25", "amount_mode": "net",
        "amount": "100", "payment_status": "unpaid"}, follow_redirects=True)
    sv = client.get("/rapporter/journal.csv?year=2026").text
    assert sv.lstrip("\ufeff").splitlines()[0].startswith("Datum;Typ;Motpart")
    client.get("/lang?lang=en&next=/rapporter")
    en = client.get("/rapporter/journal.csv?year=2026").text
    assert en.lstrip("\ufeff").splitlines()[0].startswith("Date;Type;Counterparty")
    ne_en = client.get("/rapporter/ne-bilaga.csv?year=2026").text
    assert "Net turnover" in ne_en
    vat_en = client.get("/moms/export.csv?kind=quarter&year=2026&number=1").text
    assert "Output VAT 25 %" in vat_en


def test_report_pdf_english_context(db, profile):
    from app import reports
    from app import pdf as pdfmod
    make_income(db, date(2026, 3, 1), "1000.00")
    pl = reports.pl_report(db, date(2026, 1, 1), date(2026, 12, 31))
    months = reports.monthly_summary(db, 2026)
    html = pdfmod._env.get_template("report_pdf.html").render(
        profile=profile, title="Profit & loss report 2026",
        period_text="2026-01-01 – 2026-12-31", pl=pl, months=months,
        generated="2026-09-29", lang="en",
        _=lambda t: i18n.translate("en", t))
    assert "Total net revenue" in html
    assert "Year result before tax" in html
    assert "March" in html  # English month names


def test_missing_key_falls_back_to_swedish():
    assert i18n.translate("en", "Finns inte i katalogen") == "Finns inte i katalogen"
    assert i18n.translate("sv", "Vad som helst") == "Vad som helst"
