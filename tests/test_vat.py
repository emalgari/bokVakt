"""VAT correctness: output/input VAT, Skatteverket boxes, rounding.

Regression guard: VAT must be computed on taxable sales minus deductible
input VAT — NEVER as 25 % of profit.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import vat as vatmod
from app.money import q2, vat_amount
from app.vat import compute_declaration

D = date(2026, 3, 15)


def inc(net, rate=25, code="SE25", d=D, id=1):
    net = q2(net)
    rate = q2(rate)
    info = vatmod.get_code(code)
    v = vat_amount(net, rate) if info.domestic_sale_vat else q2(0)
    return SimpleNamespace(id=id, entry_date=d, vat_code=code,
                           net_amount=net, vat_rate=rate, vat_amount=v)


def exp(net, rate=25, code="SE25_P", deductible=None, d=D, id=1):
    net = q2(net)
    rate = q2(rate)
    v = vat_amount(net, rate) if rate else q2(0)
    return SimpleNamespace(id=id, expense_date=d, vat_code=code, net_amount=net,
                           vat_rate=rate, vat_amount=v,
                           deductible_vat=v if deductible is None else q2(deductible))


def decl(incomes=(), expenses=(), start=date(2026, 1, 1), end=date(2026, 12, 31)):
    return compute_declaration(list(incomes), list(expenses), start, end)


# ---------------------------------------------------------------------------
# The core rule: moms on sales, not on profit
# ---------------------------------------------------------------------------

def test_vat_is_not_25_percent_of_profit():
    """Mixed rates make a profit-based VAT differ from the correct figure."""
    incomes = [inc(10000, 25, "SE25"), inc(5000, 6, "SE6")]
    expenses = [exp(3000, 25, "SE25_P")]
    d = decl(incomes, expenses)

    # Correct: 2500 (25% of 10 000) + 300 (6% of 5 000) − 750 (input) = 2050
    assert d.output_vat == Decimal("2800.00")
    assert d.input_vat == Decimal("750.00")
    assert d.net_vat == Decimal("2050.00")
    # A naive "25 % of profit" would give 0.25 * (15 000 − 3 000) = 3 000 — WRONG
    wrong_profit_based = q2(Decimal("0.25") * (Decimal(15000) - Decimal(3000)))
    assert wrong_profit_based == Decimal("3000.00")
    assert d.net_vat != wrong_profit_based


def test_expenses_do_not_reduce_output_vat():
    incomes = [inc(10000)]
    d_no_exp = decl(incomes, [])
    d_with_exp = decl(incomes, [exp(9000)])
    assert d_with_exp.output_vat == d_no_exp.output_vat == Decimal("2500.00")
    assert d_no_exp.net_vat == Decimal("2500.00")
    assert d_with_exp.net_vat == Decimal("250.00")  # 2500 − 2250 input


def test_boxes_for_domestic_mixed_rates():
    d = decl([inc(1000, 25, "SE25", id=1), inc(2000, 12, "SE12", id=2),
              inc(3000, 6, "SE6", id=3), inc(4000, 0, "SE0", id=4)])
    assert d.boxes["05"] == Decimal("10000.00")   # all taxable sales in box 05
    assert d.boxes["10"] == Decimal("250.00")
    assert d.boxes["11"] == Decimal("240.00")
    assert d.boxes["12"] == Decimal("180.00")
    assert d.output_vat == Decimal("670.00")
    assert d.boxes_kronor["49"] == 670


def test_exempt_eu_and_reverse_charge_sales_boxes():
    d = decl([
        inc(1000, 0, "EXEMPT", id=1),
        inc(2000, 0, "EU_GOODS", id=2),
        inc(3000, 0, "EU_SERVICES", id=3),
        inc(4000, 0, "EXPORT_GOODS", id=4),
        inc(5000, 0, "SERVICES_ABROAD", id=5),
        inc(6000, 0, "SE_REVERSE_SALE", id=6),
    ])
    assert d.boxes["42"] == Decimal("1000.00")
    assert d.boxes["35"] == Decimal("2000.00")
    assert d.boxes["39"] == Decimal("3000.00")
    assert d.boxes["36"] == Decimal("4000.00")
    assert d.boxes["40"] == Decimal("5000.00")
    assert d.boxes["41"] == Decimal("6000.00")
    assert d.output_vat == Decimal("0.00")
    assert d.net_vat_kronor == 0


def test_reverse_charge_purchase_nets_to_zero():
    """EU service purchase: output (box 30) = input (box 48) → net 0."""
    d = decl([], [exp(1000, 25, "EU_SERVICES_ACQ")])
    assert d.boxes["21"] == Decimal("1000.00")
    assert d.boxes["30"] == Decimal("250.00")
    assert d.boxes["48"] == Decimal("250.00")
    assert d.net_vat == Decimal("0.00")


def test_import_boxes():
    d = decl([], [exp(500, 25, "IMPORT_P")])
    assert d.boxes["50"] == Decimal("500.00")
    assert d.boxes["60"] == Decimal("125.00")
    assert d.boxes["48"] == Decimal("125.00")
    assert d.net_vat == Decimal("0.00")


def test_domestic_rc_purchases_boxes_23_24():
    d = decl([], [exp(1000, 25, "SE_RC_GOODS_P", id=1), exp(2000, 25, "SE_RC_SERVICES_P", id=2)])
    assert d.boxes["23"] == Decimal("1000.00")
    assert d.boxes["24"] == Decimal("2000.00")
    assert d.boxes["30"] == Decimal("750.00")   # 250 + 500
    assert d.boxes["48"] == Decimal("750.00")
    assert d.net_vat_kronor == 0


def test_non_deductible_vat_not_in_box_48():
    d = decl([], [exp(625, 25, "NON_DEDUCTIBLE_P", deductible=0)])
    assert d.boxes["48"] == Decimal("0.00")
    assert d.input_vat == Decimal("0.00")


def test_partial_deduction():
    # Representation: VAT 125 kr but only 50 kr deductible
    d = decl([], [exp(625, 25, "SE25_P", deductible=50)])
    assert d.boxes["48"] == Decimal("50.00")
    assert d.input_vat == Decimal("50.00")


def test_deductible_capped_at_charged_vat_with_warning():
    d = decl([], [exp(1250, 25, "SE25_P", deductible=9999)])
    assert d.boxes["48"] == Decimal("312.50")
    assert any("avdragsgill moms" in w for w in d.warnings)


def test_period_boundaries_inclusive():
    incomes = [inc(1000, d=date(2026, 3, 31), id=1), inc(1000, d=date(2026, 4, 1), id=2)]
    d_march = decl(incomes, [], start=date(2026, 3, 1), end=date(2026, 3, 31))
    assert d_march.boxes["05"] == Decimal("1000.00")


def test_box49_uses_rounded_whole_kronor():
    """Fält 49 = sum(rounded output boxes) − rounded box 48, per SKV."""
    # output VAT exactly 0.50 → rounds up to 1 kr
    d = decl([inc("2.00", 25, "SE25")])
    assert d.boxes["10"] == Decimal("0.50")
    assert d.boxes_kronor["10"] == 1  # half-up
    assert d.net_vat_kronor == 1
    # with input VAT 0.49 → box 48 rounds to 0
    d2 = decl([inc("2.00", 25, "SE25")], [exp("1.96", 25, "SE25_P")])
    assert d2.boxes["48"] == Decimal("0.49")
    assert d2.boxes_kronor["48"] == 0
    assert d2.net_vat_kronor == 1


def test_refund_negative_box49():
    d = decl([], [exp(10000, 25, "SE25_P")])
    assert d.net_vat == Decimal("-2500.00")
    assert d.net_vat_kronor == -2500  # att få tillbaka


def test_unknown_code_rejected():
    with pytest.raises(ValueError):
        decl([inc(100, code="XX99")])


def test_sale_with_wrong_vat_warns():
    """A reverse-charge/EU sale must not carry Swedish VAT — warn if it does."""
    e = inc(1000, 25, "EU_GOODS")
    e.vat_amount = Decimal("250.00")  # user error
    d = decl([e], [])
    assert any("svensk moms" in w for w in d.warnings)
