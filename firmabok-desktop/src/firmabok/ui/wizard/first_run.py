"""First-run setup wizard — onboards any new user: language, data location
(+ optional one-time import), company profile, bookkeeping/VAT, invoice
defaults, optional app password. All strings via tr(); all validation via
keyed domain errors."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ...core import config as core_config
from ...core.auth import hash_password
from ...core.db import get_session_factory
from ...core.errors import DomainError
from ...core.invoices import get_profile
from ...core.swedish import normalize_org_nr, normalize_vat_number, vat_matches_org_nr
from ...i18n import i18n, month_name, tr
from ..widgets.forms import LabeledField

IMPORT_TABLES = [
    "customers", "expense_categories", "income_entries", "expenses",
    "invoice_series", "invoices", "invoice_lines", "owner_transactions",
    "vat_reports", "company_profile", "audit_log",
]


class LanguagePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.rb_sv = QRadioButton("Svenska")
        self.rb_en = QRadioButton("English")
        self.rb_sv.setChecked(i18n.language == "sv")
        self.rb_en.setChecked(i18n.language == "en")
        self.rb_sv.toggled.connect(lambda on: on and i18n.set_language("sv"))
        self.rb_en.toggled.connect(lambda on: on and i18n.set_language("en"))
        lay.addWidget(self.rb_sv)
        lay.addWidget(self.rb_en)
        lay.addStretch(1)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Språk"))
        self.setSubTitle(tr("Välj språk för hela programmet. Faktura-PDF:er är alltid på svenska."))


class WelcomePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.body = QLabel()
        self.body.setWordWrap(True)
        lay.addWidget(self.body)
        lay.addStretch(1)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Välkommen till Firmabok"))
        self.setSubTitle(tr("Lokal bokföring för enskild firma"))
        self.body.setText(
            tr("Firmabok är ett lokalt bokföringsprogram för enskild firma: intäkter, utgifter, "
               "moms (SKV 4700), fakturor med PDF, rapporter och säkerhetskopior. All data "
               "stannar på din dator. Licens: MIT.")
            + "\n\n" + tr("Moms beräknas på försäljning, aldrig på vinst."))


class DataPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.paths_lbl = QLabel()
        self.paths_lbl.setWordWrap(True)
        self.paths_lbl.setObjectName("muted")
        lay.addWidget(self.paths_lbl)
        self.rb_new = QRadioButton()
        self.rb_import = QRadioButton()
        self.rb_new.setChecked(True)
        lay.addWidget(self.rb_new)
        lay.addWidget(self.rb_import)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("/path/to/firma.db")
        self.browse = QPushButton_browse()
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(self.browse)
        lay.addLayout(row)
        self.preview_lbl = QLabel("")
        self.preview_lbl.setObjectName("muted")
        self.preview_lbl.setWordWrap(True)
        lay.addWidget(self.preview_lbl)
        lay.addStretch(1)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Databas & import"))
        self.setSubTitle(tr("Var ska din bokföring lagras?"))
        self.paths_lbl.setText(f"{tr('Databas')}: {core_config.DB_PATH}\n"
                               f"{tr('Uppladdade filer')}: {core_config.UPLOAD_DIR}")
        self.rb_new.setText(tr("Ny databas (rekommenderat för nya användare)"))
        self.rb_import.setText(tr("Importera från en annan Firmabok-databas (engångsimport)"))
        self.browse.setText(tr("Bläddra…"))

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Välj databasfil"), str(Path.home()),
                                              "SQLite (*.db);;Alla filer (*)")
        if path:
            self.path_edit.setText(path)
            self._preview(path)

    def _preview(self, path: str):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            counts = []
            for t in ("income_entries", "expenses", "invoices", "customers"):
                try:
                    n = con.execute(f"select count(*) from {t}").fetchone()[0]
                    counts.append(f"{t}: {n}")
                except sqlite3.Error:
                    pass
            con.close()
            self.preview_lbl.setText(tr("Förhandsvisning") + ": " + ", ".join(counts) if counts else "")
        except sqlite3.Error:
            self.preview_lbl.setText(tr("Kunde inte läsa filen."))

    def validatePage(self):  # noqa: N802
        if self.rb_import.isChecked():
            self._preview(self.path_edit.text())
        return True


class CompanyPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self.name = QLineEdit()
        self.org = QLineEdit(); self.org.setPlaceholderText("XXXXXX-XXXX")
        self.vatn = QLineEdit(); self.vatn.setPlaceholderText("SE123456789001")
        self.fskatt = QCheckBox()
        self.addr1 = QLineEdit(); self.addr2 = QLineEdit()
        self.zip = QLineEdit(); self.city = QLineEdit()
        self.country = QLineEdit("Sverige")
        self.phone = QLineEdit(); self.email = QLineEdit(); self.website = QLineEdit()
        self.bank_name = QLineEdit(); self.bankgiro = QLineEdit(); self.plusgiro = QLineEdit()
        self.iban = QLineEdit(); self.bic = QLineEdit(); self.account = QLineEdit()
        self.business = QLineEdit(); self.sni = QLineEdit()
        fields = [
            ("Företagsnamn", self.name), ("Organisationsnummer (XXXXXX-XXXX)", self.org),
            ("Momsreg.nr (SE + orgnr + 01)", self.vatn), (None, self.fskatt),
            ("Adress", self.addr1), ("Adress 2", self.addr2),
            ("Postnummer", self.zip), ("Ort", self.city),
            ("Land", self.country), ("Telefon", self.phone),
            ("E-post", self.email), ("Webbplats", self.website),
            ("Bank", self.bank_name), ("Bankgiro", self.bankgiro),
            ("Plusgiro", self.plusgiro), ("IBAN", self.iban),
            ("BIC", self.bic), ("Kontonummer (bankkonto)", self.account),
            ("Verksamhet (beskrivning)", self.business), ("SNI-koder", self.sni),
        ]
        self._fields = []
        r, c = 0, 0
        for key, w in fields:
            if key is None:
                self.grid.addWidget(w, r, c)
                self._fields.append((None, None))
            else:
                f = LabeledField(key, w)
                self.grid.addWidget(f, r, c)
                self._fields.append((key, f))
            c += 1
            if c == 2:
                c, r = 0, r + 1
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Företagsprofil"))
        self.setSubTitle(tr("Dessa uppgifter visas på dina fakturor."))
        self.fskatt.setText(tr("Registrerad för F-skatt"))
        for _key, f in self._fields:
            if f is not None:
                f.retranslate()

    def validatePage(self):  # noqa: N802
        for _key, f in self._fields:
            if f is not None:
                f.set_error(None)
        if not self.name.text().strip():
            self._fields[0][1].set_error("Namn krävs.")
            return False
        if self.org.text().strip():
            try:
                self.org.setText(normalize_org_nr(self.org.text()))
            except DomainError as exc:
                self._fields[1][1].set_error(exc.key)
                return False
        if self.vatn.text().strip():
            try:
                self.vatn.setText(normalize_vat_number(self.vatn.text()))
                if self.org.text().strip() and not vat_matches_org_nr(self.vatn.text(), self.org.text()):
                    self._fields[2][1].set_error("vatnr.mismatch")
                    return False
            except DomainError as exc:
                self._fields[2][1].set_error(exc.key)
                return False
        return True


class BookkeepingPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.fy = QComboBox()
        for m in range(1, 13):
            self.fy.addItem(tr("Kalenderår (jan–dec)") if m == 1
                            else f"{tr('Brutet år, start')} {month_name(m)}", m)
        self.period = QComboBox()
        for value, key in (("month", "Månadsvis"), ("quarter", "Kvartalsvis"), ("year", "Årsvis")):
            self.period.addItem(tr(key), value)
        self.period.setCurrentIndex(1)
        self.method = QComboBox()
        self.method.addItem(tr("Bokslutsmetoden (kontantmetoden)"), "bokslut")
        self.method.addItem(tr("Fakturametoden (per faktureringsdatum)"), "faktura")
        self.method.setCurrentIndex(0)
        self.input_pay = QCheckBox()
        self.rate = QComboBox()
        for r in (25, 12, 6):
            self.rate.addItem(f"{r} %", r)
        form = QFormLayout()
        self._rows = [
            ("Räkenskapsår", self.fy), ("Momsperiod", self.period),
            ("Redovisningsmetod moms", self.method), ("Standardmomssats", self.rate),
        ]
        for _key, w in self._rows:
            form.addRow(LabeledField(str(_key), w))
        lay.addLayout(form)
        lay.addWidget(self.input_pay)
        note = QLabel(tr("Bokslutsmetoden: utgående moms redovisas när kunden betalat; "
                         "obetalda poster senast i årets sista period."))
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch(1)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Bokföringsinställningar"))
        self.setSubTitle(tr("Stämmer detta med din registrering hos Skatteverket?"))
        self.input_pay.setText(tr("Ingående moms per betalningsdatum"))
        for m in range(1, 13):
            self.fy.setItemText(m - 1, tr("Kalenderår (jan–dec)") if m == 1
                                else f"{tr('Brutet år, start')} {month_name(m)}")
        for i, key in enumerate(("Månadsvis", "Kvartalsvis", "Årsvis")):
            self.period.setItemText(i, tr(key))
        self.method.setItemText(0, tr("Bokslutsmetoden (kontantmetoden)"))
        self.method.setItemText(1, tr("Fakturametoden (per faktureringsdatum)"))


class InvoicePage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        self.terms = QSpinBox(); self.terms.setRange(0, 365); self.terms.setValue(30)
        self.prefix = QLineEdit()
        self.digits = QSpinBox(); self.digits.setRange(2, 8); self.digits.setValue(4)
        self.start = QSpinBox(); self.start.setRange(1, 999999); self.start.setValue(1)
        self.ocr = QCheckBox(); self.ocr.setChecked(True)
        self.pay_display = QComboBox()
        for value, key in (("bankgiro", "Bankgiro"), ("plusgiro", "Plusgiro"),
                           ("bankaccount", "Bankkonto (banknamn + kontonummer)")):
            self.pay_display.addItem(tr(key), value)
        self.late_text = QLineEdit(
            "Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.")
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(56)
        self._rows = [
            ("Betalningsvillkor (dagar)", self.terms), ("Nummerprefix", self.prefix),
            ("Sifferlängd i nummer", self.digits), ("Startnummer (nya serier)", self.start),
            ("Betalningsmottagare på fakturan", self.pay_display),
            ("Dröjsmålsräntetext på fakturan", self.late_text),
            ("Standardnotering på fakturor", self.notes),
        ]
        for _key, w in self._rows:
            form.addRow(LabeledField(str(_key), w))
        form.addRow(self.ocr)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Fakturainställningar"))
        self.setSubTitle(tr("Nummerserien blir t.ex. 2026-0001 (löpande per räkenskapsår, utan luckor)."))
        self.ocr.setText(tr("Visa OCR på fakturan"))
        for i, key in enumerate(("Bankgiro", "Plusgiro", "Bankkonto (banknamn + kontonummer)")):
            self.pay_display.setItemText(i, tr(key))


class FinishPage(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.pw_enable = QCheckBox()
        self.pw1 = QLineEdit(); self.pw1.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw2 = QLineEdit(); self.pw2.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout()
        self._pw1 = LabeledField("Nytt lösenord (minst 8 tecken)", self.pw1)
        self._pw2 = LabeledField("Upprepa nytt", self.pw2)
        form.addRow(self._pw1)
        form.addRow(self._pw2)
        lay.addWidget(self.pw_enable)
        lay.addLayout(form)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("muted")
        lay.addWidget(self.summary)
        lay.addStretch(1)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self):
        self.setTitle(tr("Klar!"))
        self.setSubTitle(tr("Valfritt app-lösenord och sammanfattning"))
        self.pw_enable.setText(tr("Skydda appen med lösenord (låsskärm vid start)"))

    def initializePage(self):  # noqa: N802
        w: FirstRunWizard = self.wizard()
        comp: CompanyPage = w.page(w.P_COMPANY)
        self.summary.setText(
            f"{comp.name.text()} · {comp.org.text() or '—'} · "
            f"{tr('Klar att använda') if True else ''}")


def QPushButton_browse():
    from PySide6.QtWidgets import QPushButton
    b = QPushButton()
    b.setProperty("kind", "secondary")
    return b


class FirstRunWizard(QWizard):
    P_LANG, P_WELCOME, P_DATA, P_COMPANY, P_BOOKKEEPING, P_INVOICE, P_FINISH = range(7)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(720, 560)
        self.setPage(self.P_LANG, LanguagePage())
        self.setPage(self.P_WELCOME, WelcomePage())
        self.setPage(self.P_DATA, DataPage())
        self.setPage(self.P_COMPANY, CompanyPage())
        self.setPage(self.P_BOOKKEEPING, BookkeepingPage())
        self.setPage(self.P_INVOICE, InvoicePage())
        self.setPage(self.P_FINISH, FinishPage())
        self.setButtonText(QWizard.WizardButton.NextButton, tr("Nästa"))
        self.setButtonText(QWizard.WizardButton.BackButton, tr("Föregående"))
        self.setButtonText(QWizard.WizardButton.FinishButton, tr("Slutför"))
        self.setButtonText(QWizard.WizardButton.CancelButton, tr("Avbryt"))
        i18n.subscribe(self.retranslate)
        self.finished.connect(lambda res: self._apply(res))

    def retranslate(self):
        self.setWindowTitle(tr("Första starten — Firmabok"))
        self.setButtonText(QWizard.WizardButton.NextButton, tr("Nästa"))
        self.setButtonText(QWizard.WizardButton.BackButton, tr("Föregående"))
        self.setButtonText(QWizard.WizardButton.FinishButton, tr("Slutför"))
        self.setButtonText(QWizard.WizardButton.CancelButton, tr("Avbryt"))

    # ------------------------------------------------------------- finalize
    def _apply(self, result: int) -> None:
        if result != QWizard.DialogCode.Accepted:
            return
        comp: CompanyPage = self.page(self.P_COMPANY)
        bk: BookkeepingPage = self.page(self.P_BOOKKEEPING)
        inv: InvoicePage = self.page(self.P_INVOICE)
        fin: FinishPage = self.page(self.P_FINISH)
        data: DataPage = self.page(self.P_DATA)

        db = get_session_factory()()
        try:
            p = get_profile(db)
            p.company_name = comp.name.text().strip()
            p.org_nr = comp.org.text().strip()
            p.vat_number = comp.vatn.text().strip()
            p.f_skatt_registered = comp.fskatt.isChecked()
            p.f_skatt_text = tr("Godkänd för F-skatt") if comp.fskatt.isChecked() else ""
            p.address_line1 = comp.addr1.text().strip()
            p.address_line2 = comp.addr2.text().strip()
            p.postal_code = comp.zip.text().strip()
            p.city = comp.city.text().strip()
            p.country = comp.country.text().strip() or "Sverige"
            p.phone = comp.phone.text().strip()
            p.email = comp.email.text().strip()
            p.website = comp.website.text().strip()
            p.bank_name = comp.bank_name.text().strip()
            p.bankgiro = comp.bankgiro.text().strip()
            p.plusgiro = comp.plusgiro.text().strip()
            p.iban = comp.iban.text().strip()
            p.bic = comp.bic.text().strip()
            p.bank_account_number = comp.account.text().strip()
            p.business_description = comp.business.text().strip()
            p.sni_codes = comp.sni.text().strip()

            p.fiscal_year_start_month = bk.fy.currentData()
            p.vat_period = bk.period.currentData()
            p.vat_method = bk.method.currentData()
            p.input_vat_on_payment = bk.input_pay.isChecked()
            p.default_vat_rate = Decimal(bk.rate.currentData())

            p.payment_terms_days = inv.terms.value()
            p.invoice_number_prefix = inv.prefix.text().strip()[:8]
            p.invoice_number_digits = inv.digits.value()
            p.invoice_number_start = inv.start.value()
            p.invoice_show_ocr = inv.ocr.isChecked()
            p.payment_display = inv.pay_display.currentData()
            p.late_interest_text = inv.late_text.text().strip() or p.late_interest_text
            p.invoice_notes = inv.notes.toPlainText().strip()
            db.commit()

            if data.rb_import.isChecked() and data.path_edit.text().strip():
                from ...core.backup import import_from_db
                _counts = import_from_db(data.path_edit.text().strip(), db)
                db.commit()

            if fin.pw_enable.isChecked() and fin.pw1.text() and fin.pw1.text() == fin.pw2.text():
                h, s = hash_password(fin.pw1.text())
                st = core_config.settings()
                st.set("auth.enabled", True)
                st.set("auth.password_hash", h)
                st.set("auth.password_salt", s)
                st.save()

            core_config.settings().set("wizard_completed", True)
            core_config.settings().save()
        finally:
            db.close()
        i18n.unsubscribe(self.retranslate)
