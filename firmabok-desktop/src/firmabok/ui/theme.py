"""Design system: palette + QSS tokens + icon loader.

Tokens (single source of truth):
  colors   primary #10314F · accent #FFD166 · success #1D5C2B · warning #7A5B00
           danger #8C1D1D · bg #F5F7FA · surface #FFFFFF · border #D7DDE4
           text #1A1D21 · muted #667
  radii    cards 8px · inputs 6px · badges 4px
  spacing  4/8/12/16/24/32
  type     12/14/16/20/24/32px, weights 400/600/700
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

RES = Path(__file__).resolve().parent / "resources"

COLORS = {
    "primary": "#10314F", "primary-soft": "#1B4A75", "accent": "#FFD166",
    "success": "#1D5C2B", "success-bg": "#E2F5E6",
    "warning": "#7A5B00", "warning-bg": "#FFF4D6",
    "danger": "#8C1D1D", "danger-bg": "#FDE3E3",
    "bg": "#F5F7FA", "surface": "#FFFFFF", "border": "#D7DDE4",
    "text": "#1A1D21", "muted": "#667080",
    "header-text": "#E6EEF5", "header-hover": "#27527C",
}

FONT_FAMILY = "Liberation Sans, DejaVu Sans, Noto Sans, sans-serif"


def qss() -> str:
    c = COLORS
    return f"""
* {{ font-family: {FONT_FAMILY}; font-size: 14px; color: {c['text']}; }}
QMainWindow, QDialog, QWizard {{ background: {c['bg']}; }}
QWidget:focus {{ outline: none; }}

/* ---------- cards ---------- */
QFrame#card {{
  background: {c['surface']}; border: 1px solid {c['border']};
  border-radius: 8px; padding: 16px;
}}
QLabel#cardTitle {{ font-size: 16px; font-weight: 600; color: {c['primary']}; }}
QLabel#statValue {{ font-size: 24px; font-weight: 700; color: {c['primary']}; }}
QLabel#statLabel {{ font-size: 12px; color: {c['muted']}; }}
QLabel#muted, QLabel.muted {{ color: {c['muted']}; font-size: 12px; }}
QLabel#pageTitle {{ font-size: 24px; font-weight: 700; color: {c['text']}; }}
QLabel#sectionTitle {{ font-size: 20px; font-weight: 600; color: {c['text']}; }}

/* ---------- header ---------- */
QFrame#header {{ background: {c['primary']}; border: none; min-height: 56px; }}
QLabel#brand {{ color: #FFFFFF; font-size: 20px; font-weight: 700; letter-spacing: 0.3px; }}
QLabel#brandSub {{ color: #9DB4C8; font-size: 12px; }}
QToolButton.navBtn {{
  color: {c['header-text']}; background: transparent; border: none;
  padding: 8px 12px; border-radius: 6px; font-size: 14px; min-height: 24px;
}}
QToolButton.navBtn:hover {{ background: {c['header-hover']}; color: #FFFFFF; }}
QToolButton.navBtn:checked {{
  background: {c['header-hover']}; color: #FFFFFF; font-weight: 600;
  border-bottom: 2px solid {c['accent']};
}}
QToolButton.navBtn:focus-visible {{ border: 1px solid {c['accent']}; }}
QToolButton#langBtn {{
  color: {c['header-text']}; background: transparent;
  border: 1px solid #52708C; border-radius: 999px;
  padding: 4px 12px; font-size: 12px; font-weight: 700; min-height: 20px;
}}
QToolButton#langBtn:checked {{ background: {c['accent']}; color: {c['primary']}; border-color: {c['accent']}; }}
QToolButton#langBtn:hover {{ border-color: #FFFFFF; color: #FFFFFF; }}
QToolButton#langBtn:checked:hover {{ color: {c['primary']}; }}
QToolButton#settingsBtn {{
  background: transparent; border: 1px solid #52708C; border-radius: 6px;
  padding: 6px; min-height: 22px;
}}
QToolButton#settingsBtn:hover {{ border-color: #FFFFFF; background: {c['header-hover']}; }}
QPushButton#logoutBtn {{
  background: transparent; color: #FFFFFF; border: 1px solid #52708C;
  border-radius: 6px; padding: 6px 14px; font-size: 13px; min-height: 22px;
}}
QPushButton#logoutBtn:hover {{ border-color: #FFFFFF; background: {c['header-hover']}; }}

/* ---------- buttons ---------- */
QPushButton {{
  background: {c['primary']}; color: #FFFFFF; border: none; border-radius: 6px;
  padding: 9px 16px; font-size: 14px; font-weight: 600; min-height: 22px;
}}
QPushButton:hover {{ background: {c['primary-soft']}; }}
QPushButton:pressed {{ background: #0A2238; }}
QPushButton:disabled {{ background: #C6CDD6; color: #EEF1F4; }}
QPushButton:focus-visible {{ border: 2px solid #0B62C4; }}
QPushButton[kind="secondary"] {{
  background: {c['surface']}; color: {c['primary']}; border: 1px solid {c['border']};
}}
QPushButton[kind="secondary"]:hover {{ border-color: {c['primary']}; background: #EEF3F8; }}
QPushButton[kind="ghost"] {{ background: transparent; color: {c['primary']}; border: none; }}
QPushButton[kind="ghost"]:hover {{ background: #E4EAF1; }}
QPushButton[kind="danger"] {{ background: {c['danger']}; }}
QPushButton[kind="danger"]:hover {{ background: #A32424; }}
QPushButton#primaryAction {{ background: {c['primary']}; }}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QDoubleSpinBox, QDateEdit, QTextEdit, QPlainTextEdit {{
  background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px;
  padding: 8px 10px; selection-background-color: {c['accent']};
  selection-color: {c['text']}; min-height: 20px;
}}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus,
QDateEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
  border: 2px solid #0B62C4; padding: 7px 9px;
}}
QLineEdit:disabled, QComboBox:disabled {{ background: #EEF1F4; color: #8A93A0; }}
QLabel#fieldError {{ color: {c['danger']}; font-size: 12px; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
  background: {c['surface']}; border: 1px solid {c['border']};
  selection-background-color: #E4EAF1; selection-color: {c['text']};
}}

/* ---------- tables ---------- */
QTableWidget, QTableView, QTreeWidget {{
  background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px;
  gridline-color: transparent; selection-background-color: #DCE9F7;
  selection-color: {c['text']}; alternate-background-color: #F7F9FB;
}}
QHeaderView::section {{
  background: {c['surface']}; color: {c['muted']}; font-size: 12px; font-weight: 600;
  border: none; border-bottom: 2px solid {c['primary']}; padding: 8px 10px;
}}
QTableWidget::item, QTableView::item {{ padding: 6px 10px; border-bottom: 1px solid #EEF1F4; }}
QTableWidget::item:hover, QTableView::item:hover {{ background: #EEF4FA; }}

/* ---------- tabs / pills / badges ---------- */
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 8px; background: {c['surface']}; }}
QTabBar::tab {{
  padding: 8px 16px; color: {c['muted']}; border: none;
  border-bottom: 2px solid transparent; font-size: 14px;
}}
QTabBar::tab:selected {{ color: {c['primary']}; font-weight: 600; border-bottom: 2px solid {c['accent']}; }}
QLabel.badge {{ border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; }}

/* ---------- status bar / scroll / menus ---------- */
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C6CDD6; border-radius: 5px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #A9B2BD; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #C6CDD6; border-radius: 5px; min-width: 32px; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 8px 16px; border-radius: 6px; }}
QMenu::item:selected {{ background: #E4EAF1; }}

/* ---------- toasts ---------- */
QFrame#toast {{ border-radius: 8px; padding: 10px 16px; font-size: 14px; }}
QFrame#toast[kind="success"] {{ background: {c['success-bg']}; color: {c['success']}; border: 1px solid #7BC48A; }}
QFrame#toast[kind="warning"] {{ background: {c['warning-bg']}; color: {c['warning']}; border: 1px solid #E0B64A; }}
QFrame#toast[kind="error"]   {{ background: {c['danger-bg']};  color: {c['danger']};  border: 1px solid #D77777; }}
QFrame#toast[kind="info"]    {{ background: #DCE9F7; color: {c['primary']}; border: 1px solid #9DB8D4; }}

/* ---------- banners ---------- */
QFrame#bannerDanger {{ background: {c['danger-bg']}; border: 1px solid #CC6666; border-radius: 8px; padding: 10px 16px; }}
QFrame#bannerInfo {{ background: #EEF4FA; border: 1px solid #9DB8D4; border-radius: 8px; padding: 10px 16px; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QToolTip {{ background: {c['primary']}; color: #FFFFFF; border: none; padding: 6px 8px; border-radius: 4px; }}
"""


def apply(app: QApplication) -> None:
    app.setStyleSheet(qss())
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(COLORS["surface"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(COLORS["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(COLORS["primary"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(COLORS["text"]))
    app.setPalette(pal)
    app.setApplicationName("Firmabok")
    app.setOrganizationName("Firmabok")


_icon_cache: dict[str, QIcon] = {}


def icon(name: str, color: str | None = None) -> QIcon:
    """Load a bundled SVG icon by base name (Lucide family), with optional
    recolor. Falls back to an empty QIcon if the file is missing (never a
    broken image)."""
    key = f"{name}:{color or ''}"
    if key in _icon_cache:
        return _icon_cache[key]
    path = RES / "icons" / f"{name}.svg"
    ic = QIcon()
    if path.exists():
        svg = path.read_text(encoding="utf-8")
        if color:
            svg = svg.replace('stroke="currentColor"', f'stroke="{color}"')
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pix = QPixmap(48, 48)
        pix.fill(QColor("#00000000"))
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        ic = QIcon(pix)
    _icon_cache[key] = ic
    return ic
