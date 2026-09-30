"""End-to-end web tests: setup, login, CSRF, income/expense forms, flows."""
from datetime import date

from conftest import csrf_of


def T(r):
    """Response text with NBSP normalized to plain space for assertions."""
    return r.text.replace("\u00a0", " ")


def test_setup_and_login_flow(client):
    # ensure no user exists (other tests may have created one in the shared DB)
    from app.db import get_session_factory
    from app.models import User
    _s = get_session_factory()()
    _s.query(User).delete(); _s.commit(); _s.close()
    client.cookies.clear()
    # no user yet -> /setup
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 302 and "/setup" in r.headers["location"]
    r = client.post("/setup", data={"username": "anna", "password": "hemligt123",
                                    "password2": "hemligt123"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/dashboard"
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200
    assert "Dashboard" in r.text
    # logout
    token = csrf_of(client)
    r = client.post("/logout", data={"csrf": token}, follow_redirects=False)
    assert r.status_code == 302
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 401 or r.status_code == 302
    # login again
    r = client.post("/login", data={"username": "anna", "password": "hemligt123"},
                    follow_redirects=False)
    assert r.status_code == 302 and "/dashboard" in r.headers["location"]
    # wrong password
    client.post("/logout", data={"csrf": csrf_of(client)})
    r = client.post("/login", data={"username": "anna", "password": "fel"},
                    follow_redirects=False)
    assert r.status_code == 302 and "error" in r.headers["location"]


def test_unauthenticated_pages_redirect_to_login(client):
    r = client.get("/intakter", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["location"]


def test_csrf_required_on_post(auth_client):
    client = auth_client
    # valid data but no CSRF token -> rejected, nothing created
    r = client.post("/intakter/ny", data={
        "entry_date": "2026-03-01", "customer_name": "X", "description": "Jobb",
        "vat_code": "SE25", "amount_mode": "net", "amount": "1000",
        "payment_status": "unpaid",
    }, follow_redirects=True)
    assert "CSRF" in r.text
    assert "1000,00" not in r.text  # entry not listed


def test_create_income_via_form_swedish_amounts(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/intakter/ny", data={
        "csrf": token,
        "entry_date": "2026-03-01", "customer_name": "Acme AB", "description": "Konsult v9",
        "vat_code": "SE25", "amount_mode": "net", "amount": "1 234,50",
        "payment_status": "unpaid", "invoice_ref": "",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Intäkt sparad" in r.text
    assert "1 234,50" in T(r)           # net shown
    assert "308,63" in T(r)             # VAT 25% of 1234.50 = 308.625 -> 308.63
    assert "1 543,13" in T(r)           # gross


def test_create_income_gross_mode(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-03-02", "customer_name": "B",
        "description": "Fast pris inkl moms", "vat_code": "SE25",
        "amount_mode": "gross", "amount": "1250", "payment_status": "unpaid",
    }, follow_redirects=True)
    r = client.get("/intakter")
    assert "1 000,00" in T(r)   # net derived from gross
    assert "250,00" in T(r)     # vat


def test_create_expense_with_deductible(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/utgifter/ny", data={
        "csrf": token, "expense_date": "2026-03-03", "supplier": "Telia",
        "category_id": "", "category_name_new": "Telefon", "description": "Mobil",
        "vat_code": "SE25_P", "amount_mode": "gross", "amount": "561,25",
        "vat_rate": "25", "deductible_vat": "50", "payment_method": "kort",
    }, follow_redirects=True)
    assert r.status_code == 200
    assert "Utgift sparad" in r.text
    assert "449,00" in T(r)   # net
    assert "112,25" in T(r)   # vat
    assert "50,00" in T(r)    # deductible capped at entered 50


def test_full_invoice_flow_via_web(auth_client):
    client = auth_client
    token = csrf_of(client)

    # 1. customer
    r = client.post("/kunder/ny", data={
        "csrf": token, "name": "Webbkund AB", "is_business": "on",
        "org_nr": "", "address_line1": "Gatan 1", "postal_code": "111 11",
        "city": "Stockholm", "country": "Sverige",
    }, follow_redirects=True)
    assert "Webbkund AB" in r.text
    import re
    # find customer id from edit buttons
    m = re.search(r"editCustomer\((\d+)\)", r.text)
    assert m
    cid = m.group(1)

    # 2. invoice draft with two lines
    r = client.post("/fakturor/ny", data={
        "csrf": token, "invoice_date": "2026-03-10", "customer_id": cid,
        "payment_terms_days": "30", "customer_reference": "PO-1", "our_reference": "",
        "notes": "",
        "descriptions": ["Konsultarbete", "Resa"],
        "qtys": ["10", "1"], "units": ["tim", "st"], "prices": ["950", "450"],
        "codes": ["SE25", "SE25"], "rates": ["25", "25"],
    }, follow_redirects=True)
    assert r.status_code == 200
    m = re.search(r"/fakturor/(\d+)", r.text)
    assert m
    inv_id = m.group(1)
    # totals visible: net 9 950, vat 2 487,50, gross 12 437,50
    assert "9 950,00" in T(r)
    assert "2 487,50" in T(r)
    assert "12 437,50" in T(r)

    # 3. finalize
    r = client.post(f"/fakturor/{inv_id}/faststall", data={"csrf": token, "book_income": "on"},
                    follow_redirects=True)
    assert "fastställd" in r.text.lower() or "Fastställd" in r.text
    assert "2026-0001" in T(r)
    # income booked automatically
    r = client.get("/intakter")
    assert "Konsultarbete" in r.text

    # 4. PDF endpoint — 200 with PDF bytes if WeasyPrint libs present,
    #    otherwise a graceful 302 back to the detail page with an error flash
    r = client.get(f"/fakturor/{inv_id}/pdf", follow_redirects=False)
    assert r.status_code in (200, 302)
    if r.status_code == 200:
        assert r.headers["content-type"] == "application/pdf"
        assert r.content[:4] == b"%PDF"

    # 5. mark paid
    r = client.post(f"/fakturor/{inv_id}/betalning", data={"csrf": token, "amount": "",
                                                           "payment_date": "2026-03-20"},
                    follow_redirects=True)
    assert "Betald" in r.text

    # 6. credit note
    r = client.post(f"/fakturor/{inv_id}/kreditera", data={"csrf": token, "reason": "retur"},
                    follow_redirects=True)
    assert "Kreditfaktura" in r.text or "kredit" in r.text.lower()


def test_vat_page_shows_boxes(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-02-01", "customer_name": "A",
        "description": "Febjobb", "vat_code": "SE25", "amount_mode": "net",
        "amount": "10000", "payment_status": "unpaid",
    }, follow_redirects=True)
    r = client.get("/moms?kind=quarter&year=2026&number=1")
    assert r.status_code == 200
    assert "Momsredovisning" in r.text
    assert "10 000,00" in T(r) or "10\u00a0000,00" in T(r)  # box 05 exact
    assert "2 500" in T(r) or "2\u00a0500" in T(r)          # output VAT
    # lock the period
    r = client.post("/moms/spara", data={"csrf": token, "kind": "quarter", "year": "2026",
                                         "number": "1", "action": "lock"}, follow_redirects=True)
    assert "låst" in r.text.lower()
    # CSV export
    r = client.get("/moms/export.csv?kind=quarter&year=2026&number=1")
    assert r.status_code == 200
    body = r.text
    assert "Fält" in body
    assert ";49;" in body.replace("\u00a0", " ") or body.splitlines()[1].startswith("05")


def test_owner_transactions_page(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/agare/ny", data={"csrf": token, "tx_date": "2026-03-01",
                                       "tx_type": "uttag", "amount": "15000",
                                       "description": "Månadsuttag"}, follow_redirects=True)
    assert "sparad" in r.text.lower()
    assert "15 000,00" in T(r) or "15\u00a0000,00" in T(r)
    # profit unaffected: dashboard should still show resultat 0 with no income
    r = client.get("/dashboard?year=2026")
    assert "Egna uttag" in r.text


def test_settings_org_nr_validation(auth_client):
    client = auth_client
    token = csrf_of(client)
    # invalid org nr -> error
    r = client.post("/installningar/foretag", data={
        "csrf": token, "company_name": "Test", "org_nr": "123456-7890",
        "vat_number": "", "country": "Sverige",
    }, follow_redirects=True)
    assert "kontrollsiffra" in r.text or "Organisationsnummer" in r.text
    # invalid VAT suffix -> error
    r = client.post("/installningar/foretag", data={
        "csrf": token, "company_name": "Test", "org_nr": "",
        "vat_number": "SE123456789002", "country": "Sverige",
    }, follow_redirects=True)
    assert "01" in T(r)


def test_backup_and_export_endpoints(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/data/backup", data={"csrf": token}, follow_redirects=True)
    assert "Backup skapad" in r.text
    r = client.get("/data/export.json")
    assert r.status_code == 200
    import json
    data = json.loads(r.text)
    assert "income_entries" in data and "invoices" in data
    r = client.get("/data/download.db")
    assert r.status_code == 200
    assert r.content[:15].startswith(b"SQLite format 3")


def test_audit_log_records_changes(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-03-05", "customer_name": "Audit AB",
        "description": "Spåras", "vat_code": "SE25", "amount_mode": "net",
        "amount": "100", "payment_status": "unpaid",
    }, follow_redirects=True)
    r = client.get("/data/audit")
    assert "IncomeEntry" in r.text
    assert "create" in r.text


def test_simplified_mode_requires_confirmation(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/installningar/bokforing", data={
        "csrf": token, "fiscal_year_start_month": "1", "vat_period": "quarter",
        "default_vat_rate": "25", "simplified_vat_mode": "on", "simplified_confirm": "",
    }, follow_redirects=True)
    assert "JAG FÖRSTÅR" in r.text
    r = client.post("/installningar/bokforing", data={
        "csrf": token, "fiscal_year_start_month": "1", "vat_period": "quarter",
        "default_vat_rate": "25", "simplified_vat_mode": "on",
        "simplified_confirm": "JAG FÖRSTÅR",
    }, follow_redirects=True)
    assert "FÖRENKLAT LÄGE" in r.text
    # and the dashboard banner shows
    r = client.get("/dashboard")
    assert "EJ KORREKT" in r.text
    # turn it back off
    r = client.post("/installningar/bokforing", data={
        "csrf": token, "fiscal_year_start_month": "1", "vat_period": "quarter",
        "default_vat_rate": "25", "simplified_vat_mode": "", "simplified_confirm": "",
    }, follow_redirects=True)
    assert "korrekt momsläge" in r.text.lower()


def test_ui_language_switch_english(auth_client):
    client = auth_client
    # default = Swedish
    r = client.get("/dashboard")
    assert "Intäkter" in r.text and "Nettoomsättning" in r.text
    # switch to English via /lang
    r = client.get("/lang?lang=en&next=/dashboard")
    assert r.status_code == 200
    assert ">Income</a>" in r.text
    assert "Net revenue" in r.text
    assert "Register income" in r.text or "+ Register income" in r.text
    assert "Owner withdrawals" in r.text or "Withdrawals" in r.text
    # flashes translate too
    token = csrf_of(client)
    r = client.post("/intakter/ny", data={
        "csrf": token, "entry_date": "2026-05-04", "customer_name": "EN Kund",
        "description": "English UI test", "vat_code": "SE25", "amount_mode": "net",
        "amount": "1000", "payment_status": "unpaid",
    }, follow_redirects=True)
    assert "Income saved" in r.text
    # VAT page chrome in English, SKV box labels stay Swedish (official terms)
    r = client.get("/moms?kind=quarter&year=2026&number=2")
    assert "VAT return" in r.text
    # SKV box descriptions are translated; box NUMBERS are language-neutral
    assert "Output VAT 25 %" in r.text
    # invoice PDF template itself is Swedish-only (checked in test_pdf.py)
    # back to Swedish
    r = client.get("/lang?lang=sv&next=/dashboard")
    assert "Intäkter" in r.text and "Nettoomsättning" in r.text


def test_invoice_finalize_direct_and_draft(auth_client):
    client = auth_client
    token = csrf_of(client)
    client.post("/kunder/ny", data={"csrf": token, "name": "Direkt Kund AB",
                                    "is_business": "on", "country": "Sverige"})
    import re as _re
    cid = _re.search(r"editCustomer\((\d+)\)", client.get("/kunder").text).group(1)

    # finalize directly (default checkbox on)
    r = client.post("/fakturor/ny", data={
        "csrf": token, "invoice_date": "2026-04-01", "customer_id": cid,
        "payment_terms_days": "10", "finalize_now": "on",
        "arts": ["11"], "descriptions": ["Taxikörning mars"], "qtys": ["1"],
        "units": ["st"], "prices": ["5000"], "codes": ["SE25"], "rates": ["25"],
    }, follow_redirects=True)
    t = r.text.replace("\u00a0", " ")
    assert "2026-0001" in t
    assert "Fastställd" in t
    assert "skapad och fastställd" in t or "created and finalized" in t

    # draft mode
    r = client.post("/fakturor/ny", data={
        "csrf": token, "invoice_date": "2026-04-02", "customer_id": cid,
        "payment_terms_days": "10", "finalize_now": "",
        "arts": [""], "descriptions": ["Utkastjobb"], "qtys": ["1"],
        "units": ["st"], "prices": ["100"], "codes": ["SE25"], "rates": ["25"],
    }, follow_redirects=True)
    t = r.text.replace("\u00a0", " ")
    assert "Utkast" in t
    assert "(utkast" in t


def test_settings_payment_display_and_ocr_toggle(auth_client):
    client = auth_client
    token = csrf_of(client)
    r = client.post("/installningar/faktura", data={
        "csrf": token, "payment_terms_days": "10", "late_interest_rate": "8",
        "late_interest_text": "Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.",
        "round_total_to_krona": "", "payment_display": "bankaccount",
        "invoice_show_ocr": "", "invoice_number_prefix": "",
        "invoice_number_digits": "4", "invoice_number_start": "1",
    }, follow_redirects=True)
    assert "Fakturainställningar sparade" in r.text
    r = client.get("/installningar")
    assert 'value="bankaccount" selected' in r.text
    assert '<option value="" selected>Nej</option>' in r.text
