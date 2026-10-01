"""Shared building blocks for the auth screens (Phase 2).

All screens are card-based (max 420 px, ``QFrame#card``), fully bilingual
with an instant SV|EN pill, keyboard accessible (tab order = layout order,
one default button per screen, accessible names on icon-only controls) and
free of hardcoded strings. Core calls go through ``core.accounts`` — the UI
translates keyed ``AuthError``s at the boundary and never touches hashes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import accounts
from ...core.db import get_session_factory
from ...i18n import i18n, tr
from .. import theme
from ..widgets.forms import LabeledField

CARD_MAX_W = 420

#: Strength segment colors by level 1..4 (design tokens only).
_STRENGTH_COLORS = {1: "danger", 2: "warning", 3: "primary-soft", 4: "success"}
_STRENGTH_KEYS = {1: "Mycket svagt", 2: "Svagt", 3: "Bra", 4: "Starkt"}

#: Small built-in blocklist (product UX only — never a security boundary).
_COMMON_PASSWORDS = {
    "password", "password1", "passw0rd", "12345678", "123456789", "1234567890",
    "qwertyui", "qwerty123", "letmein1", "iloveyou", "admin123", "welcome1",
    "changeme", "abcdefgh", "11111111", "00000000", "lösenord", "lösenord1",
}


def password_strength(password: str) -> int:
    """Deterministic 0..4 estimate (pure function, no hashing, no I/O).

    0 = shorter than ``accounts.MIN_PASSWORD_LENGTH`` (invalid); 1..4 =
    very weak → strong, from length, character-class variety and a small
    common-password blocklist.
    """
    pw = password or ""
    if len(pw) < accounts.MIN_PASSWORD_LENGTH:
        return 0
    if pw.lower() in _COMMON_PASSWORDS:
        return 1
    classes = sum((
        any(c.islower() for c in pw),
        any(c.isupper() for c in pw),
        any(c.isdigit() for c in pw),
        any(not c.isalnum() for c in pw),
    ))
    score = 1
    if len(pw) >= 12:
        score += 1
    if len(pw) >= 16:
        score += 1
    if classes >= 3:
        score += 1
    if classes >= 2 and len(pw) >= 12:
        score += 1
    return min(score, 4)


class LanguageToggle(QWidget):
    """SV|EN pill for light backgrounds (``QToolButton#langBtnLight`` —
    same behavior/tokens as the header pill)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.buttons: dict[str, QToolButton] = {}
        for lang, text in (("sv", "SV"), ("en", "EN")):
            b = QToolButton()
            b.setObjectName("langBtnLight")
            b.setText(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, lg=lang: self._set(lg))
            self.buttons[lang] = b
            lay.addWidget(b)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def _set(self, lang: str) -> None:
        if i18n.language != lang:
            i18n.set_language(lang)
        self._sync()

    def _sync(self) -> None:
        for lang, b in self.buttons.items():
            b.setChecked(lang == i18n.language)

    def retranslate(self) -> None:
        self._sync()
        for lang, b in self.buttons.items():
            full = "Svenska" if lang == "sv" else "English"
            b.setToolTip(tr("Språk") + f": {full}")
            b.setAccessibleName(tr("Språk") + f" {full}")

    def detach_i18n(self) -> None:
        i18n.unsubscribe(self.retranslate)


class PasswordField(QLineEdit):
    """Password input with a trailing show/hide eye toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self._revealed = False
        self._toggle = QAction(theme.icon("eye"), "", self)
        self._toggle.setCheckable(True)
        self._toggle.triggered.connect(self._on_toggle)
        self.addAction(self._toggle, QLineEdit.ActionPosition.TrailingPosition)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def _on_toggle(self, on: bool) -> None:
        self._revealed = bool(on)
        self.setEchoMode(QLineEdit.EchoMode.Normal if on
                         else QLineEdit.EchoMode.Password)
        self._toggle.setIcon(theme.icon("eye-off" if on else "eye"))
        self.retranslate()

    def retranslate(self) -> None:
        label = tr("Dölj lösenord") if self._revealed else tr("Visa lösenord")
        self._toggle.setText(label)
        self._toggle.setToolTip(label)

    def detach_i18n(self) -> None:
        i18n.unsubscribe(self.retranslate)


class PasswordStrengthMeter(QWidget):
    """4-segment bar + label driven by :func:`password_strength`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        self.segments: list[QFrame] = []
        for _ in range(4):
            seg = QFrame()
            seg.setFixedHeight(6)
            seg.setStyleSheet(
                f"background: {theme.COLORS['border']}; border-radius: 3px;")
            self.segments.append(seg)
            bar.addWidget(seg, 1)
        lay.addLayout(bar)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("")
        self.caption.setObjectName("muted")
        self.label = QLabel("")
        self.label.setObjectName("muted")
        row.addWidget(self.caption)
        row.addStretch(1)
        row.addWidget(self.label)
        lay.addLayout(row)
        self._level = -1
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def update_password(self, password: str) -> int:
        level = password_strength(password)
        self._level = level
        self._nonempty = bool(password)
        self._paint()
        return level

    def _paint(self) -> None:
        level = self._level
        color = (theme.COLORS[_STRENGTH_COLORS[level]] if level >= 1
                 else theme.COLORS["border"])
        for i, seg in enumerate(self.segments):
            filled = level >= 1 and i < level
            seg.setStyleSheet(
                f"background: {color if filled else theme.COLORS['border']};"
                " border-radius: 3px;")
        if level <= 0:
            # "too short" hint only while the user has actually typed something
            self.label.setText(
                tr("auth.password_too_short", min_length=accounts.MIN_PASSWORD_LENGTH)
                if getattr(self, "_nonempty", False) else "")
        else:
            self.label.setText(tr(_STRENGTH_KEYS[level]))

    def retranslate(self) -> None:
        self.caption.setText(tr("Lösenordsstyrka"))
        self._paint()

    def detach_i18n(self) -> None:
        i18n.unsubscribe(self.retranslate)


class AuthScreenBase(QWidget):
    """Centered card on the app background: language pill (top-right), brand
    title, screen title/subtitle, optional error banner. Subclasses build
    their widgets, then call ``i18n.subscribe(self.retranslate)`` +
    ``self.retranslate()`` at the END of ``__init__`` (project pattern)."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._factory = session_factory or get_session_factory()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 24)
        outer.setSpacing(12)

        top = QHBoxLayout()
        top.addStretch(1)
        self.lang_toggle = LanguageToggle()
        top.addWidget(self.lang_toggle)
        outer.addLayout(top)
        outer.addStretch(1)

        center = QHBoxLayout()
        center.addStretch(1)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setMaximumWidth(CARD_MAX_W)
        self.card.setMinimumWidth(340)
        self.lay = QVBoxLayout(self.card)
        self.lay.setContentsMargins(24, 24, 24, 24)
        self.lay.setSpacing(12)

        self.brand = QLabel("bokVakt")
        self.brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand.setStyleSheet(
            f"font-size:24px;font-weight:700;color:{theme.COLORS['primary']};")
        self.heading = QLabel("")
        self.heading.setObjectName("cardTitle")
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.heading.setWordWrap(True)
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("muted")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setWordWrap(True)

        self.error_banner = QFrame()
        self.error_banner.setObjectName("bannerDanger")
        self.error_banner.setVisible(False)
        ebl = QHBoxLayout(self.error_banner)
        ebl.setContentsMargins(10, 8, 10, 8)
        icon = QLabel()
        icon.setPixmap(theme.icon("alert-triangle", color=theme.COLORS["danger"])
                       .pixmap(16, 16))
        ebl.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)
        self.error_text = QLabel("")
        self.error_text.setWordWrap(True)
        self.error_text.setStyleSheet(f"color:{theme.COLORS['danger']};")
        ebl.addWidget(self.error_text, 1)

        self.info_banner = QFrame()
        self.info_banner.setObjectName("bannerInfo")
        self.info_banner.setVisible(False)
        ibl = QHBoxLayout(self.info_banner)
        ibl.setContentsMargins(10, 8, 10, 8)
        self.info_text = QLabel("")
        self.info_text.setWordWrap(True)
        self.info_text.setStyleSheet(f"color:{theme.COLORS['primary']};")
        ibl.addWidget(self.info_text, 1)

        self.lay.addWidget(self.brand)
        self.lay.addWidget(self.heading)
        self.lay.addWidget(self.subtitle)
        self.lay.addWidget(self.error_banner)
        self.lay.addWidget(self.info_banner)

        center.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignHCenter)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(2)

    # ------------------------------------------------------------- helpers
    def session(self):
        """Short-lived session (core functions commit; caller closes).
        ``_factory`` is a callable returning a Session (a sessionmaker)."""
        return self._factory()

    def show_error(self, key: str, **params) -> None:
        self.error_text.setText(tr(key, **params))
        self.error_banner.setVisible(True)
        self.info_banner.setVisible(False)

    def show_error_from(self, exc) -> None:
        self.show_error(exc.key, **getattr(exc, "params", {}))

    def show_info(self, key: str, **params) -> None:
        self.info_text.setText(tr(key, **params))
        self.info_banner.setVisible(True)
        self.error_banner.setVisible(False)

    def clear_banners(self) -> None:
        self.error_banner.setVisible(False)
        self.info_banner.setVisible(False)

    def retranslate_base(self) -> None:
        self.heading.setText(tr(self._heading_key()) if self._heading_key() else "")
        sub = self._subtitle_key()
        self.subtitle.setText(tr(sub) if sub else "")
        self.subtitle.setVisible(bool(sub))

    def _heading_key(self) -> str:  # overridden by screens
        return ""

    def _subtitle_key(self) -> str:  # overridden by screens
        return ""

    def detach_i18n(self) -> None:
        i18n.unsubscribe(self.retranslate)
        self.lang_toggle.detach_i18n()
        for child in self.findChildren(QWidget):
            if hasattr(child, "detach_i18n"):
                child.detach_i18n()

    def retranslate(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class AuthField(LabeledField):
    """LabeledField with explicit i18n unsubscription — auth screens are
    short-lived (destroyed after startup), unlike pages."""

    def detach_i18n(self) -> None:
        i18n.unsubscribe(self.retranslate)


def detach_orm(session, obj):
    """Make an ORM object safe to use after the session closes: reload the
    attributes (core functions commit, which expires them) then expunge."""
    session.refresh(obj)
    session.expunge(obj)
    return obj


def mono_font(point_size: int = 13) -> QFont:
    f = QFont()
    f.setFamilies(["DejaVu Sans Mono", "Liberation Mono", "Courier New",
                   "monospace"])
    f.setPointSize(point_size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def secondary_button(text_key: str = "", icon_name: str = "") -> QPushButton:
    b = QPushButton()
    b.setProperty("kind", "secondary")
    b.setAutoDefault(False)
    if icon_name:
        b.setIcon(theme.icon(icon_name, color=theme.COLORS["primary"]))
    if text_key:
        b.setText(tr(text_key))
    return b


def ghost_button(text_key: str = "", icon_name: str = "") -> QPushButton:
    b = QPushButton()
    b.setProperty("kind", "ghost")
    b.setAutoDefault(False)
    if icon_name:
        b.setIcon(theme.icon(icon_name, color=theme.COLORS["primary"]))
    if text_key:
        b.setText(tr(text_key))
    return b
