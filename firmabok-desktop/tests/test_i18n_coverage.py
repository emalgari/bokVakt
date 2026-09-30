"""i18n coverage gates.

1. Catalog parity: sv.json and en.json have identical key sets, no empties.
2. Every tr()/DomainError key literal in src/firmabok is present in BOTH
   catalogs (AST-based; implicit string concatenation handled).
3. Fallback: unknown keys return the Swedish source string.
4. Locale formatting: sv vs en money/date formats, never mixed.
"""
from __future__ import annotations

import ast
import glob
import json
from pathlib import Path

from firmabok.i18n import fmt, init_language, tr

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src" / "firmabok" / "i18n" / "locales"

ERROR_CLASSES = {"DomainError", "InvoiceError", "OrgNrError", "VatNumberError",
                 "BackupError", "ValidationError"}


def _catalog(lang):
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def test_catalog_parity_and_nonempty():
    sv, en = _catalog("sv"), _catalog("en")
    assert set(sv) == set(en), sorted(set(sv) ^ set(en))[:10]
    assert all(str(v).strip() for v in en.values())
    assert all(str(v).strip() for v in sv.values())


def test_every_tr_key_is_catalogued():
    sv = _catalog("sv")
    en = _catalog("en")
    missing = set()
    for path in glob.glob(str(ROOT / "src" / "firmabok" / "**" / "*.py"), recursive=True):
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            first = node.args[0]
            if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
                continue
            key = first.value
            if name == "set_text" or name == "tr":
                if key not in sv or key not in en:
                    missing.add(key)
            elif name in ERROR_CLASSES and key.count(".") \
                    and (key not in sv or key not in en):
                # dotted keys are translation keys by convention
                missing.add(key)
    assert not missing, sorted(missing)[:20]


def test_fallback_and_active_translation():
    init_language("sv")
    assert tr("Intäkter") == "Intäkter"
    assert tr("Finns inte i katalogen") == "Finns inte i katalogen"
    init_language("en")
    try:
        assert tr("Intäkter") == "Income"
        assert tr("inv.finalize.no_lines") == "The invoice has no lines."
        assert tr("okänd nyckel xyz") == "okänd nyckel xyz"  # Swedish fallback
        assert tr("vat.unknown_code", code="XX9") == "Unknown VAT code: XX9"
    finally:
        init_language("sv")


def test_locale_formats_never_mix():
    init_language("sv")
    try:
        from decimal import Decimal
        assert fmt.money(Decimal("1234567.5")) == "1\u00a0234\u00a0567,50 kr"
        assert fmt.money(Decimal("-42.5"), symbol=False) == "\u221242,50"
        assert fmt.date(__import__("datetime").date(2026, 9, 29)) == "2026-09-29"
        init_language("en")
        assert fmt.money(Decimal("1234567.5")) == "1,234,567.50 SEK"
        assert fmt.money(Decimal("-42.5"), symbol=False) in ("-42.50", "\u221242.50")  # QLocale minus
        assert fmt.date(__import__("datetime").date(2026, 9, 29)) == "2026-09-29"
    finally:
        init_language("sv")
