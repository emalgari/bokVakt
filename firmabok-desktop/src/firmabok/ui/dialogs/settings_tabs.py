"""Settings sub-tabs added by the gig/vehicle/payroll feature set.

Everything here is user-configurable: default lists can be renamed or removed,
default rates are clearly labelled defaults and stored in ``TaxParameters``.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select

from ...core.models import (
    Employee,
    ExpenseCategory,
    GigPlatform,
    TaxParameters,
    Vehicle,
)
from ...core.money import q2
from ...i18n import i18n, tr
from ..translatable import Translatable
from ..widgets.forms import LabeledField, parse_money
from ..widgets.tables import DataTable


def _get_params(db) -> TaxParameters:
    p = db.get(TaxParameters, 1)
    if p is None:
        p = TaxParameters(id=1)
        db.add(p)
        db.flush()
    return p


class _ListManager(Translatable):
    """Small editable (id, display) list backed by a table."""

    columns: tuple = ()
    empty_key = ""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = DataTable(self.columns, empty_key=self.empty_key)
        lay.addWidget(self.table, 1)
        btns = QHBoxLayout()
        self.btn_add = QPushButton()
        self.btn_edit = QPushButton()
        self.btn_del = QPushButton()
        self.btn_del.setProperty("kind", "danger")
        for b in (self.btn_add, self.btn_edit, self.btn_del):
            b.setProperty("kind", "secondary")
            b.clicked.connect(lambda _=False, who=b: self._click(who))
            btns.addWidget(b)
        self.btn_del.setProperty("kind", "danger")
        btns.addStretch(1)
        lay.addLayout(btns)
        self.reload()

    def _click(self, btn):
        if btn is self.btn_add:
            self.add_item()
        elif btn is self.btn_edit:
            self.edit_item()
        else:
            self.delete_item()

    def retranslate(self):
        self.btn_add.setText(tr("Lägg till"))
        self.btn_edit.setText(tr("Redigera"))
        self.btn_del.setText(tr("Radera"))
        self.reload()

    # -- overridden by subclasses --
    def reload(self):
        raise NotImplementedError

    def add_item(self):
        raise NotImplementedError

    def edit_item(self):
        raise NotImplementedError

    def delete_item(self):
        raise NotImplementedError


class PlatformManager(_ListManager):
    columns = (("Plattform", "l"), ("Anteckningar", "l"))
    empty_key = "Inga plattformar ännu."

    def reload(self):
        self._items = self.db.execute(select(GigPlatform).order_by(GigPlatform.name)).scalars().all()
        self.table.clear_rows()
        for p in self._items:
            self.table.add_row([p.name, p.notes or ""])
        self.table.refresh_empty_state()

    def _prompt(self, name="", notes=""):
        n, ok1 = QInputDialog.getText(self, tr("Plattform"), tr("Plattformsnamn"), text=name)
        if not ok1 or not n.strip():
            return None
        nt, ok2 = QInputDialog.getText(self, tr("Plattform"), tr("Anteckningar"), text=notes)
        if not ok2:
            return None
        return n.strip(), nt.strip()

    def add_item(self):
        r = self._prompt()
        if not r:
            return
        if self.db.query(GigPlatform).filter_by(name=r[0]).first():
            QMessageBox.warning(self, tr("Fel"), tr("Namnet finns redan.")); return
        self.db.add(GigPlatform(name=r[0], notes=r[1]))
        self.db.commit()
        self.reload()

    def edit_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        p = self._items[row]
        r = self._prompt(p.name, p.notes)
        if not r:
            return
        p.name, p.notes = r
        self.db.commit()
        self.reload()

    def delete_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        self.db.delete(self._items[row])
        self.db.commit()
        self.reload()


class VehicleManager(_ListManager):
    columns = (("Fordon", "l"), ("Reg.nr", "l"), ("Märke/modell", "l"), ("Anställd", "l"))
    empty_key = "Inga fordon ännu."

    def reload(self):
        self._items = self.db.execute(select(Vehicle).order_by(Vehicle.label)).scalars().all()
        emps = {e.id: e.name for e in self.db.execute(select(Employee)).scalars()}
        self.table.clear_rows()
        for v in self._items:
            self.table.add_row([v.label, v.reg_no, f"{v.make} {v.model}".strip(),
                                emps.get(v.assigned_employee_id, "")])
        self.table.refresh_empty_state()

    def add_item(self):
        VehicleDialog(self.db, None, self.window()).exec_and_apply()
        self.reload()

    def edit_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        VehicleDialog(self.db, self._items[row], self.window()).exec_and_apply()
        self.reload()

    def delete_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        self.db.delete(self._items[row])
        self.db.commit()
        self.reload()


class CategoryManager(_ListManager):
    columns = (("Kategori", "l"), ("Momskod", "l"))
    empty_key = "Inga kategorier."

    def reload(self):
        self._items = self.db.execute(select(ExpenseCategory).order_by(ExpenseCategory.name)).scalars().all()
        self.table.clear_rows()
        for c in self._items:
            self.table.add_row([c.name, c.default_vat_code or ""])
        self.table.refresh_empty_state()

    def _prompt(self, name="", code=""):
        n, ok1 = QInputDialog.getText(self, tr("Kategori"), tr("Kategorinamn"), text=name)
        if not ok1 or not n.strip():
            return None
        c, ok2 = QInputDialog.getText(self, tr("Kategori"), tr("Standardmomskod (valfritt)"), text=code)
        if not ok2:
            return None
        return n.strip(), c.strip()

    def add_item(self):
        r = self._prompt()
        if not r:
            return
        if self.db.query(ExpenseCategory).filter_by(name=r[0]).first():
            QMessageBox.warning(self, tr("Fel"), tr("Namnet finns redan.")); return
        self.db.add(ExpenseCategory(name=r[0], default_vat_code=r[1]))
        self.db.commit()
        self.reload()

    def edit_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        c = self._items[row]
        r = self._prompt(c.name, c.default_vat_code or "")
        if not r:
            return
        c.name, c.default_vat_code = r
        self.db.commit()
        self.reload()

    def delete_item(self):
        row = self.table.selected_row()
        if not (0 <= row < len(self._items)):
            return
        self.db.delete(self._items[row])
        self.db.commit()
        self.reload()


class PayrollTab(Translatable):
    """Tax parameters & payroll defaults (all user-editable, labelled defaults)."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.params = _get_params(db)
        grid = QGridLayout(self)
        grid.setHorizontalSpacing(16)
        self._money: dict[str, QLineEdit] = {}
        self._spin: dict[str, QSpinBox] = {}

        self.note_lbl = QLabel("")
        self.note_lbl.setWordWrap(True)
        self.note_lbl.setStyleSheet("color:#666;")
        grid.addWidget(self.note_lbl, 0, 0, 1, 2)

        r = 1
        self.f_ag = self._money_field("Arbetsgivaravgift, standard %", "ag_rate_default")
        grid.addWidget(self.f_ag, r, 0)
        self.f_youth_rate = self._money_field("Ungdomsavgift % (nedsatt)", "youth_rate")
        grid.addWidget(self.f_youth_rate, r, 1); r += 1

        self.youth_enabled = QCheckBox()
        self.youth_enabled.setChecked(self.params.youth_enabled)
        self.f_youth_enabled = LabeledField("Tillämpa nedsatt ungdomsavgift automatiskt", self.youth_enabled)
        grid.addWidget(self.f_youth_enabled, r, 0)
        self.f_ceiling = self._money_field("Ungdomsavgift tak kr/mån", "youth_ceiling")
        grid.addWidget(self.f_ceiling, r, 1); r += 1

        self.birth_from = QSpinBox(); self.birth_from.setRange(1900, 2200)
        self.birth_from.setValue(self.params.youth_birth_from)
        self.birth_to = QSpinBox(); self.birth_to.setRange(1900, 2200)
        self.birth_to.setValue(self.params.youth_birth_to)
        grid.addWidget(LabeledField("Födelseår från", self.birth_from), r, 0)
        grid.addWidget(LabeledField("Födelseår till", self.birth_to), r, 1); r += 1

        self.valid_from = QDateEdit(); self.valid_from.setCalendarPopup(True); self.valid_from.setDisplayFormat("yyyy-MM-dd")
        self.valid_from.setDate(QDate(self.params.youth_valid_from.year, self.params.youth_valid_from.month, self.params.youth_valid_from.day))
        self.valid_to = QDateEdit(); self.valid_to.setCalendarPopup(True); self.valid_to.setDisplayFormat("yyyy-MM-dd")
        self.valid_to.setDate(QDate(self.params.youth_valid_to.year, self.params.youth_valid_to.month, self.params.youth_valid_to.day))
        grid.addWidget(LabeledField("Gäller utbetalningar från", self.valid_from), r, 0)
        grid.addWidget(LabeledField("Gäller utbetalningar till", self.valid_to), r, 1); r += 1

        self.f_municipal = self._money_field("Kommunalskatt % (användarens egen uppgift)", "municipal_tax_pct")
        grid.addWidget(self.f_municipal, r, 0)
        self.f_church = self._money_field("Kyrkoavgift %", "church_pct")
        grid.addWidget(self.f_church, r, 1); r += 1

        self.f_burial = self._money_field("Begravningsavgift %", "burial_pct")
        grid.addWidget(self.f_burial, r, 0)
        self.f_deduction = self._money_field("Avdrag/grundavdrag kr (valfritt)", "extra_deduction")
        grid.addWidget(self.f_deduction, r, 1); r += 1

        self.f_mileage = self._money_field("Milersättning kr/mil (ingen standard — ange egen)", "mileage_rate")
        grid.addWidget(self.f_mileage, r, 0)
        self.f_vat_day = QSpinBox(); self.f_vat_day.setRange(1, 31)
        self.f_vat_day.setValue(self.params.vat_deadline_day)
        self.f_vat_offset = QSpinBox(); self.f_vat_offset.setRange(0, 12)
        self.f_vat_offset.setValue(self.params.vat_deadline_month_offset)
        grid.addWidget(LabeledField("Momsdeadline: dag i månaden", self.f_vat_day), r, 1); r += 1
        grid.addWidget(LabeledField("Momsdeadline: månader efter periodens slut", self.f_vat_offset), r, 0)

        self.f_source = LabeledField("Källhänvisning (visas i UI)", QLineEdit(self.params.source_note))
        grid.addWidget(self.f_source, r, 0, 1, 2)
        self.retranslate()

    def _money_field(self, label_key: str, attr: str) -> LabeledField:
        edit = QLineEdit()
        val = getattr(self.params, attr)
        edit.setText("" if val is None else f"{val}")
        self._money[attr] = edit
        return LabeledField(label_key, edit)

    def retranslate(self):
        self.note_lbl.setText(tr("payroll.tab.note"))

    def apply(self):
        p = self.params
        for attr, edit in self._money.items():
            txt = edit.text().strip()
            if txt == "":
                setattr(p, attr, None if attr == "mileage_rate" else Decimal("0.00"))
                continue
            val = parse_money(txt)
            if val is None:
                raise InvalidOperation(attr)
            setattr(p, attr, q2(val))
        p.youth_enabled = self.youth_enabled.isChecked()
        p.youth_birth_from = self.birth_from.value()
        p.youth_birth_to = self.birth_to.value()
        p.youth_valid_from = self.valid_from.date().toPython()
        p.youth_valid_to = self.valid_to.date().toPython()
        p.vat_deadline_day = self.f_vat_day.value()
        p.vat_deadline_month_offset = self.f_vat_offset.value()
        p.source_note = self.f_source.widget.text().strip()
        self.db.commit()


class VehicleDialog:
    """Tiny imperative dialog for vehicle add/edit."""

    def __init__(self, db, vehicle: Vehicle | None, parent=None):
        self.db = db
        self.vehicle = vehicle
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        from PySide6.QtWidgets import QDialog as _QD  # noqa: F401
        self.dlg = QDialog(parent)
        self.dlg.setWindowTitle(tr("Fordon"))
        form = QFormLayout(self.dlg)
        self.label = QLineEdit(vehicle.label if vehicle else "")
        self.reg = QLineEdit(vehicle.reg_no if vehicle else "")
        self.make = QLineEdit(vehicle.make if vehicle else "")
        self.model = QLineEdit(vehicle.model if vehicle else "")
        self.year = QSpinBox(); self.year.setRange(0, 2200); self.year.setSpecialValueText("—")
        self.year.setValue(vehicle.year_model or 0 if vehicle else 0)
        self.emp = QComboBox()
        self.emp.addItem(tr("— Ingen —"), 0)
        for e in db.execute(select(Employee).order_by(Employee.name)).scalars():
            self.emp.addItem(e.name, e.id)
        if vehicle and vehicle.assigned_employee_id:
            i = self.emp.findData(vehicle.assigned_employee_id)
            if i >= 0:
                self.emp.setCurrentIndex(i)
        form.addRow(tr("Beteckning"), self.label)
        form.addRow(tr("Reg.nr"), self.reg)
        form.addRow(tr("Märke"), self.make)
        form.addRow(tr("Modell"), self.model)
        form.addRow(tr("Årsmodell"), self.year)
        form.addRow(tr("Anställd"), self.emp)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Save).setText(tr("Spara"))
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))
        box.accepted.connect(self.dlg.accept)
        box.rejected.connect(self.dlg.reject)
        form.addRow(box)

    def exec_and_apply(self) -> bool:
        if not self.dlg.exec():
            return False
        v = self.vehicle or Vehicle()
        v.label = self.label.text().strip() or self.reg.text().strip() or "?"
        v.reg_no = self.reg.text().strip()
        v.make = self.make.text().strip()
        v.model = self.model.text().strip()
        y = self.year.value()
        v.year_model = y if y else None
        v.assigned_employee_id = self.emp.currentData() or None
        if self.vehicle is None:
            self.db.add(v)
        self.db.commit()
        return True


def build_lists_tab(db, parent=None) -> tuple[QWidget, list]:
    """Returns (widget, retranslatables) for the settings 'lists & defaults' tab."""
    host = QWidget(parent)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    inner = QTabWidget()
    lay.addWidget(inner)
    platforms = PlatformManager(db)
    vehicles = VehicleManager(db)
    categories = CategoryManager(db)
    payroll = PayrollTab(db)
    inner.addTab(platforms, "")
    inner.addTab(vehicles, "")
    inner.addTab(categories, "")
    inner.addTab(payroll, "")
    tabs_keys = ("Plattformar", "Fordon", "Utgiftskategorier", "Lön & skatteparametrar")

    def retranslate():
        for i, key in enumerate(tabs_keys):
            inner.setTabText(i, tr(key))
    retranslate()
    i18n.subscribe(retranslate)
    return host, [payroll]
