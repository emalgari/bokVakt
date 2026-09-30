"""UI smoke: quarterly overview page renders 4 rows, SV/EN labels, filing toggle buttons."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMainWindow

from firmabok.i18n import i18n
from firmabok.ui.context import AppContext
from firmabok.ui.pages.quarterly_vat import QuarterlyVatPage


@pytest.fixture()
def page(qapp, qtbot, db):
    win = QMainWindow()
    ctx = AppContext(win)
    p = QuarterlyVatPage(ctx)
    p.year_spin.setValue(2026)
    p.reload()
    qtbot.addWidget(p)
    yield p
    i18n.unsubscribe(p.retranslate)
    win.deleteLater()


def test_four_quarter_rows(page):
    assert page.table.table.rowCount() == 4
    first = page.table.table.item(0, 0).text()
    assert "1" in first


def test_labels_translate(page):
    # set_language notifies all subscribers (buttons AND DataTable headers)
    i18n.set_language("en")
    try:
        assert page.btn_file.text() == "Mark as filed"
        assert page.table.table.horizontalHeaderItem(2).text() == "Output VAT"
    finally:
        i18n.set_language("sv")
    assert page.btn_file.text() == "Markera som inlämnad"
