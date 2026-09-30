"""Language switching across every page: no Swedish leakage in EN mode,
no English leakage in SV mode; switch applies immediately (no restart)."""
from __future__ import annotations

import pytest

from firmabok.i18n import i18n, init_language
from firmabok.ui.app import MainWindow

SV_MARKERS = {
    "dashboard": ["Månadsöversikt"],
    "income": ["Intäkter"],
    "expenses": ["Utgifter"],
    "vat": ["Momsredovisning"],
    "invoices": ["Fakturor"],
    "customers": ["Kunder"],
    "owner": ["Ägarfinanser"],
    "reports": ["Rapporter"],
    "data": ["Granskningslogg"],
}
EN_MARKERS = {
    "dashboard": ["Monthly overview"],
    "income": ["Income"],
    "expenses": ["Expenses"],
    "vat": ["VAT return"],
    "invoices": ["Invoices"],
    "customers": ["Customers"],
    "owner": ["Owner"],
    "reports": ["Reports"],
    "data": ["Audit log"],
}
SV_FORBIDDEN_IN_EN = ["Intäkter", "Utgifter", "Månadsöversikt", "Granskningslogg",
                      "Momsredovisning", "Kunder", "Rapporter", "Ägarfinanser"]


@pytest.fixture()
def win(qapp, qtbot):
    init_language("sv")
    w = MainWindow()
    qtbot.addWidget(w)
    w.show_content()
    yield w
    init_language("sv")
    w.close()


def _all_text(widget) -> str:
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget
    parts = []
    for child in widget.findChildren(QWidget):
        if isinstance(child, (QLabel, QAbstractButton)):
            t = child.text()
            if t:
                parts.append(t)
    # table headers
    from PySide6.QtWidgets import QTableWidget
    for table in widget.findChildren(QTableWidget):
        for i in range(table.columnCount()):
            item = table.horizontalHeaderItem(i)
            if item:
                parts.append(item.text())
    return "\n".join(parts)


def test_every_page_switches_language(qtbot, win):
    for page_id, sv_markers in SV_MARKERS.items():
        win.go_page(page_id)
        qtbot.wait(10)
        page = win._pages[page_id]
        i18n.set_language("sv")
        sv_text = _all_text(page)
        for marker in sv_markers:
            assert marker in sv_text, f"{page_id}: SV marker saknas: {marker}"

        i18n.set_language("en")  # immediate switch, no restart
        qtbot.wait(10)
        en_text = _all_text(page)
        en_markers = EN_MARKERS[page_id]
        for marker in en_markers:
            assert marker in en_text, f"{page_id}: EN marker missing: {marker}"
        for forbidden in SV_FORBIDDEN_IN_EN:
            assert forbidden not in en_text, f"{page_id}: Swedish leaked in EN: {forbidden}"
    init_language("sv")


def test_header_and_menus_switch_with_pages(qtbot, win):
    i18n.set_language("en")
    qtbot.wait(10)
    assert win.menu_file.title() == "File"
    assert win.act_settings.text() == "Settings…"
    assert win.header.logout_btn.text() == "Log out"
    i18n.set_language("sv")
    qtbot.wait(10)
    assert win.menu_file.title() == "Arkiv"
    assert win.act_settings.text() == "Inställningar…"
    assert win.header.logout_btn.text() == "Logga ut"


def test_language_persists_in_settings(qtbot, win):
    from firmabok.core import config as core_config
    i18n.set_language("en")
    qtbot.wait(10)
    st = core_config.Settings()  # fresh read from disk
    assert st.get("language") == "en"
    i18n.set_language("sv")
    qtbot.wait(10)
    st = core_config.Settings()
    assert st.get("language") == "sv"


def test_navigation_shows_requested_page(qtbot, win):
    """Regression: stacked widget must actually switch to the chosen page."""
    for page_id in ("income", "invoices", "vat", "dashboard"):
        win.go_page(page_id)
        qtbot.wait(10)
        assert win.pages.currentWidget() is win._page_scrolls[page_id]
        assert win._page_scrolls[page_id].widget() is win._pages[page_id]
        assert win.header._nav_buttons[page_id].isChecked()
