"""Exact money math: Decimal only, half-up rounding, Swedish formatting."""
from decimal import Decimal

from app.money import (
    format_int, format_qty, format_sek, gross_from_net, line_net, net_from_gross,
    q2, round_kronor, sum_money, vat_amount, vat_from_gross,
)


def test_all_values_are_decimal():
    assert isinstance(q2("1.005"), Decimal)
    assert isinstance(vat_amount(100, 25), Decimal)
    assert isinstance(gross_from_net("99.99", "12"), Decimal)
    assert isinstance(net_from_gross("1250", 25), Decimal)


def test_half_up_rounding_to_ore():
    assert q2("1.005") == Decimal("1.01")   # half-up, not banker's rounding
    assert q2("1.004") == Decimal("1.00")
    assert q2("-1.005") == Decimal("-1.01")
    assert vat_amount("0.02", 25) == Decimal("0.01")      # 0.005 -> 0.01
    assert vat_amount("33.33", 25) == Decimal("8.33")     # 8.3325 -> 8.33
    assert vat_amount("10.00", 12) == Decimal("1.20")
    assert vat_amount("10.00", 6) == Decimal("0.60")


def test_vat_gross_net_roundtrip():
    assert gross_from_net("1000.00", 25) == Decimal("1250.00")
    assert net_from_gross("1250.00", 25) == Decimal("1000.00")
    assert gross_from_net("0.01", 25) == Decimal("0.01")
    assert vat_from_gross("1250.00", 25) == Decimal("250.00")
    # awkward amounts keep exactness to the öre
    for net in ("0.03", "17.47", "999.99", "123456.78"):
        g = gross_from_net(net, 25)
        assert net_from_gross(g, 25) == q2(net)


def test_line_net_quantity_times_price():
    assert line_net("3", "33.33") == Decimal("99.99")
    assert line_net("2.5", "10.01") == Decimal("25.03")   # 25.025 -> half-up


def test_round_kronor_half_up():
    assert round_kronor("0.50") == 1
    assert round_kronor("0.49") == 0
    assert round_kronor("-0.50") == -1
    assert round_kronor("1234.56") == 1235


def test_swedish_formatting():
    # comma decimal separator, space (NBSP) thousands separator
    assert format_sek("1234567.5") == "1\u00a0234\u00a0567,50"
    assert format_sek("-1234.5") == "\u22121\u00a0234,50"
    assert format_sek("0.05") == "0,05"
    assert format_sek("999.99", symbol=True).endswith(" kr")
    assert format_int("1234567.4") == "1\u00a0234\u00a0567"
    assert format_qty("2.500") == "2,5"
    assert format_qty("3") == "3"


def test_sum_money_ignores_none_and_sums_exact():
    assert sum_money([Decimal("0.01"), None, "0.02", Decimal("0.03")]) == Decimal("0.06")
    assert sum_money([]) == Decimal("0.00")
