"""Exact money arithmetic with Decimal — floats are never used for money.

Conventions
-----------
* Amounts are ``Decimal`` quantized to 2 decimals (öre), ROUND_HALF_UP.
* VAT rates are percentages stored as ``Decimal`` (e.g. ``Decimal("25")``).
* VAT is computed per line/invoice row from the net (excl. VAT) amount:
  ``vat = round(net * rate / 100)``.
* VAT is NEVER computed on profit. Moms follows sales (utgående) and
  deductible purchase VAT (ingående) only.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

Number = Decimal | int | str

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")

# Non-breaking space as thousands separator (Swedish convention).
NBSP = "\u00a0"


def to_decimal(value: Number | float | None) -> Decimal:
    """Convert input to Decimal. Floats are converted via str() to avoid
    binary representation surprises (they are only tolerated at the edges,
    e.g. HTML form input; all stored/computed values are Decimal)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(str(value))


def q2(value: Number) -> Decimal:
    """Quantize to öre (2 decimals), half-up."""
    return to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def round_kronor(value: Number) -> int:
    """Round to whole kronor, half-up.

    Mervärdesskattelagen (1994:200) 1 kap. 7 §: amounts of VAT and VAT
    bases are stated in whole kronor in the declaration ("hela krontal så
    att öretal faller bort"). Skatteverket's practice is normal rounding
    per field. The ledger itself keeps öre precision.
    """
    return int(to_decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def vat_amount(net: Number, rate_percent: Number) -> Decimal:
    """VAT on a net amount, per row, half-up to öre."""
    return q2(to_decimal(net) * to_decimal(rate_percent) / HUNDRED)


def gross_from_net(net: Number, rate_percent: Number) -> Decimal:
    return q2(to_decimal(net) + vat_amount(net, rate_percent))


def net_from_gross(gross: Number, rate_percent: Number) -> Decimal:
    """Net amount when only the gross (incl. VAT) is known."""
    rate = to_decimal(rate_percent)
    if rate == 0:
        return q2(gross)
    return q2(to_decimal(gross) / (Decimal(1) + rate / HUNDRED))


def vat_from_gross(gross: Number, rate_percent: Number) -> Decimal:
    return q2(to_decimal(gross) - net_from_gross(gross, rate_percent))


def line_net(quantity: Number, unit_price: Number) -> Decimal:
    return q2(to_decimal(quantity) * to_decimal(unit_price))


def sum_money(values) -> Decimal:
    total = ZERO
    for v in values:
        total += to_decimal(v)
    return q2(total)


def format_sek(amount: Number, symbol: bool = False, nbsp: bool = True) -> str:
    """Swedish formatting: 1234567.5 -> '1 234 567,50' (comma decimal,
    space thousands). Optionally append ' kr'."""
    d = q2(amount)
    negative = d < 0
    d = abs(d)
    ints, _, dec = f"{d:.2f}".partition(".")
    sep = NBSP if nbsp else " "
    grouped = ""
    while len(ints) > 3:
        grouped = sep + ints[-3:] + grouped
        ints = ints[:-3]
    grouped = ints + grouped
    text = f"{grouped},{dec}"
    if negative:
        text = "\u2212" + text  # real minus sign for print/PDF
    if symbol:
        text += " kr"
    return text


def format_sek_lang(amount: Number, lang: str = "sv", symbol: bool = True) -> str:
    """Locale-aware money string.

    sv: 1 234,56 kr   (NBSP thousands, comma decimal)
    en: 1,234.56 SEK  (comma thousands, dot decimal)
    """
    d = q2(amount)
    negative = d < 0
    d = abs(d)
    ints, _, dec = f"{d:.2f}".partition(".")
    if lang == "en":
        grouped = f"{int(ints):,}"
        text = f"{grouped}.{dec}"
        if symbol:
            text += " SEK"
    else:
        sep = NBSP
        grouped = ""
        rest = ints
        while len(rest) > 3:
            grouped = sep + rest[-3:] + grouped
            rest = rest[:-3]
        grouped = rest + grouped
        text = f"{grouped},{dec}"
        if symbol:
            text += " kr"
    return ("\u2212" if negative else "") + text


def format_int_lang(amount: Number, lang: str = "sv") -> str:
    n = round_kronor(amount)
    negative = n < 0
    s = f"{abs(n):,}" if lang == "en" else None
    if s is None:
        raw = str(abs(n))
        grouped = ""
        while len(raw) > 3:
            grouped = NBSP + raw[-3:] + grouped
            raw = raw[:-3]
        s = raw + grouped
    return ("-" if negative else "") + s


def format_int(amount: Number) -> str:
    """Whole-kronor Swedish formatting (for declaration boxes)."""
    n = round_kronor(amount)
    negative = n < 0
    s = str(abs(n))
    grouped = ""
    while len(s) > 3:
        grouped = NBSP + s[-3:] + grouped
        s = s[:-3]
    grouped = s + grouped
    return ("-" if negative else "") + grouped


def format_qty(q: Number) -> str:
    d = to_decimal(q).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP).normalize()
    s = f"{d:f}"
    return s.replace(".", ",")


def format_qty2(q: Number) -> str:
    """Quantity with two decimals, Swedish style: 1 -> '1,00' (as on the
    user's invoice template)."""
    d = to_decimal(q).quantize(CENT, rounding=ROUND_HALF_UP)
    s = f"{d:.2f}"
    ints, _, dec = s.partition(".")
    return f"{ints},{dec}"
