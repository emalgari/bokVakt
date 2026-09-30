"""Swedish identifier validation and fiscal-period math."""
from datetime import date

import pytest

from firmabok.core.swedish import (
    fiscal_year_bounds,
    fiscal_year_of,
    luhn_check_digit,
    luhn_ok,
    make_ocr,
    normalize_org_nr,
    normalize_vat_number,
    period_of,
    vat_matches_org_nr,
)


def _valid_org(digits9: str) -> str:
    return digits9 + str(luhn_check_digit(digits9))


def test_org_nr_luhn_validation():
    good = _valid_org("556000123")
    assert normalize_org_nr(good) == f"{good[:6]}-{good[6:]}"
    assert normalize_org_nr(f"{good[:6]}{good[6:]}") == f"{good[:6]}-{good[6:]}"
    # flip one digit -> invalid check digit
    bad = ("5" if good[0] != "5" else "6") + good[1:]
    with pytest.raises(ValueError):
        normalize_org_nr(bad)
    with pytest.raises(ValueError):
        normalize_org_nr("12345")


def test_vat_number_format():
    org = _valid_org("556000123")
    good = f"SE{org}01"
    assert normalize_vat_number(good.lower().replace("se", "se")) == good
    assert normalize_vat_number(f"se {good[2:]}") == good
    with pytest.raises(ValueError):
        normalize_vat_number("SE123")            # too short
    with pytest.raises(ValueError):
        normalize_vat_number(f"SE{org}02")       # must end in 01
    assert vat_matches_org_nr(good, f"{org[:6]}-{org[6:]}")
    assert not vat_matches_org_nr(good, _valid_org("556000124"))


def test_ocr_luhn():
    ocr = make_ocr("2026-0001")
    assert ocr.startswith("20260001")
    assert luhn_ok(ocr)
    assert make_ocr("") == ""


def test_calendar_year_periods():
    p = period_of("month", 2026, 3)
    assert (p.start, p.end) == (date(2026, 3, 1), date(2026, 3, 31))
    q = period_of("quarter", 2026, 2)
    assert (q.start, q.end) == (date(2026, 4, 1), date(2026, 6, 30))
    y = period_of("year", 2026, 1)
    assert (y.start, y.end) == (date(2026, 1, 1), date(2026, 12, 31))
    assert y.label == "2026" and q.label == "2026-Q2" and p.label == "2026-03"


def test_broken_fiscal_year_may_to_april():
    fy_start = 5
    assert fiscal_year_of(date(2026, 4, 30), fy_start) == 2025
    assert fiscal_year_of(date(2026, 5, 1), fy_start) == 2026
    start, end = fiscal_year_bounds(2025, fy_start)
    assert (start, end) == (date(2025, 5, 1), date(2026, 4, 30))
    # fiscal month 1 = May 2025, fiscal month 12 = April 2026
    m1 = period_of("month", 2025, 1, fy_start)
    m12 = period_of("month", 2025, 12, fy_start)
    assert (m1.start, m1.end) == (date(2025, 5, 1), date(2025, 5, 31))
    assert (m12.start, m12.end) == (date(2026, 4, 1), date(2026, 4, 30))
    # fiscal quarter 1 = May–Jul
    q1 = period_of("quarter", 2025, 1, fy_start)
    assert (q1.start, q1.end) == (date(2025, 5, 1), date(2025, 7, 31))
    y = period_of("year", 2025, 1, fy_start)
    assert (y.start, y.end) == (date(2025, 5, 1), date(2026, 4, 30))
