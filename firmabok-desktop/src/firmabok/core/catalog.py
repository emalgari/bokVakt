"""Pure-Python translation catalog reader (no Qt) for the core layer.

Used by exporters (CSV/report PDF labels) that must render in a requested
language without importing the UI i18n stack. Reads the SAME catalogs as the
UI: firmabok/i18n/locales/{sv,en}.json.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("firmabok.core.catalog")

LANGS = ("sv", "en")
_LOCALES_DIR = Path(__file__).resolve().parents[1] / "i18n" / "locales"


@lru_cache(maxsize=1)
def _catalogs() -> dict[str, dict[str, str]]:
    out = {}
    for lang in LANGS:
        try:
            out[lang] = json.loads((_LOCALES_DIR / f"{lang}.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            log.error("catalog unreadable: %s", lang)
            out[lang] = {}
    return out


def translate(lang: str, text: str) -> str:
    """Translate `text` (Swedish source string) into `lang`; fallback sv."""
    if lang == "sv":
        return text
    return _catalogs().get(lang, {}).get(text, text)
