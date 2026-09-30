"""Tax-document dialogs (feature D): upload + key-figure editing."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

from ...core import config as core_config
from ...core import taxdocs
from ...core.models import TaxDocument
from ...i18n import tr
from .. import theme
from ..widgets.forms import LabeledField, MoneyEdit, date_edit, date_of
from .forms import BaseDialog

TYPE_KEYS = {
    "slutlig_skatt": "Slutlig skatt (beslut)",
    "preliminar": "Preliminärskatt / F-skatt",
    "momsdeklaration": "Momsdeklaration",
    "ovrigt": "Övrig korrespondens",
}


class TaxDocUploadDialog(BaseDialog):
    def __init__(self, db, parent=None):
        super().__init__("Ladda upp dokument", parent)
        self.db = db
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)

        self.type_cb = QComboBox()
        for value, key in TYPE_KEYS.items():
            self.type_cb.addItem(tr(key), value)
        self.f_type = LabeledField("Dokumenttyp", self.type_cb, required=True)
        self.title = QLineEdit()
        self.f_title = LabeledField("Titel", self.title)
        self.f_issued = LabeledField("Utgivningsdatum", date_edit(None))
        self.period = QLineEdit()
        self.f_period = LabeledField("Period", self.period)
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(56)
        self.f_notes = LabeledField("Anteckningar", self.notes)

        self.file_btn = QPushButton(tr("Välj fil…"))
        self.file_btn.setProperty("kind", "secondary")
        self.file_btn.setIcon(theme.icon("paperclip"))
        self.file_btn.clicked.connect(self._pick)
        self.file_lbl = QLabel("")
        self.file_lbl.setObjectName("muted")
        row = QWidget()
        rr = QHBoxLayout(row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.addWidget(self.file_btn)
        rr.addWidget(self.file_lbl, 1)
        self.f_file = LabeledField("Fil", row, required=True)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")

        for w, r, c in ((self.f_type, 0, 0), (self.f_title, 0, 1), (self.f_issued, 1, 0),
                        (self.f_period, 1, 1), (self.f_file, 2, 0), (self.f_notes, 2, 1)):
            grid.addWidget(w, r, c)
        grid.addWidget(self.hint, 3, 0, 1, 2)
        self._root.addLayout(grid)
        self._add_buttons()
        self._path = ""
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "type_cb"):   # called from BaseDialog.__init__ pre-build
            return
        for i, key in enumerate(TYPE_KEYS.values()):
            self.type_cb.setItemText(i, tr(key))
        self.file_btn.setText(tr("Välj fil…"))
        self.hint.setText(tr("taxdocs.upload_hint"))

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, tr("Välj fil…"), str(core_config.UPLOAD_DIR),
            "PDF (*.pdf);;Bilder (*.png *.jpg *.jpeg);;Alla filer (*)")
        if path:
            self._path = path
            from pathlib import Path
            self.file_lbl.setText(Path(path).name)

    def on_accept(self) -> None:
        if not self._path:
            self.f_file.set_error("Välj en fil först.")
            return
        doc = taxdocs.save_document(
            self.db, self._path, self.type_cb.currentData(),
            title=self.title.text().strip(),
            issued=date_of(self.f_issued.widget),
            period_text=self.period.text().strip(),
            notes=self.notes.toPlainText().strip())
        self.result_doc = doc
        self.accept()


class TaxDocDetailDialog(BaseDialog):
    """View metadata + user-entered key figures (always manually correctable)."""

    def __init__(self, db, doc: TaxDocument, parent=None):
        super().__init__("Nyckeltal (manuell inmatning/korrigering)", parent)
        self.db = db
        self.doc = doc
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        ex = taxdocs.get_extracted(doc)

        self.meta = QLabel("")
        self.meta.setWordWrap(True)
        self.meta.setObjectName("muted")
        grid.addWidget(self.meta, 0, 0, 1, 2)

        self.f_final = self._money("Slutlig skatt (kr)", ex.get("final_tax"))
        self.f_prepaid = self._money("Redan betald preliminärskatt (kr)", ex.get("preliminary_paid"))
        self.f_vat = self._money("Att betala/få tillbaka", ex.get("vat_net"))
        self.f_free = LabeledField("Anteckningar", QLineEdit(ex.get("free_text", "")))

        grid.addWidget(self.f_final, 1, 0)
        grid.addWidget(self.f_prepaid, 1, 1)
        grid.addWidget(self.f_vat, 2, 0)
        grid.addWidget(self.f_free, 2, 1)
        self.disclaimer = QLabel("")
        self.disclaimer.setWordWrap(True)
        self.disclaimer.setObjectName("muted")
        grid.addWidget(self.disclaimer, 3, 0, 1, 2)
        self._root.addLayout(grid)
        self._add_buttons()
        self.retranslate()

    def _money(self, label_key: str, value) -> LabeledField:
        edit = MoneyEdit()
        if value:
            edit.setText(str(value))
        return LabeledField(label_key, edit)

    def retranslate(self) -> None:
        super().retranslate()
        if not hasattr(self, "meta"):      # called from BaseDialog.__init__ pre-build
            return
        d = self.doc
        self.meta.setText(f"{tr(TYPE_KEYS[d.doc_type])} · {d.title} · "
                          f"{d.original_name} ({d.size_bytes} bytes)")
        self.disclaimer.setText(tr("taxdocs.disclaimer"))

    def on_accept(self) -> None:
        taxdocs.set_extracted(self.db, self.doc, {
            "final_tax": self.f_final.widget.text().strip(),
            "preliminary_paid": self.f_prepaid.widget.text().strip(),
            "vat_net": self.f_vat.widget.text().strip(),
            "free_text": self.f_free.widget.text().strip(),
        })
        self.db.commit()
        self.accept()
