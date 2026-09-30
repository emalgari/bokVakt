"""Settings dialog — mirrors the reference app's sections."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import config as core_config
from ...core.auth import hash_password, verify_password
from ...core.errors import DomainError
from ...core.invoices import get_profile
from ...core.swedish import normalize_org_nr, normalize_vat_number, vat_matches_org_nr
from ...i18n import i18n, tr
from .. import theme
from ..widgets.forms import LabeledField, parse_money


class SettingsDialog(QDialog):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.profile = get_profile(db)
        self.setMinimumWidth(760)
        self._build()
        i18n.subscribe(self.retranslate)
        self.retranslate()

    # ------------------------------------------------------------------ ui
    def _le(self, value: str = "") -> QLineEdit:
        w = QLineEdit(value or "")
        return w

    def _build(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ---- company ----
        comp = QWidget()
        cg = QGridLayout(comp)
        self.company_name = self._le(self.profile.company_name)
        self.org_nr = self._le(self.profile.org_nr)
        self.vat_number = self._le(self.profile.vat_number)
        self.f_skatt = QCheckBox()
        self.f_skatt.setChecked(self.profile.f_skatt_registered)
        self.addr1 = self._le(self.profile.address_line1)
        self.addr2 = self._le(self.profile.address_line2)
        self.zip = self._le(self.profile.postal_code)
        self.city = self._le(self.profile.city)
        self.country = self._le(self.profile.country)
        self.phone = self._le(self.profile.phone)
        self.email = self._le(self.profile.email)
        self.website = self._le(self.profile.website)
        self.business_desc = self._le(self.profile.business_description)
        self.sni = self._le(self.profile.sni_codes)
        self.bank_name = self._le(self.profile.bank_name)
        self.bankgiro = self._le(self.profile.bankgiro)
        self.plusgiro = self._le(self.profile.plusgiro)
        self.iban = self._le(self.profile.iban)
        self.bic = self._le(self.profile.bic)
        self.account_no = self._le(self.profile.bank_account_number)
        self.logo_btn = QPushButton()
        self.logo_btn.setProperty("kind", "secondary")
        self.logo_btn.setIcon(theme.icon("image"))
        self.logo_btn.clicked.connect(self._pick_logo)
        self.logo_state = QLabel("")
        self.logo_state.setObjectName("muted")
        logo_row = QHBoxLayout()
        logo_row.addWidget(self.logo_btn)
        logo_row.addWidget(self.logo_state, 1)
        fields = [
            ("Företagsnamn", self.company_name), ("Organisationsnummer (XXXXXX-XXXX)", self.org_nr),
            ("Momsreg.nr (SE + orgnr + 01)", self.vat_number), (None, self.f_skatt),
            ("Adress", self.addr1), ("Adress 2", self.addr2),
            ("Postnummer", self.zip), ("Ort", self.city),
            ("Land", self.country), ("Telefon", self.phone),
            ("E-post", self.email), ("Webbplats", self.website),
            ("Verksamhet (beskrivning)", self.business_desc), ("SNI-koder", self.sni),
            ("Bank", self.bank_name), ("Bankgiro", self.bankgiro),
            ("Plusgiro", self.plusgiro), ("IBAN", self.iban),
            ("BIC", self.bic), ("Kontonummer (bankkonto)", self.account_no),
        ]
        self._company_fields: list[tuple[str | None, LabeledField | QCheckBox, QWidget]] = []
        r, c = 0, 0
        for key, widget in fields:
            if key is None:
                cg.addWidget(widget, r, c)
                self._company_fields.append((None, None, widget))
            else:
                f = LabeledField(key, widget)
                cg.addWidget(f, r, c)
                self._company_fields.append((key, f, widget))
            c += 1
            if c == 2:
                c, r = 0, r + 1
        cg.addWidget(self.logo_btn, r, 0)
        cg.addWidget(self.logo_state, r, 1)
        tabs.addTab(comp, "")
        self._tab_company = tabs.indexOf(comp)

        # ---- invoice ----
        inv = QWidget()
        ig = QGridLayout(inv)
        self.terms = QSpinBox(); self.terms.setRange(0, 365); self.terms.setValue(self.profile.payment_terms_days)
        self.late_rate = QLineEdit(str(self.profile.late_interest_rate))
        self.late_text = QLineEdit(self.profile.late_interest_text)
        self.prefix = QLineEdit(self.profile.invoice_number_prefix)
        self.digits = QSpinBox(); self.digits.setRange(2, 8); self.digits.setValue(self.profile.invoice_number_digits)
        self.start_no = QSpinBox(); self.start_no.setRange(1, 999999); self.start_no.setValue(self.profile.invoice_number_start)
        self.pay_display = QComboBox()
        for value, key in (("bankgiro", "Bankgiro"), ("plusgiro", "Plusgiro"),
                           ("bankaccount", "Bankkonto (banknamn + kontonummer)")):
            self.pay_display.addItem(tr(key), value)
        self.pay_display.setCurrentIndex(max(0, self.pay_display.findData(self.profile.payment_display)))
        self.show_ocr = QComboBox()
        self.show_ocr.addItem(tr("Ja"), True)
        self.show_ocr.addItem(tr("Nej"), False)
        self.show_ocr.setCurrentIndex(0 if self.profile.invoice_show_ocr else 1)
        self.rounding = QCheckBox()
        self.rounding.setChecked(self.profile.round_total_to_krona)
        self.inv_notes = QTextEdit(self.profile.invoice_notes)
        self.inv_notes.setMaximumHeight(64)
        inv_fields = [
            ("Betalningsvillkor (dagar)", self.terms), ("Dröjsmålsränta (%/år)", self.late_rate),
            ("Betalningsmottagare på fakturan", self.pay_display), ("Visa OCR på fakturan", self.show_ocr),
            ("Nummerprefix", self.prefix), ("Sifferlängd i nummer", self.digits),
            ("Startnummer (nya serier)", self.start_no), ("Dröjsmålsräntetext på fakturan", self.late_text),
            (None, self.rounding), ("Standardnotering på fakturor", self.inv_notes),
        ]
        self._inv_fields = []
        r, c = 0, 0
        for key, widget in inv_fields:
            if key is None:
                ig.addWidget(widget, r, c); self._inv_fields.append((None, None, widget))
            else:
                f = LabeledField(key, widget)
                ig.addWidget(f, r, c); self._inv_fields.append((key, f, widget))
            c += 1
            if c == 2:
                c, r = 0, r + 1
        tabs.addTab(inv, "")
        self._tab_invoice = tabs.indexOf(inv)

        # ---- bookkeeping ----
        bk = QWidget()
        bg = QGridLayout(bk)
        self.fy_month = QComboBox()
        from ...i18n import month_name
        for m in range(1, 13):
            self.fy_month.addItem(
                tr("Kalenderår (jan–dec)") if m == 1 else f"{tr('Brutet år, start')} {month_name(m)}", m)
        self.fy_month.setCurrentIndex(self.profile.fiscal_year_start_month - 1)
        self.vat_period = QComboBox()
        for value, key in (("month", "Månadsvis"), ("quarter", "Kvartalsvis"), ("year", "Årsvis")):
            self.vat_period.addItem(tr(key), value)
        self.vat_period.setCurrentIndex(max(0, self.vat_period.findData(self.profile.vat_period)))
        self.vat_method = QComboBox()
        self.vat_method.addItem(tr("Bokslutsmetoden (kontantmetoden)"), "bokslut")
        self.vat_method.addItem(tr("Fakturametoden (per faktureringsdatum)"), "faktura")
        self.vat_method.setCurrentIndex(max(0, self.vat_method.findData(self.profile.vat_method)))
        self.input_on_payment = QCheckBox()
        self.input_on_payment.setChecked(self.profile.input_vat_on_payment)
        self.default_rate = QComboBox()
        for r0 in (25, 12, 6):
            self.default_rate.addItem(f"{r0} %", r0)
        self.default_rate.setCurrentIndex(max(0, self.default_rate.findData(int(self.profile.default_vat_rate))))
        bk_fields = [
            ("Räkenskapsår", self.fy_month), ("Momsperiod", self.vat_period),
            ("Redovisningsmetod moms", self.vat_method), ("Standardmomssats", self.default_rate),
            (None, self.input_on_payment),
        ]
        self._bk_fields = []
        r, c = 0, 0
        for key, widget in bk_fields:
            if key is None:
                bg.addWidget(widget, r, c); self._bk_fields.append((None, None, widget))
            else:
                f = LabeledField(key, widget)
                bg.addWidget(f, r, c); self._bk_fields.append((key, f, widget))
            c += 1
            if c == 2:
                c, r = 0, r + 1
        bg.setRowStretch(r + 1, 1)
        tabs.addTab(bk, "")
        self._tab_bookkeeping = tabs.indexOf(bk)

        # ---- appearance & language ----
        ap = QWidget()
        av = QFormLayout(ap)
        self.lang_cb = QComboBox()
        self.lang_cb.addItem("Svenska", "sv")
        self.lang_cb.addItem("English", "en")
        self.lang_cb.setCurrentIndex(max(0, self.lang_cb.findData(i18n.language)))
        self.lang_cb.currentIndexChanged.connect(
            lambda: i18n.set_language(self.lang_cb.currentData()))
        av.addRow(LabeledField("Språk", self.lang_cb))
        tabs.addTab(ap, "")
        self._tab_appearance = tabs.indexOf(ap)

        # ---- security ----
        sec = QWidget()
        sv = QFormLayout(sec)
        self.cur_pw = QLineEdit(); self.cur_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw = QLineEdit(); self.new_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw2 = QLineEdit(); self.new_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        sv.addRow(LabeledField("Nuvarande lösenord", self.cur_pw))
        sv.addRow(LabeledField("Nytt lösenord (minst 8 tecken)", self.new_pw))
        sv.addRow(LabeledField("Upprepa nytt", self.new_pw2))
        tabs.addTab(sec, "")
        self._tab_security = tabs.indexOf(sec)

        # ---- lists & payroll/tax defaults (new features) ----
        from .settings_tabs import build_lists_tab
        lists_host, self._lists_retranslatable = build_lists_tab(self.db)
        tabs.addTab(lists_host, "")
        self._tab_lists = tabs.indexOf(lists_host)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Spara"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._buttons = buttons
        self._tabs = tabs

    def _pick_logo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Välj logotyp"), str(core_config.UPLOAD_DIR),
            "Bilder (*.png *.jpg *.jpeg *.svg)")
        if not path:
            return
        import shutil
        from pathlib import Path as P
        dst_dir = core_config.UPLOAD_DIR / "logos"
        dst_dir.mkdir(parents=True, exist_ok=True)
        stored = dst_dir / f"logo-{secrets_hex()}{P(path).suffix.lower()}"
        shutil.copy2(path, stored)
        self.profile.logo_path = f"logos/{stored.name}"
        self.db.commit()
        self.logo_state.setText(stored.name)

    # ----------------------------------------------------------- behaviour
    def retranslate(self) -> None:
        self.setWindowTitle(tr("Inställningar"))
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Spara"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))
        self._tabs.setTabText(self._tab_company, tr("Företagsprofil & bankuppgifter"))
        self._tabs.setTabText(self._tab_invoice, tr("Fakturainställningar"))
        self._tabs.setTabText(self._tab_bookkeeping, tr("Bokföringsinställningar"))
        self._tabs.setTabText(self._tab_appearance, tr("Utseende & språk"))
        self._tabs.setTabText(self._tab_security, tr("Konto & lösenord"))
        self._tabs.setTabText(self._tab_lists, tr("Listor & standardvärden"))
        self.logo_btn.setText(tr("Välj logotyp…"))
        self.f_skatt.setText(tr("Registrerad för F-skatt"))
        self.rounding.setText(tr("Avrunda totalsumma till hela kronor (Avrundning-rad)"))
        self.input_on_payment.setText(tr("Ingående moms per betalningsdatum"))
        from ...i18n import month_name
        for m in range(1, 13):
            self.fy_month.setItemText(
                m - 1,
                tr("Kalenderår (jan–dec)") if m == 1 else f"{tr('Brutet år, start')} {month_name(m)}")
        for i, key in enumerate(("Bankgiro", "Plusgiro", "Bankkonto (banknamn + kontonummer)")):
            self.pay_display.setItemText(i, tr(key))
        self.show_ocr.setItemText(0, tr("Ja"))
        self.show_ocr.setItemText(1, tr("Nej"))
        for i, key in enumerate(("Månadsvis", "Kvartalsvis", "Årsvis")):
            self.vat_period.setItemText(i, tr(key))
        self.vat_method.setItemText(0, tr("Bokslutsmetoden (kontantmetoden)"))
        self.vat_method.setItemText(1, tr("Fakturametoden (per faktureringsdatum)"))

    def _save(self) -> None:
        p = self.profile
        try:
            for t in getattr(self, "_lists_retranslatable", []):
                t.apply()
        except Exception as exc:  # InvalidOperation etc.
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("Fel"), tr("Ogiltigt värde.") + f" ({exc})")
            return
        try:
            if self.org_nr.text().strip():
                p.org_nr = normalize_org_nr(self.org_nr.text())
            else:
                p.org_nr = ""
            if self.vat_number.text().strip():
                p.vat_number = normalize_vat_number(self.vat_number.text())
            else:
                p.vat_number = ""
        except DomainError as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("Fel"), tr(exc.key))
            return
        if p.org_nr and p.vat_number and not vat_matches_org_nr(p.vat_number, p.org_nr):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("Fel"), tr("vatnr.mismatch"))
            return
        p.company_name = self.company_name.text().strip()
        p.f_skatt_registered = self.f_skatt.isChecked()
        p.f_skatt_text = tr("Godkänd för F-skatt") if p.f_skatt_registered else ""
        p.address_line1 = self.addr1.text().strip()
        p.address_line2 = self.addr2.text().strip()
        p.postal_code = self.zip.text().strip()
        p.city = self.city.text().strip()
        p.country = self.country.text().strip() or "Sverige"
        p.phone = self.phone.text().strip()
        p.email = self.email.text().strip()
        p.website = self.website.text().strip()
        p.business_description = self.business_desc.text().strip()
        p.sni_codes = self.sni.text().strip()
        p.bank_name = self.bank_name.text().strip()
        p.bankgiro = self.bankgiro.text().strip()
        p.plusgiro = self.plusgiro.text().strip()
        p.iban = self.iban.text().strip()
        p.bic = self.bic.text().strip()
        p.bank_account_number = self.account_no.text().strip()

        p.payment_terms_days = self.terms.value()
        lir = parse_money(self.late_rate.text())
        if lir is not None and lir >= 0:
            p.late_interest_rate = lir
        p.late_interest_text = self.late_text.text().strip() or (
            "Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.")
        p.invoice_number_prefix = self.prefix.text().strip()[:8]
        p.invoice_number_digits = self.digits.value()
        p.invoice_number_start = self.start_no.value()
        p.payment_display = self.pay_display.currentData()
        p.invoice_show_ocr = bool(self.show_ocr.currentData())
        p.round_total_to_krona = self.rounding.isChecked()
        p.invoice_notes = self.inv_notes.toPlainText().strip()

        p.fiscal_year_start_month = self.fy_month.currentData()
        p.vat_period = self.vat_period.currentData()
        p.vat_method = self.vat_method.currentData()
        p.input_vat_on_payment = self.input_on_payment.isChecked()
        p.default_vat_rate = Decimal(self.default_rate.currentData())

        new_pw = self.new_pw.text()
        if new_pw:
            if len(new_pw) < 8 or new_pw != self.new_pw2.text():
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, tr("Fel"), tr("Lösenordskrav ej uppfyllda."))
                return
            st = core_config.settings()
            auth_enabled = st.get("auth.enabled", False)
            if auth_enabled and not verify_password(self.cur_pw.text(),
                                                    st.get("auth.password_hash", ""),
                                                    st.get("auth.password_salt", "")):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, tr("Fel"), tr("Nuvarande lösenord är fel."))
                return
            h, s = hash_password(new_pw)
            st.set("auth.enabled", True)
            st.set("auth.password_hash", h)
            st.set("auth.password_salt", s)
            st.save()
        self.db.commit()
        self.accept()

    def reject(self) -> None:
        i18n.unsubscribe(self.retranslate)
        super().reject()

    def accept(self) -> None:
        i18n.unsubscribe(self.retranslate)
        super().accept()


def secrets_hex() -> str:
    import secrets
    return secrets.token_hex(4)
