"""Dev/CI helper: offscreen screenshots of the desktop UI.

    python3 scripts/screenshots.py [outdir]

Renders the main window at 800x600, 1280x800 and 1920x1080 in Swedish and
English (dashboard + income + invoices pages) and a sample Swedish invoice
PDF. Requires PySide6 (offscreen) and, for the PDF, WeasyPrint native libs.
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("preview/desktop")
OUT.mkdir(parents=True, exist_ok=True)

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TMP = Path(tempfile.mkdtemp(prefix="firmabok-shot-"))
os.environ["FIRMABOK_CONFIG_DIR"] = str(TMP / "c")
os.environ["FIRMABOK_DATA_DIR"] = str(TMP / "d")
os.environ["FIRMABOK_STATE_DIR"] = str(TMP / "s")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from firmabok.core import config  # noqa: E402
from firmabok.core.db import get_session_factory  # noqa: E402
from firmabok.core.invoices import finalize_invoice, get_profile  # noqa: E402
from firmabok.core.migrate import run_migrations, seed_reference_data  # noqa: E402
from firmabok.core.models import Customer, InvoiceLine  # noqa: E402
from firmabok.core.models import Invoice  # noqa: E402
from firmabok.i18n import i18n  # noqa: E402
from firmabok.ui import theme  # noqa: E402
from firmabok.ui.app import MainWindow  # noqa: E402

config.reset_for_tests(TMP / "c", TMP / "d", TMP / "s")
config.ensure_dirs()
run_migrations()
db = get_session_factory()()
seed_reference_data(db)

# demo profile + one finalized invoice for realistic screenshots + PDF
p = get_profile(db)
p.company_name = "Saddam Hussain"
p.org_nr = "830116-0571"
p.vat_number = "SE830116057101"
p.f_skatt_registered = True
p.address_line1 = "Friherregatan 48 lgh 1102"
p.postal_code = "165 58"
p.city = "Hässelby"
p.bankgiro = ""
p.payment_terms_days = 10
c = Customer(name="Shangla Tech Solutions AB", customer_no="22",
             address_line1="MUSKÖTSTIGEN 5 LGH 1603", postal_code="19252",
             city="SOLLENTUNA", is_business=True)
db.add(c)
db.flush()
inv = Invoice(status="draft", invoice_date=date(2026, 7, 20), customer_id=c.id,
              payment_terms_days=10)
db.add(inv)
db.flush()
db.add(InvoiceLine(invoice_id=inv.id, position=0, article_no="11",
                   description="TaxiService-körning Juni-2026",
                   quantity=Decimal("1.000"), unit="st",
                   unit_price=Decimal("46900.00"), vat_code="SE25",
                   vat_rate=Decimal("25")))
db.flush()
finalize_invoice(db, inv, username="screenshot", book_income=True)
db.commit()

app = QApplication(sys.argv[:1])
theme.apply(app)
st = config.settings()
st.set("wizard_completed", True)
st.save()

win = MainWindow()
win.show_content()

for lang in ("sv", "en"):
    i18n.set_language(lang)
    for page_id in ("dashboard", "income", "invoices"):
        win.go_page(page_id)
        for w, h in ((800, 600), (1280, 800), (1920, 1080)):
            win.resize(w, h)
            app.processEvents()
            pix = win.grab()
            name = OUT / f"{page_id}_{lang}_{w}x{h}.png"
            pix.save(str(name))
            print("saved", name.name, pix.size())

# sample invoice PDF (must stay Swedish under EN too)
i18n.set_language("en")
from firmabok.core import pdf as core_pdf  # noqa: E402

data = core_pdf.render_invoice_pdf(db, inv.id)
(OUT / "faktura_sample_en_session.pdf").write_bytes(data)
print("pdf bytes:", len(data))
db.close()
print("done")
