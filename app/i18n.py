"""Two-language UI (Swedish + English).

Design
------
* Catalogs live in ``app/locales/sv.json`` and ``app/locales/en.json``.
  Keys are the Swedish source strings; ``sv.json`` maps identity and acts
  as the authoritative string inventory, ``en.json`` holds translations.
* The **application UI** is bilingual (default Swedish). Missing English
  keys fall back to Swedish and log a warning when FIRMA_DEBUG=1.
* **Invoices are ALWAYS Swedish** (legal documents; explicit product
  decision). Report PDFs and CSV exports follow the UI language.
* Money/date formatting is locale-aware (see app.money.format_money).
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("firma.i18n")

LANGS = ("sv", "en")
DEFAULT_LANG = "sv"
COOKIE_NAME = "firma_lang"

_LOCALES_DIR = Path(__file__).resolve().parent / "locales"

MONTHS_SV = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
             "augusti", "september", "oktober", "november", "december"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]


@lru_cache(maxsize=1)
def _catalogs() -> dict[str, dict[str, str]]:
    out = {}
    for lang in LANGS:
        path = _LOCALES_DIR / f"{lang}.json"
        try:
            out[lang] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
            log.error("Kunde inte läsa katalog %s: %s", path, exc)
            out[lang] = {}
    return out


def translate(lang: str, text: str) -> str:
    """Translate `text` (a Swedish source string) into `lang`.

    Falls back to the Swedish source string when a key is missing; in
    debug mode (FIRMA_DEBUG=1) a warning is logged so gaps are noticed.
    """
    if lang == DEFAULT_LANG:
        return text
    cat = _catalogs().get(lang, {})
    try:
        return cat[text]
    except KeyError:
        if os.environ.get("FIRMA_DEBUG"):
            log.warning(" saknar översättning [%s]: %r", lang, text)
        return text


def lang_from_request(request) -> str:
    lang = (request.cookies.get(COOKIE_NAME) or DEFAULT_LANG).lower()
    return lang if lang in LANGS else DEFAULT_LANG


def month_name(lang: str, m: int) -> str:
    if lang == "en":
        return MONTHS_EN[int(m) - 1]
    return MONTHS_SV[int(m) - 1].capitalize()


def reload_catalogs() -> None:
    """Test/helper hook: drop the cached catalogs."""
    _catalogs.cache_clear()
