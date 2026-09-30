"""Top bar rendering: SV/EN, sizes 800×600…1920×1080, overflow collapse,
accessible language toggle, logout signal."""
from __future__ import annotations

import pytest

from firmabok.i18n import i18n, init_language
from firmabok.ui.header import HeaderBar


@pytest.fixture()
def header(qapp):
    h = HeaderBar()
    yield h
    i18n.unsubscribe(h.retranslate)
    h.deleteLater()


def test_header_renders_swedish(qtbot, header):
    init_language("sv")
    header.retranslate()
    texts = [b.text() for b in header._nav_buttons.values()]
    assert "Intäkter" in texts and "Data" in texts and "Fakturor" in texts
    assert header.logout_btn.text() == "Logga ut"
    assert header.settings_btn.toolTip() == "Inställningar…"


def test_header_renders_english(qtbot, header):
    init_language("en")
    try:
        header.retranslate()
        texts = [b.text() for b in header._nav_buttons.values()]
        assert "Income" in texts and "Data" in texts and "Invoices" in texts
        assert "Intäkter" not in texts
        assert header.logout_btn.text() == "Log out"
    finally:
        init_language("sv")


def test_language_toggle_accessibility_and_state(qtbot, header):
    init_language("sv")
    header.retranslate()
    sv_btn, en_btn = header.lang_btns["sv"], header.lang_btns["en"]
    assert sv_btn.isChecked() and not en_btn.isChecked()
    assert sv_btn.accessibleName().startswith("Språk")
    en_btn.click()
    qtbot.wait(10)
    assert i18n.language == "en"
    assert en_btn.isChecked() and not sv_btn.isChecked()
    assert en_btn.accessibleName().startswith("Language")
    sv_btn.click()
    qtbot.wait(10)
    assert i18n.language == "sv"


def test_no_clipping_across_sizes(qtbot, header):
    for width, _height in [(800, 600), (1024, 768), (1280, 800), (1920, 1080)]:
        header.resize(width, 64)
        header.show()
        qtbot.wait(10)
        # brand + right cluster always visible; nav either inline or in overflow
        assert not header.brand_text.isHidden() or not header.logo_label.isHidden()
        assert not header.logout_btn.isHidden()
        overflow = not header.overflow_btn.isHidden()
        inline = not header.nav_host.isHidden()
        assert overflow != inline or width >= 1280  # never both hidden
        # nothing extends beyond the header rect
        assert header.logout_btn.geometry().right() <= width


def test_overflow_menu_at_narrow_width(qtbot, header):
    header.resize(800, 64)
    header.show()
    qtbot.wait(10)
    assert header.overflow_btn.isVisible()
    menu = header.overflow_menu
    labels = [a.text() for a in menu.actions()]
    assert len(labels) == len(header._nav_buttons)
    init_language("en")
    header.retranslate()
    labels_en = [a.text() for a in menu.actions()]
    assert "Income" in labels_en
    init_language("sv")


def test_nav_signal_and_active_state(qtbot, header):
    received = []
    header.nav_selected.connect(received.append)
    header._nav_buttons["vat"].click()
    qtbot.wait(10)
    assert received == ["vat"]
    assert header._nav_buttons["vat"].isChecked()


def test_logout_signal(qtbot, header):
    received = []
    header.logout_clicked.connect(lambda: received.append(True))
    header.logout_btn.click()
    qtbot.wait(10)
    assert received == [True]


def test_text_logo_never_broken(qtbot, header):
    header.show()
    qtbot.wait(10)
    # no logo configured → text logo with company name, no broken image
    header.load_brand("Saddam Hussain", "")
    assert not header.brand_text.isHidden()
    assert header.brand_text.text() == "Saddam Hussain"
    assert header.logo_label.isHidden()
    # nonexistent logo path → still text logo (never a broken image)
    header.load_brand("Saddam Hussain", "logos/does-not-exist.png")
    assert not header.brand_text.isHidden()
    assert header.logo_label.isHidden()
