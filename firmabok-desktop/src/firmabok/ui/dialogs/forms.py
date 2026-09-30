"""Form dialogs: income, expense, customer, owner transaction, invoice editor.

All strings go through tr(); all money stays Decimal; validation errors are
shown inline under the offending field (keyed translations).
"""
from __future__ import annotations

import secrets
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core import config as core_config
from ...core import vat as vatmod
from ...core.errors import DomainError
from ...core.invoices import recalc_invoice, recalc_line
from ...core.models import (
    Customer,
    Employee,
    Expense,
    ExpenseCategory,
    GigPlatform,
    IncomeEntry,
    Invoice,
    InvoiceLine,
    Vehicle,
)
from ...core.money import ZERO, net_from_gross, q2, vat_amount
from ...core.swedish import normalize_org_nr, normalize_vat_number
from ...i18n import i18n, tr
from .. import theme
from ..widgets.forms import LabeledField, MoneyEdit, date_edit, date_of, parse_money

MAX_RECEIPT_BYTES = 10 * 1024 * 1024
RECEIPT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                 ".webp": "image/webp", ".heic": "image/heic", ".pdf": "application/pdf"}


class BaseDialog(QDialog):
    def __init__(self, title_key: str, parent=None):
        super().__init__(parent)
        self._title_key = title_key
        self.setMinimumWidth(560)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Spara"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))
        self._buttons.accepted.connect(self.on_accept)
        self._buttons.rejected.connect(self.reject)
        self._root = QVBoxLayout(self)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(tr(self._title_key))
        self._buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Spara"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))

    def on_accept(self) -> None:  # pragma: no cover - overridden
        self.accept()

    def _add_buttons(self) -> None:
        self._root.addStretch(1)
        self._root.addWidget(self._buttons)

    def reject(self) -> None:
        i18n.unsubscribe(self.retranslate)
        super().reject()

    def accept(self) -> None:
        i18n.unsubscribe(self.retranslate)
        super().accept()


def _vat_code_combo(side: str, current: str) -> QComboBox:
    cb = QComboBox()
    registry = vatmod.SALE_CODES if side == "sale" else vatmod.PURCHASE_CODES
    for info in registry.values():
        cb.addItem(tr(info.label_sv), info.code)
    idx = cb.findData(current)
    cb.setCurrentIndex(idx if idx >= 0 else 0)

    def _rt():
        for i, info in enumerate(registry.values()):
            cb.setItemText(i, tr(info.label_sv))
    i18n.subscribe(_rt)
    return cb


def _rate_from_code(cb: QComboBox) -> Decimal:
    return vatmod.default_rate_for(cb.currentData())


# ---------------------------------------------------------------------------
# Income
# ---------------------------------------------------------------------------

class IncomeDialog(BaseDialog):
    def __init__(self, db, entry: IncomeEntry | None = None, parent=None):
        super().__init__("Registrera intäkt" if entry is None else "Redigera intäkt", parent)
        self.db = db
        self.entry = entry
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.f_date = LabeledField("Datum", date_edit(entry.entry_date if entry else None), required=True)
        self.customers = db.query(Customer).order_by(Customer.name).all()
        self.customer_cb = QComboBox()
        self.customer_cb.addItem(tr("— Ingen / engångskund —"), 0)
        for c in self.customers:
            self.customer_cb.addItem(c.name, c.id)
        if entry and entry.customer_id:
            i = self.customer_cb.findData(entry.customer_id)
            if i >= 0:
                self.customer_cb.setCurrentIndex(i)
        self.f_customer = LabeledField("Kund (register)", self.customer_cb)
        self.name_edit = QLineEdit(entry.customer_name if entry else "")
        self.f_name = LabeledField("Kundnamn (om ej i registret)", self.name_edit)
        self.source_cb = QComboBox()
        self.source_cb.addItem(tr("Direkt kund"), "direct")
        self.source_cb.addItem(tr("Plattform"), "platform")
        if entry and entry.source_type == "platform":
            self.source_cb.setCurrentIndex(1)
        self.f_source = LabeledField("Källa", self.source_cb, help_key="income.aggregate_hint")
        self.platform_cb = QComboBox()
        self.platform_cb.setEditable(True)
        for p in db.query(GigPlatform).order_by(GigPlatform.name).all():
            self.platform_cb.addItem(p.name)
        if entry and entry.platform_name:
            self.platform_cb.setEditText(entry.platform_name)
        self.f_platform = LabeledField("Plattformsnamn", self.platform_cb)
        self.source_cb.currentIndexChanged.connect(self._toggle_platform)
        self._toggle_platform()
        self.desc_edit = QLineEdit(entry.description if entry else "")
        self.f_desc = LabeledField("Beskrivning", self.desc_edit)
        self.code_cb = _vat_code_combo("sale", entry.vat_code if entry else "SE25")
        self.code_cb.currentIndexChanged.connect(
            lambda: self.rate_spin.setValue(int(_rate_from_code(self.code_cb))))
        self.f_code = LabeledField("Momskod", self.code_cb, help_key="momskod.help")
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(0, 25)
        self.rate_spin.setSuffix(" %")
        self.rate_spin.setValue(int(entry.vat_rate) if entry else 25)
        self.f_rate = LabeledField("Momssats %", self.rate_spin)
        self.mode_cb = QComboBox()
        self.mode_cb.addItem(tr("Exkl. moms (netto)"), "net")
        self.mode_cb.addItem(tr("Inkl. moms (brutto)"), "gross")
        self.f_mode = LabeledField("Ange belopp som", self.mode_cb)
        self.amount_edit = MoneyEdit()
        if entry:
            self.amount_edit.set_decimal(entry.net_amount)
        self.f_amount = LabeledField("Belopp (kr)", self.amount_edit, required=True,
                                     help_key="Moms och totalsumma räknas automatiskt (halvöresavrundning per rad).")
        self.status_cb = QComboBox()
        for value, key in (("unpaid", "Obetald"), ("paid", "Betald"), ("partial", "Delbetald")):
            self.status_cb.addItem(tr(key), value)
        if entry:
            self.status_cb.setCurrentIndex(max(0, self.status_cb.findData(entry.payment_status)))
        self.f_status = LabeledField("Betalstatus", self.status_cb)
        self.paid_date = date_edit(entry.payment_date if entry and entry.payment_date else None)
        self.f_paid_date = LabeledField("Betalningsdatum", self.paid_date,
                                        help_key="bokslut.help.betalningsdatum")
        self.ref_edit = QLineEdit(entry.invoice_ref if entry else "")
        self.f_ref = LabeledField("Fakturareferens", self.ref_edit)
        self.notes = QTextEdit(entry.notes if entry else "")
        self.notes.setMaximumHeight(64)
        self.f_notes = LabeledField("Anteckningar", self.notes)

        rows = [(self.f_date, 0, 0), (self.f_customer, 0, 1), (self.f_name, 1, 0),
                (self.f_desc, 1, 1), (self.f_code, 2, 0), (self.f_rate, 2, 1),
                (self.f_mode, 3, 0), (self.f_amount, 3, 1), (self.f_status, 4, 0),
                (self.f_paid_date, 4, 1), (self.f_ref, 5, 0), (self.f_notes, 5, 1),
                (self.f_source, 6, 0), (self.f_platform, 6, 1)]
        for w, r, c in rows:
            grid.addWidget(w, r, c)
        self._root.addLayout(grid)
        self._add_buttons()
        i18n.subscribe(self._rt_combos)

    def _toggle_platform(self) -> None:
        show = self.source_cb.currentData() == "platform"
        self.f_platform.setVisible(show)

    def _rt_combos(self):
        self.customer_cb.setItemText(0, tr("— Ingen / engångskund —"))
        self.source_cb.setItemText(0, tr("Direkt kund"))
        self.source_cb.setItemText(1, tr("Plattform"))
        for i, key in enumerate(("Exkl. moms (netto)", "Inkl. moms (brutto)")):
            self.mode_cb.setItemText(i, tr(key))
        for i, key in enumerate(("Obetald", "Betald", "Delbetald")):
            self.status_cb.setItemText(i, tr(key))

    def on_accept(self) -> None:
        self.f_amount.set_error(None)
        amount = self.amount_edit.decimal()
        if amount is None or amount == 0:
            self.f_amount.set_error("Ogiltigt belopp.")
            return
        cid = self.customer_cb.currentData() or None
        cust = self.db.get(Customer, cid) if cid else None
        name = cust.name if cust else self.name_edit.text().strip()
        if not name:
            self.f_name.set_error("Ange kund (välj ur listan eller skriv namn).")
            return
        self.f_name.set_error(None)
        mode = self.mode_cb.currentData()
        rate = Decimal(self.rate_spin.value())
        code = self.code_cb.currentData()
        info = vatmod.get_code(code)
        if info.side == "sale" and not info.domestic_sale_vat:
            rate = ZERO
        if mode == "gross":
            net = net_from_gross(amount, rate)
            vat = q2(amount - net)
            gross = q2(amount)
        else:
            net = q2(amount)
            vat = vat_amount(net, rate)
            gross = q2(net + vat)
        status = self.status_cb.currentData()
        target = self.entry or IncomeEntry()
        target.entry_date = date_of(self.f_date.widget)
        target.customer_id = cust.id if cust else None
        target.customer_name = name
        target.description = self.desc_edit.text().strip()
        target.vat_code = code
        target.net_amount, target.vat_rate, target.vat_amount, target.gross_amount = net, rate, vat, gross
        target.payment_status = status
        target.payment_date = date_of(self.f_paid_date.widget) if status == "paid" else None
        target.invoice_ref = self.ref_edit.text().strip()
        target.notes = self.notes.toPlainText().strip()
        target.source_type = self.source_cb.currentData()
        if target.source_type == "platform":
            target.platform_name = self.platform_cb.currentText().strip()
            if target.platform_name and not self.db.query(GigPlatform).filter_by(
                    name=target.platform_name).first():
                self.db.add(GigPlatform(name=target.platform_name))
                self.db.flush()
        else:
            target.platform_name = ""
        self.result_entry = target
        self.accept()


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

class ExpenseDialog(BaseDialog):
    def __init__(self, db, expense: Expense | None = None, parent=None):
        super().__init__("Registrera utgift" if expense is None else "Redigera utgift", parent)
        self.db = db
        self.expense = expense
        self._receipt_tmp: Path | None = None
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        self.f_date = LabeledField("Datum", date_edit(expense.expense_date if expense else None), required=True)
        self.supplier = QLineEdit(expense.supplier if expense else "")
        self.f_supplier = LabeledField("Leverantör", self.supplier, required=True)
        self.method = QLineEdit(expense.payment_method if expense else "")
        self.f_method = LabeledField("Betalningssätt", self.method)
        self.paid_date = date_edit(expense.payment_date if expense and expense.payment_date else None)
        self.f_paid_date = LabeledField("Betalningsdatum", self.paid_date,
                                        help_key="Behövs om du väljer ingående moms per betalningsdatum i Inställningar.")
        cats = db.query(ExpenseCategory).order_by(ExpenseCategory.name).all()
        self.cat_cb = QComboBox()
        self.cat_cb.addItem(tr("— Välj —"), 0)
        for c in cats:
            self.cat_cb.addItem(c.name, c.id)
        if expense and expense.category_id:
            i = self.cat_cb.findData(expense.category_id)
            if i >= 0:
                self.cat_cb.setCurrentIndex(i)
        self.f_cat = LabeledField("Kategori", self.cat_cb)
        self.new_cat = QLineEdit()
        self.f_new_cat = LabeledField("…eller skapa ny kategori", self.new_cat)
        self.desc = QLineEdit(expense.description if expense else "")
        self.f_desc = LabeledField("Beskrivning", self.desc)
        self.code_cb = _vat_code_combo("purchase", expense.vat_code if expense else "SE25_P")
        self.code_cb.currentIndexChanged.connect(
            lambda: self.rate_spin.setValue(int(_rate_from_code(self.code_cb))))
        self.f_code = LabeledField("Momskod", self.code_cb)
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(0, 25)
        self.rate_spin.setSuffix(" %")
        self.rate_spin.setValue(int(expense.vat_rate) if expense else 25)
        self.f_rate = LabeledField("Momssats %", self.rate_spin)
        self.mode_cb = QComboBox()
        self.mode_cb.addItem(tr("Inkl. moms (kvittots totalsumma)"), "gross")
        self.mode_cb.addItem(tr("Exkl. moms (netto)"), "net")
        self.f_mode = LabeledField("Ange belopp som", self.mode_cb)
        self.amount_edit = MoneyEdit()
        if expense:
            self.amount_edit.set_decimal(expense.gross_amount)
        self.f_amount = LabeledField("Belopp (kr)", self.amount_edit, required=True)
        self.deduct_edit = MoneyEdit()
        if expense:
            self.deduct_edit.set_decimal(expense.deductible_vat)
        self.f_deduct = LabeledField("Avdragsgill moms (kr)", self.deduct_edit,
                                     help_key="Minska vid t.ex. representation eller blandad användning.")
        self.receipt_btn = QPushButton(tr("Välj kvitto…"))
        self.receipt_btn.setProperty("kind", "secondary")
        self.receipt_btn.setIcon(theme.icon("paperclip"))
        self.receipt_btn.clicked.connect(self._pick_receipt)
        self.receipt_lbl = QLabel(expense.receipt_original_name if expense and expense.receipt_original_name else "")
        self.receipt_lbl.setObjectName("muted")
        receipt_row = QWidget()
        rr = QHBoxLayout(receipt_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self.receipt_btn)
        rr.addWidget(self.receipt_lbl, 1)
        self.f_receipt = LabeledField("Kvitto (bild/PDF, max 10 MB)", receipt_row)
        self.notes = QTextEdit(expense.notes if expense else "")
        self.notes.setMaximumHeight(56)
        self.f_notes = LabeledField("Anteckningar", self.notes)

        # --- vehicle / employee attribution (feature B) ---
        self.vehicle_cb = QComboBox()
        self.vehicle_cb.addItem(tr("— Ingen —"), 0)
        for v in db.query(Vehicle).order_by(Vehicle.label).all():
            self.vehicle_cb.addItem(f"{v.label} ({v.reg_no})" if v.reg_no else v.label, v.id)
        if expense and expense.vehicle_id:
            i = self.vehicle_cb.findData(expense.vehicle_id)
            if i >= 0:
                self.vehicle_cb.setCurrentIndex(i)
        self.f_vehicle = LabeledField("Fordon", self.vehicle_cb)
        self.employee_cb = QComboBox()
        self.employee_cb.addItem(tr("Ingen anställd"), 0)
        for e in db.query(Employee).order_by(Employee.name).all():
            self.employee_cb.addItem(e.name, e.id)
        if expense and expense.employee_id:
            i = self.employee_cb.findData(expense.employee_id)
            if i >= 0:
                self.employee_cb.setCurrentIndex(i)
        self.f_employee = LabeledField("Anställd", self.employee_cb)
        self.mileage_edit = MoneyEdit()
        if expense and expense.mileage:
            self.mileage_edit.set_decimal(expense.mileage)
        self.f_mileage = LabeledField("Körsträcka (mil)", self.mileage_edit)

        rows = [(self.f_date, 0, 0), (self.f_supplier, 0, 1), (self.f_method, 1, 0),
                (self.f_paid_date, 1, 1), (self.f_cat, 2, 0), (self.f_new_cat, 2, 1),
                (self.f_desc, 3, 0), (self.f_code, 3, 1), (self.f_rate, 4, 0),
                (self.f_mode, 4, 1), (self.f_amount, 5, 0), (self.f_deduct, 5, 1),
                (self.f_receipt, 6, 0), (self.f_notes, 6, 1),
                (self.f_vehicle, 7, 0), (self.f_employee, 7, 1), (self.f_mileage, 8, 0)]
        for w, r, c in rows:
            grid.addWidget(w, r, c)
        self._root.addLayout(grid)
        self._add_buttons()

    def _pick_receipt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Välj kvitto"), str(Path.home()),
            "Bilder/PDF (*.jpg *.jpeg *.png *.webp *.heic *.pdf)")
        if not path:
            return
        p = Path(path)
        if p.stat().st_size > MAX_RECEIPT_BYTES:
            QMessageBox.warning(self, tr("Fel"), tr("Kvittot är större än 10 MB."))
            return
        self._receipt_tmp = p
        self.receipt_lbl.setText(p.name)

    def on_accept(self) -> None:
        amount = self.amount_edit.decimal()
        if amount is None or amount <= 0:
            self.f_amount.set_error("Ogiltigt belopp (ange positivt belopp).")
            return
        self.f_amount.set_error(None)
        code = self.code_cb.currentData()
        rate = Decimal(self.rate_spin.value())
        mode = self.mode_cb.currentData()
        if mode == "gross":
            gross = q2(amount)
            net = net_from_gross(gross, rate)
            vat = q2(gross - net)
        else:
            net = q2(amount)
            vat = vat_amount(net, rate)
            gross = q2(net + vat)
        deductible = self.deduct_edit.decimal()
        deductible = vat if deductible is None else max(ZERO, min(q2(deductible), vat))
        if code == "NON_DEDUCTIBLE_P":
            deductible = ZERO

        cat_id = self.cat_cb.currentData() or None
        cat_name = "Övrigt"
        new_cat_name = self.new_cat.text().strip()
        if cat_id:
            cat = self.db.get(ExpenseCategory, cat_id)
            cat_name = cat.name if cat else "Övrigt"
        elif new_cat_name:
            cat = self.db.query(ExpenseCategory).filter_by(name=new_cat_name).one_or_none()
            if cat is None:
                cat = ExpenseCategory(name=new_cat_name)
                self.db.add(cat)
                self.db.flush()
            cat_id = cat.id
            cat_name = cat.name

        target = self.expense or Expense()
        target.expense_date = date_of(self.f_date.widget)
        target.supplier = self.supplier.text().strip()
        target.description = self.desc.text().strip()
        target.vat_code = code
        target.net_amount, target.vat_rate, target.vat_amount, target.gross_amount = net, rate, vat, gross
        target.deductible_vat = deductible
        target.payment_method = self.method.text().strip()
        target.payment_date = date_of(self.f_paid_date.widget)
        target.category_id = cat_id
        target.category_name = cat_name
        target.notes = self.notes.toPlainText().strip()
        target.vehicle_id = self.vehicle_cb.currentData() or None
        target.employee_id = self.employee_cb.currentData() or None
        target.mileage = self.mileage_edit.decimal()
        if self._receipt_tmp is not None:
            year_dir = core_config.UPLOAD_DIR / "receipts" / str(target.expense_date.year)
            year_dir.mkdir(parents=True, exist_ok=True)
            ext = self._receipt_tmp.suffix.lower()
            stored = f"{date.today():%Y%m%d}-{secrets.token_hex(6)}{ext}"
            shutil.copy2(self._receipt_tmp, year_dir / stored)
            target.receipt_path = f"receipts/{year_dir.name}/{stored}"
            target.receipt_original_name = self._receipt_tmp.name[:250]
        self.result_expense = target
        self.accept()


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

class CustomerDialog(BaseDialog):
    def __init__(self, db, customer: Customer | None = None, parent=None):
        super().__init__("Ny kund" if customer is None else "Redigera kund", parent)
        self.db = db
        self.customer = customer
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        def le(value="", key="", ph=""):
            w = QLineEdit(value)
            if ph:
                w.setPlaceholderText(tr(ph))
            return LabeledField(key, w) if key else w

        self.name = le(customer.name if customer else "", "Namn")
        self.cust_no = le(customer.customer_no if customer else "", "Kundnr")
        self.is_business = QCheckBox(tr("Företag (annan person)"))
        self.is_business.setChecked(customer.is_business if customer else True)
        self.org = le(customer.org_nr if customer else "", "Org.nr / personnr", "XXXXXX-XXXX")
        self.vatn = le(customer.vat_number if customer else "", "EU VAT-nummer", "t.ex. DK12345678")
        self.addr1 = le(customer.address_line1 if customer else "", "Adress")
        self.addr2 = le(customer.address_line2 if customer else "", "Adress 2")
        self.zip = le(customer.postal_code if customer else "", "Postnummer")
        self.city = le(customer.city if customer else "", "Ort")
        self.country = le(customer.country if customer else "Sverige", "Land")
        self.email = le(customer.email if customer else "", "E-post")
        self.phone = le(customer.phone if customer else "", "Telefon")
        self.ref = le(customer.reference if customer else "", "Referensperson")
        fields = [self.name, self.cust_no, None, self.org, self.vatn, self.ref,
                  self.addr1, self.addr2, self.zip, self.city, self.country, self.email, self.phone]
        r, c = 0, 0
        for f in fields:
            if f is None:
                grid.addWidget(self.is_business, r, c)
            else:
                grid.addWidget(f, r, c)
            c += 1
            if c == 2:
                c, r = 0, r + 1
        self._root.addLayout(grid)
        self._add_buttons()
        i18n.subscribe(self._rt)

    def _rt(self):
        self.is_business.setText(tr("Företag (annan person)"))

    def on_accept(self) -> None:
        if not self.name.widget.text().strip():
            self.name.set_error("Namn krävs.")
            return
        self.name.set_error(None)
        target = self.customer or Customer()
        target.name = self.name.widget.text().strip()
        target.customer_no = self.cust_no.widget.text().strip()
        target.is_business = self.is_business.isChecked()
        org = self.org.widget.text().strip()
        if org and target.is_business and sum(ch.isdigit() for ch in org) == 10:
            try:
                target.org_nr = normalize_org_nr(org)
            except DomainError as exc:
                self.org.set_error(exc.key)
                return
        else:
            target.org_nr = org
        self.org.set_error(None)
        vatn = self.vatn.widget.text().strip()
        if vatn:
            try:
                target.vat_number = normalize_vat_number(vatn)
            except DomainError as exc:
                self.vatn.set_error(exc.key)
                return
        else:
            target.vat_number = ""
        self.vatn.set_error(None)
        target.address_line1 = self.addr1.widget.text().strip()
        target.address_line2 = self.addr2.widget.text().strip()
        target.postal_code = self.zip.widget.text().strip()
        target.city = self.city.widget.text().strip()
        target.country = self.country.widget.text().strip() or "Sverige"
        target.email = self.email.widget.text().strip()
        target.phone = self.phone.widget.text().strip()
        target.reference = self.ref.widget.text().strip()
        self.result_customer = target
        self.accept()


# ---------------------------------------------------------------------------
# Owner transaction
# ---------------------------------------------------------------------------

class OwnerDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("Registrera transaktion", parent)
        grid = QGridLayout()
        self.type_cb = QComboBox()
        self.type_cb.addItem(tr("Eget uttag"), "uttag")
        self.type_cb.addItem(tr("Egen insättning"), "insattning")
        self.f_type = LabeledField("Typ", self.type_cb, required=True)
        self.f_date = LabeledField("Datum", date_edit(), required=True)
        self.amount = MoneyEdit()
        self.f_amount = LabeledField("Belopp (kr)", self.amount, required=True)
        self.ref = QLineEdit()
        self.f_ref = LabeledField("Referens", self.ref, help_key="t.ex. överförings-id")
        self.desc = QLineEdit()
        self.f_desc = LabeledField("Beskrivning", self.desc)
        for w, (r, c) in [(self.f_type, (0, 0)), (self.f_date, (0, 1)),
                          (self.f_amount, (1, 0)), (self.f_ref, (1, 1)),
                          (self.f_desc, (2, 0))]:
            grid.addWidget(w, r, c)
        grid.setColumnStretch(2, 1)
        self._root.addLayout(grid)
        notice = QLabel(tr("Ägartransaktioner påverkar varken resultat eller moms."))
        notice.setObjectName("muted")
        notice.setWordWrap(True)
        self._root.addWidget(notice)
        self._notice = notice
        i18n.subscribe(lambda: notice.setText(
            tr("Ägartransaktioner påverkar varken resultat eller moms.")))
        self._add_buttons()

    def on_accept(self) -> None:
        amount = self.amount.decimal()
        if amount is None or amount <= 0:
            self.f_amount.set_error("Ange ett positivt belopp.")
            return
        self.f_amount.set_error(None)
        from ...core.models import OwnerTransaction
        self.result_tx = OwnerTransaction(
            tx_date=date_of(self.f_date.widget),
            tx_type=self.type_cb.currentData(),
            amount=q2(amount),
            description=self.desc.text().strip(),
            reference=self.ref.text().strip(),
        )
        self.accept()


# ---------------------------------------------------------------------------
# Invoice editor (drafts; new or existing)
# ---------------------------------------------------------------------------

class InvoiceEditorDialog(BaseDialog):
    LINE_COLS = ["Art.nr", "Beskrivning", "Antal", "Enhet", "À-pris exkl. moms *", "Momskod", "Sats %"]

    def __init__(self, db, invoice: Invoice | None = None, parent=None):
        super().__init__("Ny faktura" if invoice is None else "Redigera faktura", parent)
        self.db = db
        self.invoice = invoice
        self.setMinimumWidth(860)

        meta = QGridLayout()
        meta.setHorizontalSpacing(16)
        meta.setVerticalSpacing(10)
        self.f_date = LabeledField("Fakturadatum",
                                   date_edit(invoice.invoice_date if invoice else None), required=True)
        self.f_delivery = LabeledField("Leveransdatum",
                                       date_edit(invoice.delivery_date if invoice else None))
        self.customer_cb = QComboBox()
        for c in db.query(Customer).order_by(Customer.name).all():
            self.customer_cb.addItem(c.name, c.id)
        if invoice and invoice.customer_id:
            i = self.customer_cb.findData(invoice.customer_id)
            if i >= 0:
                self.customer_cb.setCurrentIndex(i)
        self.f_customer = LabeledField("Kund", self.customer_cb, required=True)
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setValue(invoice.payment_terms_days if invoice else 30)
        self.f_terms = LabeledField("Betalningsvillkor (dagar)", self.terms)
        self.our_ref = QLineEdit(invoice.our_reference if invoice else "")
        self.f_our_ref = LabeledField("Vår referens", self.our_ref)
        self.cust_ref = QLineEdit(invoice.customer_reference if invoice else "")
        self.f_cust_ref = LabeledField("Er referens", self.cust_ref)
        self.notes = QTextEdit(invoice.notes if invoice else "")
        self.notes.setMaximumHeight(56)
        self.f_notes = LabeledField("Notering", self.notes)
        for w, (r, c) in [(self.f_date, (0, 0)), (self.f_delivery, (0, 1)),
                          (self.f_customer, (0, 2)), (self.f_terms, (1, 0)),
                          (self.f_our_ref, (1, 1)), (self.f_cust_ref, (1, 2)),
                          (self.f_notes, (2, 0))]:
            meta.addWidget(w, r, c)
        meta.setColumnStretch(3, 1)
        self._root.addLayout(meta)

        # lines table
        self.lines = QTableWidget(0, len(self.LINE_COLS))
        self.lines.setHorizontalHeaderLabels([tr(k) for k in self.LINE_COLS])
        self.lines.verticalHeader().setVisible(False)
        self.lines.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.lines.setMinimumHeight(180)
        self._root.addWidget(self.lines)
        row_btns = QHBoxLayout()
        self.add_btn = QPushButton(tr("Lägg till rad"))
        self.add_btn.setProperty("kind", "secondary")
        self.add_btn.setIcon(theme.icon("plus"))
        self.add_btn.clicked.connect(lambda: self._add_line())
        self.remove_btn = QPushButton(tr("Ta bort rad"))
        self.remove_btn.setProperty("kind", "ghost")
        self.remove_btn.setIcon(theme.icon("trash"))
        self.remove_btn.clicked.connect(self._remove_line)
        row_btns.addWidget(self.add_btn)
        row_btns.addWidget(self.remove_btn)
        row_btns.addStretch(1)
        self.totals_lbl = QLabel("")
        self.totals_lbl.setStyleSheet("font-weight:600;")
        row_btns.addWidget(self.totals_lbl)
        self._root.addLayout(row_btns)

        if invoice is None:
            self.finalize_cb = QCheckBox(tr("Fastställ direkt vid sparning (tilldela fakturanummer, klar att skicka)"))
            self.finalize_cb.setChecked(True)
            self._root.addWidget(self.finalize_cb)
            i18n.subscribe(self._rt_finalize)
            self._add_line()
        else:
            self.finalize_cb = None
            for line in invoice.lines:
                self._add_line(line)
        self._add_buttons()
        self.lines.cellChanged.connect(lambda *_: self._update_totals())
        self._update_totals()

    def _rt_finalize(self):
        self.finalize_cb.setText(tr("Fastställ direkt vid sparning (tilldela fakturanummer, klar att skicka)"))

    def _add_line(self, line: InvoiceLine | None = None) -> None:
        r = self.lines.rowCount()
        self.lines.insertRow(r)
        self.lines.setItem(r, 0, QTableWidgetItem(line.article_no if line else ""))
        self.lines.setItem(r, 1, QTableWidgetItem(line.description if line else ""))
        self.lines.setItem(r, 2, QTableWidgetItem(str(line.quantity) if line else "1"))
        self.lines.setItem(r, 3, QTableWidgetItem(line.unit if line else "st"))
        price = MoneyEdit()
        if line:
            price.set_decimal(line.unit_price)
        self.lines.setCellWidget(r, 4, price)
        self.lines.setCellWidget(r, 5, _vat_code_combo("sale", line.vat_code if line else "SE25"))
        rate = QSpinBox()
        rate.setRange(0, 25)
        rate.setSuffix(" %")
        rate.setValue(int(line.vat_rate) if line else 25)
        self.lines.setCellWidget(r, 6, rate)
        cb: QComboBox = self.lines.cellWidget(r, 5)
        cb.currentIndexChanged.connect(lambda _i, rt=rate, c=cb: rt.setValue(int(vatmod.default_rate_for(c.currentData()))))

    def _remove_line(self) -> None:
        r = self.lines.currentRow()
        if r >= 0:
            self.lines.removeRow(r)
            self._update_totals()

    def _row_values(self, r: int) -> dict | None:
        desc = (self.lines.item(r, 1).text().strip() if self.lines.item(r, 1) else "")
        price_w: MoneyEdit = self.lines.cellWidget(r, 4)
        price = price_w.decimal()
        if not desc and price is None:
            return None
        qty = parse_money(self.lines.item(r, 2).text() if self.lines.item(r, 2) else "1") or Decimal(1)
        rate_w: QSpinBox = self.lines.cellWidget(r, 6)
        return {
            "article_no": self.lines.item(r, 0).text().strip() if self.lines.item(r, 0) else "",
            "description": desc, "quantity": qty,
            "unit": (self.lines.item(r, 3).text().strip() or "st") if self.lines.item(r, 3) else "st",
            "unit_price": q2(price or ZERO),
            "vat_code": self.lines.cellWidget(r, 5).currentData(),
            "vat_rate": Decimal(rate_w.value()),
        }

    def _update_totals(self) -> None:
        from ...i18n import fmt
        net = vat = ZERO
        for r in range(self.lines.rowCount()):
            v = self._row_values(r)
            if not v:
                continue
            ln = q2(v["quantity"] * v["unit_price"])
            info = vatmod.get_code(v["vat_code"])
            lv = vat_amount(ln, v["vat_rate"]) if info.domestic_sale_vat else ZERO
            net += ln
            vat += lv
        gross = q2(net + vat)
        self.totals_lbl.setText(
            f"{tr('Summa exkl. moms')}: {fmt.money(net)}    {tr('Moms')}: {fmt.money(vat)}    "
            f"{tr('Summa inkl. moms')}: {fmt.money(gross)}")

    def on_accept(self) -> None:
        rows = [v for r in range(self.lines.rowCount()) if (v := self._row_values(r))]
        if not rows:
            QMessageBox.warning(self, tr("Fel"), tr("Lägg till minst en fakturarad med beskrivning och pris."))
            return
        if self.customer_cb.count() == 0:
            QMessageBox.warning(self, tr("Fel"), tr("Välj en registrerad kund på intäkten innan faktura skapas (engångskunder: lägg upp dem under Kunder)."))
            return
        inv = self.invoice or Invoice(status="draft")
        if self.invoice is None:
            self.db.add(inv)
        inv.invoice_date = date_of(self.f_date.widget)
        dd = date_of(self.f_delivery.widget)
        inv.delivery_date = dd or inv.invoice_date
        inv.customer_id = self.customer_cb.currentData()
        inv.payment_terms_days = self.terms.value()
        inv.our_reference = self.our_ref.text().strip()
        inv.customer_reference = self.cust_ref.text().strip()
        inv.notes = self.notes.toPlainText().strip()
        inv.lines.clear()
        self.db.flush()
        for i, v in enumerate(rows):
            line = InvoiceLine(position=i, article_no=v["article_no"], description=v["description"],
                               quantity=v["quantity"], unit=v["unit"], unit_price=v["unit_price"],
                               vat_code=v["vat_code"], vat_rate=v["vat_rate"])
            recalc_line(line)
            inv.lines.append(line)
        self.db.flush()
        from ...core.invoices import get_profile
        recalc_invoice(inv, round_to_krona=bool(get_profile(self.db).round_total_to_krona))
        self.result_invoice = inv
        self.result_finalize = bool(self.finalize_cb and self.finalize_cb.isChecked())
        self.accept()
