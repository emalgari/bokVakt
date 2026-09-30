"""i18n layer: JSON catalogs + tr() + QLocale-based formatting.

Rules
-----
* Catalogs live in ``locales/sv.json`` (identity keys) and ``locales/en.json``.
* ``tr(key, **params)`` returns the translation for the active language;
  missing keys fall back to Swedish and log a warning (coverage-tested).
* One English locale only: ``en_US``. Swedish: ``sv_SE``.
* Money/dates: sv → ``2026-09-29``, ``1 234,56 kr`` (NBSP thousands, comma
  decimal); en → ``2026-09-29``, ``1,234.56 SEK`` (comma thousands, dot).
* The invoice PDF NEVER uses this layer (core.pdf locks locale "sv").
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QDate, QLocale

log = logging.getLogger("firmabok.i18n")

LANGS = ("sv", "en")
DEFAULT_LANG = "sv"
_LOCALES = {
    "sv": QLocale(QLocale.Language.Swedish, QLocale.Country.Sweden),
    "en": QLocale(QLocale.Language.English, QLocale.Country.UnitedStates),
}
MONTHS_SV = ["januari", "februari", "mars", "april", "maj", "juni", "juli",
             "augusti", "september", "oktober", "november", "december"]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

_DIR = Path(__file__).resolve().parent / "locales"


def _load(lang: str) -> dict[str, str]:
    try:
        return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover
        log.error("Katalog saknas/korrupt (%s): %s", lang, exc)
        return {}


_CATALOGS: dict[str, dict[str, str]] = {lang: _load(lang) for lang in LANGS}


class I18n:
    """Language singleton with a plain subscriber list (Qt-agnostic).

    UI widgets register retranslate callbacks; ``set_language`` notifies all
    subscribers synchronously so the switch is immediate, no restart.
    """

    def __init__(self) -> None:
        self._language = DEFAULT_LANG
        self._subscribers: list = []

    @property
    def language(self) -> str:
        return self._language

    def locale(self) -> QLocale:
        return _LOCALES[self._language]

    def set_language(self, lang: str) -> None:
        if lang not in LANGS or lang == self._language:
            return
        self._language = lang
        save_language(lang)
        for cb in list(self._subscribers):
            try:
                cb()
            except Exception:  # pragma: no cover
                log.exception("retranslate failed for %r", cb)

    def subscribe(self, callback) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)


i18n = I18n()


def init_language(lang: str) -> None:
    """Set language WITHOUT persistence (startup / tests / wizard preview)."""
    if lang in LANGS:
        i18n._language = lang


def tr(key: str, **params) -> str:
    """Translate `key` into the active language (params for {} formatting)."""
    lang = i18n.language
    if lang == DEFAULT_LANG:
        text = _CATALOGS[DEFAULT_LANG].get(key, key)
    else:
        try:
            text = _CATALOGS[lang][key]
        except KeyError:
            log.warning("missing %s translation for %r — falling back to Swedish", lang, key)
            text = _CATALOGS[DEFAULT_LANG].get(key, key)
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError):  # pragma: no cover
            log.warning("tr() params mismatch for %r %r", key, params)
    return text


def translate(lang: str, text: str) -> str:
    """Translate with an explicit language (used by exporters/PDF reports)."""
    if lang == DEFAULT_LANG:
        return _CATALOGS[DEFAULT_LANG].get(text, text)
    try:
        return _CATALOGS[lang][text]
    except KeyError:
        return _CATALOGS[DEFAULT_LANG].get(text, text)


def translate_for(lang: str):
    return lambda text: translate(lang, text)


def catalog_keys() -> set[str]:
    return set(_CATALOGS[DEFAULT_LANG]) | set(_CATALOGS["en"])


def month_name(m: int) -> str:
    names = MONTHS_EN if i18n.language == "en" else MONTHS_SV
    return names[int(m) - 1]


# ---------------------------------------------------------------------------
# Formatting (QLocale-backed, display only; storage/math stays Decimal)
# ---------------------------------------------------------------------------

class Fmt:
    @staticmethod
    def money(value, symbol: bool = True) -> str:
        from ..core.money import q2
        ql = i18n.locale()
        d = q2(value)
        s = ql.toString(float(d), "f", 2)
        if symbol:
            s += " kr" if i18n.language == "sv" else " SEK"
        return s

    @staticmethod
    def int(value) -> str:
        from ..core.money import round_kronor
        return i18n.locale().toString(int(round_kronor(value)))

    @staticmethod
    def date(d) -> str:
        if d is None:
            return ""
        if isinstance(d, QDate):
            return d.toString("yyyy-MM-dd")
        return QDate(d.year, d.month, d.day).toString("yyyy-MM-dd")

    @staticmethod
    def qty(value) -> str:
        from decimal import Decimal

        from ..core.money import to_decimal
        d = to_decimal(value).quantize(Decimal("0.001")).normalize()
        s = i18n.locale().toString(float(d), "f", max(0, -d.as_tuple().exponent))
        return s if s else "0"


fmt = Fmt()


def save_language(lang: str) -> None:  # patched by ui.main at startup
    try:
        from ..core.config import settings
        settings().set("language", lang)
        settings().save()
    except Exception:  # pragma: no cover
        log.exception("kunde inte spara språkval")
