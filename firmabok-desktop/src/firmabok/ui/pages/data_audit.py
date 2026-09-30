"""Data page: backups, restore, exports, audit log."""
from __future__ import annotations

import json
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)
from sqlalchemy import select

from ...core import backup as backupmod
from ...core import config as core_config
from ...core import reports
from ...core.invoices import get_profile
from ...core.models import AuditLog
from ...core.swedish import fiscal_year_bounds, fiscal_year_of
from ...i18n import i18n, tr
from .. import theme
from ..translatable import Translatable
from ..widgets.cards import Card, PageHeader
from ..widgets.tables import DataTable
from ..workers import Worker

AUDIT_COLUMNS = [("Tid (UTC)", "l"), ("Åtgärd", "l"), ("Entitet", "l"),
                 ("Sammanfattning", "l"), ("Användare", "l")]


class DataPage(Translatable):
    page_id = "data"

    def __init__(self, ctx, parent=None):
        self.ctx = ctx
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.header = PageHeader("Data, backup & granskning")
        lay.addWidget(self.header)

        top = QHBoxLayout()
        self.btn_backup = QPushButton(tr("Skapa backup nu"))
        self.btn_backup.setIcon(theme.icon("hard-drive"))
        self.btn_backup.clicked.connect(self._backup)
        self.btn_export = QPushButton(tr("Exportera allt (JSON)"))
        self.btn_export.setProperty("kind", "secondary")
        self.btn_export.setIcon(theme.icon("download"))
        self.btn_export.clicked.connect(self._export_json)
        self.btn_journal = QPushButton(tr("Bokföringsorder (CSV)"))
        self.btn_journal.setProperty("kind", "secondary")
        self.btn_journal.setIcon(theme.icon("download"))
        self.btn_journal.clicked.connect(self._export_journal)
        for b in (self.btn_backup, self.btn_export, self.btn_journal):
            top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)

        grid = QGridLayout()
        self.paths_card = Card("Säkerhet & integritet")
        self.paths_lbl = QLabel("")
        self.paths_lbl.setWordWrap(True)
        self.paths_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.paths_card.body.addWidget(self.paths_lbl)

        self.restore_card = Card("Backup & återställning")
        self.restore_table = DataTable([("Backup", "l"), ("Skapad", "l"), ("Storlek", "r")],
                                       empty_key="Inga backuper ännu.")
        self.restore_table.table.setMaximumHeight(160)
        self.restore_card.body.addWidget(self.restore_table)
        row = QHBoxLayout()
        self.btn_restore = QPushButton(tr("Återställ vald backup"))
        self.btn_restore.setProperty("kind", "danger")
        self.btn_restore.clicked.connect(self._restore)
        row.addWidget(self.btn_restore)
        row.addStretch(1)
        self.restore_card.body.addLayout(row)

        grid.addWidget(self.paths_card, 0, 0)
        grid.addWidget(self.restore_card, 0, 1)
        lay.addLayout(grid)

        audit_card = Card("Granskningslogg")
        self.audit_table = DataTable(AUDIT_COLUMNS, empty_key="Loggen är tom.")
        audit_card.body.addWidget(self.audit_table)
        lay.addWidget(audit_card, 1)
        self.retranslate()

    def retranslate(self) -> None:
        self.header.retranslate()
        self.btn_backup.setText(tr("Skapa backup nu"))
        self.btn_export.setText(tr("Exportera allt (JSON)"))
        self.btn_journal.setText(tr("Bokföringsorder (CSV)"))
        self.btn_restore.setText(tr("Återställ vald backup"))
        self.reload()

    def reload(self) -> None:
        self.paths_lbl.setText(
            f"{tr('Databas')}: {core_config.DB_PATH}\n"
            f"{tr('Uppladdade filer')}: {core_config.UPLOAD_DIR}\n"
            f"{tr('Backuper')}: {core_config.BACKUP_DIR}\n"
            f"{tr('Loggar')}: {core_config.LOG_DIR}\n\n"
            + tr("All data lagras lokalt. Ingen molntjänst, inga externa API:er, ingen telemetri."))
        try:
            backups = backupmod.list_backups()
        except Exception:  # noqa: BLE001
            backups = []
        self.restore_table.clear_rows()
        for b in backups:
            self.restore_table.add_row([b["name"], b["created_at"],
                                        f"{b['total_bytes'] / 1e6:.1f} MB"])
        self.restore_table.refresh_empty_state()
        self.restore_table.resize_columns()

        db = self.ctx.session()
        try:
            entries = db.execute(select(AuditLog).order_by(AuditLog.ts.desc(), AuditLog.id.desc())
                                 .limit(300)).scalars().all()
            self.audit_table.clear_rows()
            for e in entries:
                self.audit_table.add_row([
                    e.ts.strftime("%Y-%m-%d %H:%M:%S"), e.action,
                    f"{e.entity_type}{f' #{e.entity_id}' if e.entity_id else ''}",
                    e.summary, e.username])
            self.audit_table.refresh_empty_state()
            self.audit_table.resize_columns()
        finally:
            db.close()

    # -------------------------------------------------------------- actions
    def _backup(self) -> None:
        self.btn_backup.setEnabled(False)

        def _job():
            return str(backupmod.create_backup())

        w = Worker(_job)
        w.finished.connect(lambda p: (self.btn_backup.setEnabled(True),
                                      self.ctx.toast(tr("Backup skapad") + f": {p}", "success"),
                                      self.reload()))
        w.failed.connect(lambda e: (self.btn_backup.setEnabled(True),
                                    self.ctx.toast(f"{tr('Backup misslyckades')}: {e}", "error")))
        w.start()
        self._worker = w

    def _restore(self) -> None:
        row = self.restore_table.selected_row()
        backups = backupmod.list_backups()
        if not (0 <= row < len(backups)):
            self.ctx.toast(tr("Markera en rad först."), "warning"); return
        name = backups[row]["name"]
        ok, word, _ = self._ask_word(tr("Skriv exakt 'ÅTERSTÄLL' för att bekräfta."), "ÅTERSTÄLL")
        if not ok:
            return
        self.ctx.toast(tr("Återställning startad — starta om appen när den är klar."), "info")

        def _job():
            safety = backupmod.restore_backup(name)
            return str(safety)

        w = Worker(_job)
        w.finished.connect(lambda p: self.ctx.toast(
            tr("Återställning klar. Starta om appen nu.") + f" ({tr('Säkerhetskopia')}: {p})",
            "success"))
        w.failed.connect(lambda e: self.ctx.toast(f"{tr('Återställning misslyckades')}: {e}", "error"))
        w.start()
        self._worker = w

    def _ask_word(self, prompt: str, word: str) -> tuple[bool, str, object]:
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout
        dlg = QDialog(self.window())
        dlg.setWindowTitle(tr("Bekräfta åtgärd"))
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(prompt))
        edit = QLineEdit()
        lay.addWidget(edit)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Ja, fortsätt"))
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Avbryt"))
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        ok = dlg.exec() == QDialog.DialogCode.Accepted and edit.text().strip().upper() == word
        return ok, edit.text(), dlg

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self.window(), tr("Exportera allt (JSON)"),
            f"firmabok-export-{date.today():%Y%m%d}.json", "JSON (*.json)")
        if not path:
            return
        db = self.ctx.session()
        try:
            from ...core.models import (
                CompanyProfile,
                Customer,
                Expense,
                IncomeEntry,
                Invoice,
                OwnerTransaction,
                VatReport,
            )

            def rows(model):
                return [{c.name: str(getattr(o, c.name)) if getattr(o, c.name) is not None else None
                         for c in o.__table__.columns}
                        for o in db.execute(select(model)).scalars().all()]

            data = {
                "exported_at": datetime.now().isoformat(timespec="seconds"),
                "app": "Firmabok Desktop",
                "company_profile": rows(CompanyProfile),
                "customers": rows(Customer),
                "income_entries": rows(IncomeEntry),
                "expenses": rows(Expense),
                "invoices": rows(Invoice),
                "owner_transactions": rows(OwnerTransaction),
                "vat_reports": rows(VatReport),
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            self.ctx.toast(tr("JSON sparad") + f": {path}", "success")
        finally:
            db.close()

    def _export_journal(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self.window(), tr("Exportera CSV"),
                                              "bokforingsorder.csv", "CSV (*.csv)")
        if not path:
            return
        db = self.ctx.session()
        try:
            profile = get_profile(db)
            fy = fiscal_year_of(date.today(), profile.fiscal_year_start_month)
            start, end = fiscal_year_bounds(fy, profile.fiscal_year_start_month)
            content = reports.export_journal_csv(db, start, end, lang=i18n.language)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(content)
            self.ctx.toast(tr("CSV sparad") + f": {path}", "success")
        finally:
            db.close()
