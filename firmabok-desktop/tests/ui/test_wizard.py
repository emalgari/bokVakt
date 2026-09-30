"""First-run wizard: full flow, validation, settings/profile written."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWizard

from firmabok.core import config as core_config
from firmabok.core.db import get_session_factory
from firmabok.core.invoices import get_profile
from firmabok.i18n import init_language
from firmabok.ui.wizard.first_run import FirstRunWizard


@pytest.fixture()
def wizard(qapp, qtbot):
    w = FirstRunWizard()
    qtbot.addWidget(w)
    yield w
    w.deleteLater()


def test_wizard_completes_and_writes_profile(qtbot, wizard):
    # reset flags so the wizard is "first run"
    st = core_config.settings()
    st.set("wizard_completed", False)
    st.save()

    comp = wizard.page(wizard.P_COMPANY)
    comp.name.setText("Test Konsult HB")
    comp.org.setText("556000-1239")  # may fail LUHN — set a valid one instead:
    from firmabok.core.swedish import luhn_check_digit
    base = "556000123"
    comp.org.setText(f"{base[:6]}-{base[6:]}{luhn_check_digit(base)}")
    comp.vatn.setText(f"SE{base}{luhn_check_digit(base)}01")
    comp.fskatt.setChecked(True)
    comp.addr1.setText("Testgatan 1")
    comp.zip.setText("111 11")
    comp.city.setText("Stockholm")
    comp.bankgiro.setText("123,456-7")

    bk = wizard.page(wizard.P_BOOKKEEPING)
    bk.period.setCurrentIndex(bk.period.findData("quarter"))
    bk.method.setCurrentIndex(bk.method.findData("bokslut"))

    inv = wizard.page(wizard.P_INVOICE)
    inv.terms.setValue(10)
    inv.ocr.setChecked(True)
    inv.pay_display.setCurrentIndex(inv.pay_display.findData("bankgiro"))

    assert comp.validatePage() is True
    wizard._apply(QWizard.DialogCode.Accepted)

    db = get_session_factory()()
    try:
        p = get_profile(db)
        assert p.company_name == "Test Konsult HB"
        assert p.org_nr == f"{base[:6]}-{base[6:]}{luhn_check_digit(base)}"
        assert p.vat_number == f"SE{base}{luhn_check_digit(base)}01"
        assert p.f_skatt_registered is True
        assert p.vat_period == "quarter"
        assert p.vat_method == "bokslut"
        assert p.payment_terms_days == 10
        assert p.invoice_show_ocr is True
        assert p.payment_display == "bankgiro"
    finally:
        db.close()
    st2 = core_config.Settings()
    assert st2.get("wizard_completed") is True


def test_wizard_validates_org_nr(qtbot, wizard):
    comp = wizard.page(wizard.P_COMPANY)
    comp.name.setText("X")
    comp.org.setText("123456-7890")  # wrong LUHN
    assert comp.validatePage() is False
    init_language("en")
    comp.validatePage()
    err = comp._fields[1][1].error.text()
    assert "check digit" in err.lower() or "luhn" in err.lower()
    init_language("sv")
    comp.org.setText("")
    assert comp.validatePage() is True


def test_wizard_translates_titles(qtbot, wizard):
    from firmabok.i18n import i18n
    i18n.set_language("en")
    assert wizard.page(wizard.P_LANG).title() == "Language"
    assert wizard.buttonText(QWizard.WizardButton.NextButton) == "Next"
    i18n.set_language("sv")
    assert wizard.page(wizard.P_LANG).title() == "Språk"
    assert wizard.buttonText(QWizard.WizardButton.NextButton) == "Nästa"
