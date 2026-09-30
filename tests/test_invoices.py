"""Invoice totals, per-line rounding, gapless numbering, credit notes, OCR."""
from datetime import date
from decimal import Decimal

import pytest

from app.invoices import (
    InvoiceError, book_invoice_income, create_credit_note, delete_draft,
    finalize_invoice, format_number, get_series, peek_next_number, recalc_invoice,
)
from app.models import IncomeEntry, Invoice, InvoiceStatus
from app.swedish import luhn_ok
from conftest import make_invoice


def test_line_totals_and_per_line_rounding(db, customer):
    inv = make_invoice(db, customer, [
        ("Rad 1", "3", "33.33", "SE25"),      # net 99.99, vat 25.00 (24.9975 half-up)
        ("Rad 2", "1", "0.02", "SE25"),       # net 0.02, vat 0.01 (0.005 half-up)
        ("Rad 3", "2.5", "10.01", "SE6"),     # net 25.03 (25.025 half-up), vat 1.50
    ], invoice_date=date(2026, 3, 1))
    lines = {l.description: l for l in inv.lines}
    assert lines["Rad 1"].line_net == Decimal("99.99")
    assert lines["Rad 1"].line_vat == Decimal("25.00")
    assert lines["Rad 1"].line_gross == Decimal("124.99")
    assert lines["Rad 2"].line_vat == Decimal("0.01")
    assert lines["Rad 3"].line_net == Decimal("25.03")
    assert lines["Rad 3"].line_vat == Decimal("1.50")
    # totals = sum of lines, and net + vat = gross exactly
    assert inv.net_total == Decimal("125.04")
    assert inv.vat_total == Decimal("26.51")
    assert inv.gross_total == inv.net_total + inv.vat_total == Decimal("151.55")


def test_reverse_charge_line_has_no_vat(db, customer):
    inv = make_invoice(db, customer, [("Byggtjänst RC", "1", "10000", "SE_REVERSE_SALE")])
    assert inv.vat_total == Decimal("0.00")
    assert inv.gross_total == Decimal("10000.00")
    finalize_invoice(db, inv, username="test", book_income=True)
    db.commit()
    e = inv.income_entries[0]
    assert e.vat_amount == Decimal("0.00")
    assert e.vat_code == "SE_REVERSE_SALE"


def test_sequential_numbering_per_year_series(db, customer, profile):
    profile.invoice_number_start = 1
    inv1 = make_invoice(db, customer, [("A", "1", "100", "SE25")], invoice_date=date(2026, 1, 10))
    inv2 = make_invoice(db, customer, [("B", "1", "100", "SE25")], invoice_date=date(2026, 2, 10))
    assert peek_next_number(db, 2026) == "2026-0001"
    finalize_invoice(db, inv1, username="t")
    db.commit()
    assert inv1.number == "2026-0001"
    finalize_invoice(db, inv2, username="t")
    db.commit()
    assert inv2.number == "2026-0002"
    assert inv1.due_date == date(2026, 2, 9)  # 30 days terms


def test_numbering_start_and_prefix_configurable(db, customer, profile):
    profile.invoice_number_start = 42
    profile.invoice_number_prefix = "A"
    inv = make_invoice(db, customer, [("A", "1", "100", "SE25")], invoice_date=date(2027, 1, 5))
    finalize_invoice(db, inv, username="t")
    db.commit()
    assert inv.number == "A2027-0042"


def test_separate_series_per_fiscal_year(db, customer):
    i26 = make_invoice(db, customer, [("A", "1", "100", "SE25")], invoice_date=date(2026, 6, 1))
    i27 = make_invoice(db, customer, [("B", "1", "100", "SE25")], invoice_date=date(2027, 1, 4))
    finalize_invoice(db, i26, username="t")
    finalize_invoice(db, i27, username="t")
    db.commit()
    assert i26.number == "2026-0001"
    assert i27.number == "2027-0001"


def test_draft_deletion_does_not_consume_numbers(db, customer):
    draft = make_invoice(db, customer, [("A", "1", "100", "SE25")])
    assert draft.number is None
    delete_draft(db, draft)
    db.commit()
    real = make_invoice(db, customer, [("B", "1", "100", "SE25")])
    finalize_invoice(db, real, username="t")
    db.commit()
    assert real.number == "2026-0001"  # gapless: no number wasted on the draft


def test_finalized_invoice_cannot_be_deleted_or_refinalized(db, customer):
    inv = make_invoice(db, customer, [("A", "1", "100", "SE25")])
    finalize_invoice(db, inv, username="t")
    db.commit()
    with pytest.raises(InvoiceError):
        delete_draft(db, inv)
    with pytest.raises(InvoiceError):
        finalize_invoice(db, inv, username="t")


def test_finalize_requires_customer_and_lines(db, customer):
    empty = Invoice(status="draft", invoice_date=date(2026, 3, 1))
    db.add(empty)
    db.commit()
    with pytest.raises(InvoiceError):
        finalize_invoice(db, empty, username="t")
    db.rollback()


def test_ocr_is_luhn_valid(db, customer):
    inv = make_invoice(db, customer, [("A", "1", "100", "SE25")])
    finalize_invoice(db, inv, username="t")
    db.commit()
    assert inv.ocr.startswith("20260001")
    assert luhn_ok(inv.ocr)


def test_credit_note_negates_and_credits_original(db, customer):
    inv = make_invoice(db, customer, [("Konsult", "2", "5000", "SE25")],
                       invoice_date=date(2026, 3, 1))
    finalize_invoice(db, inv, username="t")
    db.commit()
    assert inv.gross_total == Decimal("12500.00")

    credit = create_credit_note(db, inv, username="t", reason="Felaktigt belopp")
    db.commit()
    assert credit.is_credit_note
    assert credit.net_total == Decimal("-10000.00")
    assert credit.vat_total == Decimal("-2500.00")
    finalize_invoice(db, credit, username="t")
    db.commit()
    assert credit.number == "2026-0002"          # credit note gets its own number
    assert inv.status == InvoiceStatus.CREDITED.value
    # credit note books a negative income entry → VAT report nets out
    assert len(credit.income_entries) == 1
    assert credit.income_entries[0].net_amount == Decimal("-10000.00")
    with pytest.raises(InvoiceError):
        create_credit_note(db, credit, username="t")  # cannot credit a credit note


def test_booking_income_from_invoice_happens_once(db, customer):
    inv = make_invoice(db, customer, [("A", "1", "1000", "SE25"), ("B", "1", "500", "SE12")])
    finalize_invoice(db, inv, username="t", book_income=True)
    db.commit()
    assert len(inv.income_entries) == 2
    entries = db.query(IncomeEntry).filter_by(invoice_id=inv.id).all()
    assert len(entries) == 2
    # calling again must not duplicate
    book_invoice_income(db, inv)
    db.commit()
    assert db.query(IncomeEntry).filter_by(invoice_id=inv.id).count() == 2
    total_net = sum(e.net_amount for e in inv.income_entries)
    total_vat = sum(e.vat_amount for e in inv.income_entries)
    assert total_net == Decimal("1500.00")
    assert total_vat == Decimal("310.00")  # 250 + 60


def test_finalize_without_booking_income(db, customer):
    inv = make_invoice(db, customer, [("A", "1", "1000", "SE25")])
    finalize_invoice(db, inv, username="t", book_income=False)
    db.commit()
    assert len(inv.income_entries) == 0
    assert db.query(IncomeEntry).filter_by(invoice_id=inv.id).count() == 0


def test_rounding_to_whole_kronor(db, customer, profile):
    """Avrundning-raden: totalsumman öres-justeras till hela kronor."""
    profile.round_total_to_krona = True
    db.commit()
    # net 80.39 → vat 20.10 (20.0975 half-up) → gross 100.49 → avrundning −0.49 → att betala 100.00
    inv = make_invoice(db, customer, [("Öresutjämningsrad", "1", "80.39", "SE25")])
    from app.invoices import recalc_invoice
    recalc_invoice(inv, round_to_krona=True)
    db.commit()
    assert inv.gross_total == Decimal("100.49")
    assert inv.rounding_amount == Decimal("-0.49")
    assert inv.amount_to_pay == Decimal("100.00")
    # round-up case: 100.50 → 101
    inv2 = make_invoice(db, customer, [("Rad", "1", "80.40", "SE25")])
    recalc_invoice(inv2, round_to_krona=True)
    db.commit()
    assert inv2.gross_total == Decimal("100.50")
    assert inv2.rounding_amount == Decimal("0.50")
    assert inv2.amount_to_pay == Decimal("101.00")


def test_no_rounding_by_default(db, customer):
    inv = make_invoice(db, customer, [("Rad", "1", "80.39", "SE25")])
    assert inv.rounding_amount == Decimal("0.00")
    assert inv.amount_to_pay == Decimal("100.49")


def test_article_no_and_delivery_date(db, customer):
    from app.models import InvoiceLine
    inv = make_invoice(db, customer, [("Taxikörning juni", "1", "46900", "SE25")],
                       invoice_date=date(2026, 7, 20))
    inv.lines[0].article_no = "11"
    db.commit()
    finalize_invoice(db, inv, username="t")
    db.commit()
    assert inv.lines[0].article_no == "11"
    # delivery date defaults to invoice date on finalize
    assert inv.delivery_date == date(2026, 7, 20)
    assert inv.due_date == date(2026, 8, 19)  # default 30 days
