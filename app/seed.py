"""Sample/demo data seeder.

    python -m app.seed            # seed demo data into the current DB
    python -m app.seed --fresh    # also reset the demo flag

Creates a realistic small consulting business: monthly + weekly income,
expenses across categories (incl. non-deductible and reverse-charge
examples), owner transactions, and one finalized invoice + credit note.
Company details are PLACEHOLDERS — replace them in Inställningar.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from . import vat as vatmod
from .db import get_session_factory
from .invoices import create_credit_note, finalize_invoice, get_profile, recalc_invoice
from .main import run_migrations, seed_reference_data
from .models import (
    Customer, Expense, IncomeEntry, Invoice, InvoiceLine, OwnerTransaction,
    PaymentStatus,
)
from .money import gross_from_net, net_from_gross, q2, vat_amount


PLACEHOLDER_COMPANY = {
    "company_name": "EXEMPEL Konsult (placeholder — ändra i Inställningar)",
    "org_nr": "",          # set yours in Settings; validated there
    "vat_number": "",
    "f_skatt_registered": False,
    "address_line1": "Exempelgatan 1",
    "postal_code": "111 22",
    "city": "Stockholm",
    "phone": "070-000 00 00",
    "email": "hej@exempel.se",
    "payment_terms_days": 30,
    "invoice_notes": "Tack för uppdraget! Betalas senast på förfallodatum.",
}


def seed_demo(db) -> None:
    profile = get_profile(db)
    for k, v in PLACEHOLDER_COMPANY.items():
        if not getattr(profile, k):
            setattr(profile, k, v)

    today = date.today()
    year = today.year

    # --- Customers ---------------------------------------------------------
    customers = []
    for name, org, city in [
        ("Nordtech AB", "556000-1234", "Stockholm"),
        ("Grön Energi Handelsbolag", "969000-5678", "Uppsala"),
        ("Lisa Lundström (privat)", "", "Solna"),
    ]:
        c = db.execute(select(Customer).where(Customer.name == name)).scalar_one_or_none()
        if c is None:
            c = Customer(name=name, org_nr=org, city=city, is_business=bool(org),
                         address_line1="Kundgatan 2", postal_code="123 45",
                         reference="Ekonomiavdelningen" if org else "")
            db.add(c)
        customers.append(c)
    db.flush()

    # --- Income: weekly consulting + monthly retainers ----------------------
    def add_income(d, cust, desc, net, code="SE25", status=PaymentStatus.PAID.value, ref=""):
        rate = vatmod.default_rate_for(code)
        e = db.execute(select(IncomeEntry).where(
            IncomeEntry.entry_date == d, IncomeEntry.description == desc)).scalar_one_or_none()
        if e is not None:
            return e
        e = IncomeEntry(entry_date=d, customer_id=cust.id if cust else None,
                        customer_name=cust.name if cust else "", description=desc,
                        vat_code=code, net_amount=q2(net), vat_rate=rate,
                        vat_amount=vat_amount(net, rate), gross_amount=gross_from_net(net, rate),
                        payment_status=status, invoice_ref=ref)
        db.add(e)
        return e

    # monthly retainer (12% for some food-sector work to show mixed rates)
    for m in range(1, min(today.month, 12) + 1):
        d = date(year, m, min(28, 1 + (m * 3)))
        add_income(d, customers[0], f"Månadsarvode konsulttjänster {m:02d}", Decimal("24000.00"))
        if m % 2 == 0:
            add_income(d + timedelta(days=2), customers[1],
                       f"Projektarbete vecka {d.isocalendar()[1]}", Decimal("8500.00"))
    add_income(date(year, min(today.month, 12), 15), customers[2],
               "Hemsida (privatkund)", Decimal("6000.00"), status=PaymentStatus.UNPAID.value)

    # --- Expenses -----------------------------------------------------------
    def add_expense(d, supplier, cat, desc, gross, code="SE25_P", deductible=None):
        x = db.execute(select(Expense).where(
            Expense.expense_date == d, Expense.description == desc)).scalar_one_or_none()
        if x is not None:
            return x
        rate = vatmod.default_rate_for(code)
        net = net_from_gross(gross, rate)
        vat = q2(gross - net)
        x = Expense(expense_date=d, supplier=supplier, category_name=cat, description=desc,
                    vat_code=code, net_amount=net, vat_rate=rate, vat_amount=vat,
                    gross_amount=q2(gross),
                    deductible_vat=vat if deductible is None else q2(min(deductible, vat)))
        db.add(x)
        return x

    add_expense(date(year, min(today.month, 12), 3), "Telia", "Telefon & internet",
                "Mobilabonnemang företag", Decimal("561.25"))
    add_expense(date(year, min(today.month, 12), 8), "Staples", "Kontor & administration",
                "Kontorsmaterial", Decimal("1237.50"))
    add_expense(date(year, min(today.month, 12), 12), "Adobe", "IT & programvara",
                "Creative Cloud årslicens", Decimal("7499.00"))
    add_expense(date(year, min(today.month, 12), 20), "Restaurang Operakällaren", "Representation",
                "Kundmiddag Nordtech (2 pers)", Decimal("2450.00"),
                deductible=Decimal("150.00"))  # begränsad avdragsrätt representation
    add_expense(date(year, min(today.month, 12), 22), "Google Ireland Ltd", "IT & programvara",
                "Google Workspace (EU-tjänst, omvänd skattskyldighet)", Decimal("1200.00"),
                code="EU_SERVICES_ACQ")
    add_expense(date(year, min(today.month, 12), 25), "Systembolaget", "Representation",
                "Present till kund — ej avdragsgill moms", Decimal("500.00"),
                code="NON_DEDUCTIBLE_P", deductible=Decimal("0"))

    # --- Owner transactions --------------------------------------------------
    for m in range(1, min(today.month, 12) + 1):
        d = date(year, m, 27)
        exists = db.execute(select(OwnerTransaction).where(
            OwnerTransaction.tx_date == d, OwnerTransaction.tx_type == "uttag")).scalar_one_or_none()
        if exists is None:
            db.add(OwnerTransaction(tx_date=d, tx_type="uttag", amount=Decimal("15000.00"),
                                    description=f"Månadsuttag {m:02d}", reference="privatkonto"))

    # --- One finalized invoice + one credit note ------------------------------
    inv_exists = db.execute(select(Invoice).where(Invoice.status != "draft")).scalars().first()
    if inv_exists is None:
        inv = Invoice(status="draft", invoice_date=today - timedelta(days=20),
                      customer_id=customers[0].id, payment_terms_days=profile.payment_terms_days,
                      our_reference="EX", customer_reference="PO-1001",
                      notes=profile.invoice_notes)
        db.add(inv)
        db.flush()
        db.add(InvoiceLine(invoice_id=inv.id, position=0,
                           description="Konsulttjänster enligt avtal (16 h à 950 kr)",
                           quantity=Decimal("16"), unit="tim", unit_price=Decimal("950.00"),
                           vat_code="SE25", vat_rate=Decimal("25")))
        db.add(InvoiceLine(invoice_id=inv.id, position=1,
                           description="Resekostnader (mileage)",
                           quantity=Decimal("1"), unit="st", unit_price=Decimal("450.00"),
                           vat_code="SE25", vat_rate=Decimal("25")))
        db.flush()
        recalc_invoice(inv)
        finalize_invoice(db, inv, username="seed")
        # credit a small part via full credit note example (draft left for demo)
        create_credit_note(db, inv, username="seed", reason="Demonstration av kreditfaktura")
        # remove the demo credit note draft again to keep the sample clean:
        for cn in db.execute(select(Invoice).where(Invoice.is_credit_note == True,  # noqa: E712
                                                   Invoice.status == "draft")).scalars().all():
            db.delete(cn)

    db.commit()
    print("Demo-data skapad (placeholder-företag). Ändra företagsuppgifter under Inställningar.")


def main(argv):
    run_migrations()
    db = get_session_factory()()
    try:
        seed_reference_data(db)
        seed_demo(db)
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
