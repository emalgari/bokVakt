"""Top bar: brand/logo (left) · primary nav (center, overflow menu on narrow
widths) · language toggle + logout (right).

Rules implemented here:
* Logo: max height 36 px, aspect ratio preserved, smooth scaling; if no logo
  is configured or the file is unreadable, a clean TEXT logo (company name)
  is shown — a broken image can never appear.
* Nav items never wrap or clip: when the header is too narrow, items collapse
  into an overflow QMenu (checkable, mirrors active page).
* Language toggle: segmented SV|EN pill, checkable exclusive group,
  accessible names/tooltips, persists via i18n.
* Logout: icon + label, same 34 px height as siblings, right-aligned.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import config as core_config
from ..i18n import i18n, tr
from . import theme

NAV_ITEMS = [
    ("dashboard", "Dashboard", "layout-dashboard"),
    ("income", "Intäkter", "coins"),
    ("expenses", "Utgifter", "receipt"),
    ("vat", "Moms", "percent"),
    ("quarterly", "Kvartalsmoms", "calendar-check"),
    ("invoices", "Fakturor", "file-text"),
    ("customers", "Kunder", "users"),
    ("owner", "Ägare", "wallet"),
    ("employees", "Anställda", "briefcase"),
    ("reports", "Rapporter", "bar-chart"),
    ("taxdocs", "Skattedokument", "file-lock"),
    ("data", "Data", "database"),
]

LOGO_MAX_H = 36
BUTTON_H = 34


class HeaderBar(QFrame):
    nav_selected = Signal(str)         # page id
    logout_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("header")
        self.setFixedHeight(64)
        self._current_page = "dashboard"
        self._overflow_mode = False

        root = QHBoxLayout(self)
        root.setContentsMargins(16, 6, 16, 6)
        root.setSpacing(12)

        # ---------- brand / logo ----------
        self.brand_box = QWidget()
        brand_lay = QVBoxLayout(self.brand_box)
        brand_lay.setContentsMargins(0, 0, 0, 0)
        brand_lay.setSpacing(0)
        self.logo_label = QLabel()
        self.logo_label.setFixedHeight(LOGO_MAX_H)
        self.logo_label.setVisible(False)
        self.brand_text = QLabel("Firmabok")
        self.brand_text.setObjectName("brand")
        from PySide6.QtGui import QFont
        bf = QFont()
        bf.setPointSize(15)
        self.brand_text.setFont(bf)
        self.brand_sub = QLabel("")
        self.brand_sub.setObjectName("brandSub")
        self.brand_sub.setMaximumWidth(260)
        brand_lay.addWidget(self.logo_label)
        brand_lay.addWidget(self.brand_text)
        brand_lay.addWidget(self.brand_sub)
        root.addWidget(self.brand_box)

        # ---------- nav (center) ----------
        self.nav_host = QWidget()
        self.nav_lay = QHBoxLayout(self.nav_host)
        self.nav_lay.setContentsMargins(0, 0, 0, 0)
        self.nav_lay.setSpacing(2)
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QToolButton] = {}
        self._nav_actions: dict[str, QAction] = {}
        for page_id, _label_key, icon_name in NAV_ITEMS:
            btn = QToolButton()
            btn.setProperty("class", "navBtn")
            btn.setObjectName(f"nav-{page_id}")
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            btn.setIcon(theme.icon(icon_name, color="#E6EEF5"))
            btn.setIconSize(QSize(16, 16))
            btn.setMinimumHeight(BUTTON_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, pid=page_id: self._emit_nav(pid))
            self._nav_group.addButton(btn)
            self._nav_buttons[page_id] = btn
            self.nav_lay.addWidget(btn)

            act = QAction(theme.icon(icon_name, color="#10314F"), "", self)
            act.setCheckable(True)
            act.setData(page_id)
            act.triggered.connect(lambda _=False, pid=page_id: self._emit_nav(pid))
            self._nav_actions[page_id] = act
        self.overflow_menu = QMenu(self)
        for page_id, _, _ in NAV_ITEMS:
            self.overflow_menu.addAction(self._nav_actions[page_id])
        self.overflow_btn = QToolButton()
        self.overflow_btn.setObjectName("nav-overflow")
        self.overflow_btn.setProperty("class", "navBtn")
        self.overflow_btn.setIcon(theme.icon("menu", color="#E6EEF5"))
        self.overflow_btn.setIconSize(QSize(18, 18))
        self.overflow_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.overflow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.overflow_btn.setMenu(self.overflow_menu)
        self.overflow_btn.setMinimumHeight(BUTTON_H)
        self.overflow_btn.setVisible(False)
        self.overflow_btn.setStyleSheet("QToolButton::menu-indicator { image: none; }")

        center = QHBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addWidget(self.nav_host)
        center.addWidget(self.overflow_btn)
        center.addStretch(1)
        root.addLayout(center, 1)

        # ---------- right cluster: language pill + logout ----------
        right = QHBoxLayout()
        right.setSpacing(8)
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)
        self.lang_btns: dict[str, QToolButton] = {}
        for lang, text in (("sv", "SV"), ("en", "EN")):
            b = QToolButton()
            b.setObjectName("langBtn")
            b.setText(text)
            b.setCheckable(True)
            b.setMinimumHeight(BUTTON_H)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, lg=lang: self._set_lang(lg))
            self.lang_btns[lang] = b
            right.addWidget(b)
        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setIcon(theme.icon("settings", color="#E6EEF5"))
        self.settings_btn.setIconSize(QSize(16, 16))
        self.settings_btn.setMinimumHeight(BUTTON_H)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_clicked)
        right.addWidget(self.settings_btn)
        self.logout_btn = QPushButton()
        self.logout_btn.setObjectName("logoutBtn")
        self.logout_btn.setIcon(theme.icon("log-out", color="#FFFFFF"))
        self.logout_btn.setMinimumHeight(BUTTON_H)
        self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_btn.clicked.connect(self.logout_clicked)
        right.addWidget(self.logout_btn)
        root.addLayout(right)

        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.set_current_page("dashboard")

    # ------------------------------------------------------------------ API
    def set_current_page(self, page_id: str) -> None:
        self._current_page = page_id
        btn = self._nav_buttons.get(page_id)
        if btn:
            btn.setChecked(True)
        for pid, act in self._nav_actions.items():
            act.setChecked(pid == page_id)

    def load_brand(self, company_name: str, logo_path: str = "") -> None:
        """Text logo fallback is the default; image only when it loads cleanly."""
        pix = None
        if logo_path:
            p = core_config.UPLOAD_DIR / Path(logo_path).name if not Path(logo_path).is_absolute() \
                else Path(logo_path)
            for cand in (p, core_config.UPLOAD_DIR / "logos" / Path(logo_path).name):
                if cand.exists():
                    raw = QPixmap(str(cand))
                    if not raw.isNull():
                        pix = raw.scaledToHeight(LOGO_MAX_H, Qt.TransformationMode.SmoothTransformation)
                        break
        if pix is not None:
            self.logo_label.setPixmap(pix)
            self.logo_label.setVisible(True)
            self.brand_text.setVisible(False)
        else:
            self.logo_label.clear()
            self.logo_label.setVisible(False)
            self.brand_text.setVisible(True)
            self.brand_text.setText(company_name or "Firmabok")
        self.brand_sub.setText(company_name if pix is not None else "")
        self.brand_sub.setToolTip(company_name)

    # -------------------------------------------------------------- signals
    def _emit_nav(self, page_id: str) -> None:
        self.set_current_page(page_id)
        self.nav_selected.emit(page_id)

    def _set_lang(self, lang: str) -> None:
        if i18n.language != lang:
            i18n.set_language(lang)
        self._sync_lang_buttons()

    def _sync_lang_buttons(self) -> None:
        for lang, b in self.lang_btns.items():
            b.setChecked(lang == i18n.language)

    # ---------------------------------------------------------- retranslate
    def retranslate(self) -> None:
        self._sync_lang_buttons()
        for lang, b in self.lang_btns.items():
            full = "Svenska" if lang == "sv" else "English"
            b.setToolTip(tr("Språk") + f": {full}")
            b.setAccessibleName(tr("Språk") + f" {full}")
        for page_id, label_key, _icon in NAV_ITEMS:
            label = tr(label_key)
            self._nav_buttons[page_id].setText(label)
            self._nav_buttons[page_id].setToolTip(label)
            self._nav_actions[page_id].setText(label)
        self.overflow_btn.setToolTip(tr("Meny"))
        self.overflow_btn.setAccessibleName(tr("Meny"))
        self.logout_btn.setText(tr("Logga ut"))
        self.logout_btn.setToolTip(tr("Logga ut"))
        self.settings_btn.setToolTip(tr("Inställningar…"))
        self.settings_btn.setAccessibleName(tr("Inställningar…"))
        self._apply_overflow_if_needed()

    # ------------------------------------------------------------ responsive
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply_overflow_if_needed()

    def _apply_overflow_if_needed(self) -> None:
        width = self.width()
        if width <= 0:
            return
        right_cluster = 264  # lang pill + gear + logout + margins
        brand = self.brand_box.sizeHint().width()
        # stage 1: full nav
        self._set_compact(False)
        needed = brand + self.nav_host.sizeHint().width() + right_cluster
        if width >= needed:
            self._set_overflow(False)
            return
        # stage 2: compact nav (smaller type/padding)
        self._set_compact(True)
        needed = brand + self.nav_host.sizeHint().width() + right_cluster
        if width >= needed:
            self._set_overflow(False)
            return
        # stage 3: overflow menu
        self._set_overflow(True)

    def _set_compact(self, on: bool) -> None:
        """Compact stage: text-only nav buttons (icons hidden) + smaller
        brand type, so all nine items fit inline on laptop widths."""
        if getattr(self, "_compact", False) == on:
            return
        self._compact = on
        for btn in self._nav_buttons.values():
            btn.setProperty("compact", "true" if on else "false")
            btn.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextOnly if on
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            # widget-level sheet wins over the app sheet for these props;
            # hover/checked rules from the app sheet still apply
            btn.setStyleSheet(
                "QToolButton { font-size: 12.5px; padding: 6px 7px; }" if on else "")
            btn.updateGeometry()
        from PySide6.QtGui import QFont
        bf = QFont()
        bf.setPointSize(12 if on else 15)
        bf.setBold(True)
        self.brand_text.setFont(bf)
        self.brand_text.updateGeometry()
        self.brand_box.updateGeometry()
        self.nav_host.updateGeometry()

    def _set_overflow(self, on: bool) -> None:
        if self._overflow_mode == on:
            return
        self._overflow_mode = on
        self.nav_host.setVisible(not on)
        self.overflow_btn.setVisible(on)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(900, 64)
