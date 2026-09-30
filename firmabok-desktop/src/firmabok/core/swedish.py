"""Swedish identifiers, dates and fiscal-period helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .errors import OrgNrError, VatNumberError

ORG_NR_RE = re.compile(r"^\d{6}-?\d{4}$")


def normalize_org_nr(value: str) -> str:
    """Return org.nr as XXXXXX-XXXX. Raises ValueError if invalid."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) != 10:
        raise OrgNrError("orgnr.length")
    if not luhn_ok(digits):
        raise OrgNrError("orgnr.luhn")
    return f"{digits[:6]}-{digits[6:]}"


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def luhn_check_digit(digits: str) -> int:
    """Check digit that makes `digits + check` pass LUHN."""
    for c in range(10):
        if luhn_ok(digits + str(c)):
            return c
    raise AssertionError("unreachable")


def normalize_vat_number(value: str, org_nr: str | None = None) -> str:
    """Swedish VAT reg. number: SE + 12 siffror + '01'? No — SE + org.nr
    (10 digits) + '01' = SEXXXXXXXXXX01. Returns uppercase without spaces.
    Raises ValueError when malformed; warns (not raises) on org.nr mismatch
    is handled by the caller via validate_vat_number."""
    v = re.sub(r"[\s]", "", (value or "")).upper()
    if not re.fullmatch(r"SE\d{12}", v):
        raise VatNumberError("vatnr.format")
    if not v.endswith("01"):
        raise VatNumberError("vatnr.suffix")
    return v


def vat_matches_org_nr(vat_number: str, org_nr: str) -> bool:
    """True when VAT number is consistent with the org.nr (SE + digits + 01)."""
    try:
        org_digits = re.sub(r"\D", "", org_nr)
        return vat_number.upper() == f"SE{org_digits}01"
    except Exception:
        return False


def make_ocr(reference: str) -> str:
    """OCR reference: digits of `reference` + LUHN check digit.
    Common Swedish practice: invoice number digits with a check digit so
    bank payments can be validated."""
    digits = re.sub(r"\D", "", reference or "")
    if not digits:
        return ""
    return digits + str(luhn_check_digit(digits))


@dataclass(frozen=True)
class Period:
    """A fiscal period (month, quarter or year) with concrete start/end dates."""
    kind: str          # 'month' | 'quarter' | 'year'
    year: int          # fiscal year label
    number: int        # 1..12, 1..4 or 1
    start: date
    end: date

    @property
    def label(self) -> str:
        if self.kind == "month":
            return f"{self.year}-{self.number:02d}"
        if self.kind == "quarter":
            return f"{self.year}-Q{self.number}"
        return f"{self.year}"

    @property
    def next_start(self) -> date:
        from datetime import timedelta
        return self.end + timedelta(days=1)


def fiscal_year_of(d: date, fy_start_month: int = 1) -> int:
    """Label of the fiscal year containing date `d`.
    A fiscal year starting in e.g. May 2025 is labelled 2025 (start year),
    matching the common 'brutet räkenskapsår 2025/2026' notation."""
    if fy_start_month == 1:
        return d.year
    if d.month >= fy_start_month:
        return d.year
    return d.year - 1


def fiscal_year_bounds(fy_year: int, fy_start_month: int = 1) -> tuple[date, date]:
    if fy_start_month == 1:
        return date(fy_year, 1, 1), date(fy_year, 12, 31)
    start = date(fy_year, fy_start_month, 1)
    end_year = fy_year + 1
    end = date(end_year, fy_start_month, 1) - _one_day()
    return start, end


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


def period_of(kind: str, fy_year: int, number: int, fy_start_month: int = 1) -> Period:
    """Build a Period. Months/quarters are counted from the fiscal year start
    (for calendar-year firms this is identical to calendar months/quarters)."""
    if kind == "year":
        start, end = fiscal_year_bounds(fy_year, fy_start_month)
        return Period("year", fy_year, 1, start, end)
    if kind == "month":
        if not 1 <= number <= 12:
            raise ValueError("Månadsperiod måste vara 1-12.")
        y, m = fy_year, fy_start_month
        for _ in range(number - 1):
            m += 1
            if m > 12:
                m = 1
                y += 1
        start = date(y, m, 1)
        nm, ny = (m + 1, y) if m < 12 else (1, y + 1)
        end = date(ny, nm, 1) - _one_day()
        return Period("month", fy_year, number, start, end)
    if kind == "quarter":
        if not 1 <= number <= 4:
            raise ValueError("Kvartalsperiod måste vara 1-4.")
        first_month = 1 + 3 * (number - 1)
        start = period_of("month", fy_year, first_month, fy_start_month).start
        end = period_of("month", fy_year, first_month + 2, fy_start_month).end
        return Period("quarter", fy_year, number, start, end)
    raise ValueError(f"Okänd periodtyp: {kind}")


def periods_of_year(kind: str, fy_year: int, fy_start_month: int = 1) -> list[Period]:
    if kind == "year":
        return [period_of("year", fy_year, 1, fy_start_month)]
    if kind == "quarter":
        return [period_of("quarter", fy_year, n, fy_start_month) for n in range(1, 5)]
    return [period_of("month", fy_year, n, fy_start_month) for n in range(1, 13)]


def filing_due(period_end: date, day: int = 12, month_offset: int = 2) -> date:
    """Momsdeklarationens inlämningsdatum: som standard den 12:e i den ANDRA
    månaden efter redovisningsperiodens utgång (per SKV-registerutdrag).
    Infaller den 12:e på en helgfri dag senast den dagen; om den 12:e är
    en helgdag senareläggs datumet — kontrollera alltid Skatteverkets
    uppgift för din period.

    ``day``/``month_offset`` är ANVÄNDARSTYRDA standardvärden
    (Inställningar → Lön & skatteparametrar), inte hårdkodade lagregler."""
    m = period_end.month + month_offset
    y = period_end.year
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, day)


def month_name_sv(m: int) -> str:
    names = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
             "augusti", "september", "oktober", "november", "december"]
    return names[m - 1]


def weekday_name_sv(d: date) -> str:
    names = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
    return names[d.weekday()]


def format_date_sv(d: date | None) -> str:
    return d.isoformat() if d else ""


def decimal_or_zero(value) -> Decimal:
    return Decimal(str(value or 0))
