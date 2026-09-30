"""Bokslutsmetoden (kontantmetoden) — the user's registered VAT method.

Utgående moms redovisas när kunden BETALAT; obetalda poster redovisas
senast i räkenskapsårets sista period. Ingående moms: förenklingsregeln
(avdrag vid bokföring) som standard, eller per betalningsdatum.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app import vat as vatmod
from app.money import q2, vat_amount
from app.swedish import filing_due
from app.vat import compute_declaration

Q1 = (date(2026, 1, 1), date(2026, 3, 31))
Q4 = (date(2026, 10, 1), date(2026, 12, 31))
Q1_27 = (date(2027, 1, 1), date(2027, 3, 31))


def inc(net="1000", entry=date(2026, 2, 10), status="unpaid", payment_date=None, id=1):
    n = q2(net)
    v = vat_amount(n, 25)
    return SimpleNamespace(id=id, entry_date=entry, vat_code="SE25", net_amount=n,
                           vat_rate=q2(25), vat_amount=v, payment_status=status,
                           payment_date=payment_date)


def exp(gross="1250", d=date(2026, 2, 20), payment_date=None, id=1):
    n = q2("1000.00")
    v = q2("250.00")
    return SimpleNamespace(id=id, expense_date=d, vat_code="SE25_P", net_amount=n,
                           vat_rate=q2(25), vat_amount=v, deductible_vat=v,
                           payment_date=payment_date)


def test_fakturametoden_uses_entry_date():
    d = compute_declaration([inc()], [], *Q1, method="faktura")
    assert d.output_vat == Decimal("250.00")
    d2 = compute_declaration([inc()], [], *Q4, method="faktura")
    assert d2.output_vat == Decimal("0.00")


def test_bokslut_unpaid_not_in_entry_period():
    """Unpaid February sale must NOT appear in Q1 under bokslutsmetoden."""
    d = compute_declaration([inc()], [], *Q1, method="bokslut")
    assert d.output_vat == Decimal("0.00")
    assert d.boxes["05"] == Decimal("0.00")


def test_bokslut_unpaid_swept_to_year_end():
    """Unpaid sales are reported in the fiscal year's LAST period."""
    d = compute_declaration([inc()], [], *Q4, method="bokslut")
    assert d.output_vat == Decimal("250.00")
    assert d.boxes["05"] == Decimal("1000.00")


def test_bokslut_paid_uses_payment_date():
    """December sale paid in January → reported in Q1 of the NEXT year."""
    e = inc(entry=date(2026, 12, 20), status="paid", payment_date=date(2027, 1, 10))
    d_q4_26 = compute_declaration([e], [], *Q4, method="bokslut")
    assert d_q4_26.output_vat == Decimal("0.00")
    d_q1_27 = compute_declaration([e], [], *Q1_27, method="bokslut")
    assert d_q1_27.output_vat == Decimal("250.00")


def test_bokslut_partial_payment_warns():
    e = inc(status="partial", payment_date=date(2026, 3, 1))
    d = compute_declaration([e], [], *Q1, method="bokslut")
    assert d.output_vat == Decimal("250.00")
    assert any("delbetald" in w for w in d.warnings)


def test_bokslut_paid_without_payment_date_falls_back_and_warns():
    e = inc(status="paid", payment_date=None)
    d = compute_declaration([e], [], *Q1, method="bokslut")
    assert d.output_vat == Decimal("250.00")   # falls back to entry date
    assert any("betalningsdatum" in w for w in d.warnings)


def test_input_vat_default_deducted_at_booking():
    x = exp(d=date(2026, 2, 20), payment_date=None)
    d = compute_declaration([], [x], *Q1, method="bokslut", input_vat_on_payment=False)
    assert d.input_vat == Decimal("250.00")


def test_input_vat_on_payment_uses_payment_date():
    x = exp(d=date(2026, 2, 20), payment_date=date(2026, 4, 5))
    d_q1 = compute_declaration([], [x], *Q1, method="bokslut", input_vat_on_payment=True)
    assert d_q1.input_vat == Decimal("0.00")
    d_q2 = compute_declaration([], [x], date(2026, 4, 1), date(2026, 6, 30),
                               method="bokslut", input_vat_on_payment=True)
    assert d_q2.input_vat == Decimal("250.00")


def test_input_vat_on_payment_missing_date_warns():
    x = exp(payment_date=None)
    d = compute_declaration([], [x], *Q1, method="bokslut", input_vat_on_payment=True)
    assert d.input_vat == Decimal("250.00")  # fallback to booking date
    assert any("betalningsdatum" in w for w in d.warnings)


def test_filing_due_12th_of_second_month_after_period():
    # Q1 ends 2026-03-31 → due 2026-05-12 (per registerutdraget)
    assert filing_due(date(2026, 3, 31)) == date(2026, 5, 12)
    # Q2 ends 2026-06-30 → due 2026-08-12
    assert filing_due(date(2026, 6, 30)) == date(2026, 8, 12)
    # Year ends 2026-12-31 → due 2027-02-12
    assert filing_due(date(2026, 12, 31)) == date(2027, 2, 12)
    # Month ends 2026-11-30 → due 2027-01-12
    assert filing_due(date(2026, 11, 30)) == date(2027, 1, 12)
