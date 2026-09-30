"""Main window: menu bar, header (top bar), page stack, status bar."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QMenu,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import config as core_config
from ..core.db import get_session_factory
from ..core.invoices import get_profile
from ..i18n import i18n, tr
from . import theme
from .context import AppContext
from .dialogs.about_dialog import AboutDialog
from .dialogs.settings_dialog import SettingsDialog
from .header import HeaderBar
from .lock import LockScreen
from .pages.customers import CustomersPage
from .pages.dashboard import DashboardPage
from .pages.data_audit import DataPage
from .pages.employees import EmployeesPage
from .pages.expenses import ExpensesPage
from .pages.income import IncomePage
from .pages.invoices import InvoicesPage
from .pages.owner import OwnerPage
from .pages.quarterly_vat import QuarterlyVatPage
from .pages.reports import ReportsPage
from .pages.tax_documents import TaxDocumentsPage
from .pages.vat import VatPage


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Firmabok")
        self.setMinimumSize(800, 600)
        self.ctx = AppContext(self)

        self._build_menus()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # index 0: lock screen; index 1: app content
        self.lock = LockScreen()
        self.lock.unlocked.connect(self.show_content)
        self.stack.addWidget(self.lock)

        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, 0, 0)
        clay.setSpacing(0)
        self.header = HeaderBar()
        self.header.nav_selected.connect(self.go_page)
        self.header.logout_clicked.connect(self.show_lock)
        self.header.settings_clicked.connect(self.open_settings)
        clay.addWidget(self.header)

        self.pages = QStackedWidget()
        wrap = QWidget()
        wlay = QVBoxLayout(wrap)
        wlay.setContentsMargins(24, 16, 24, 16)
        wlay.addWidget(self.pages)
        clay.addWidget(wrap, 1)
        self.stack.addWidget(content)

        self._pages: dict[str, QWidget] = {}
        self._page_scrolls: dict[str, QWidget] = {}
        self._page_classes = {
            "dashboard": DashboardPage, "income": IncomePage, "expenses": ExpensesPage,
            "vat": VatPage, "quarterly": QuarterlyVatPage,
            "invoices": InvoicesPage, "customers": CustomersPage,
            "owner": OwnerPage, "reports": ReportsPage, "data": DataPage,
            "taxdocs": TaxDocumentsPage, "employees": EmployeesPage,
        }

        self.setCentralWidget(central)
        self.statusBar().showMessage("")
        i18n.subscribe(self.retranslate)
        self.retranslate()
        self.refresh_brand()

    # ------------------------------------------------------------------ menu
    def _build_menus(self) -> None:
        mb = self.menuBar()
        self.menu_file = QMenu()
        self.menu_view = QMenu()
        self.menu_help = QMenu()
        mb.addMenu(self.menu_file)
        mb.addMenu(self.menu_view)
        mb.addMenu(self.menu_help)

        self.act_settings = QAction(theme.icon("settings"), "", self)
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_settings.triggered.connect(self.open_settings)
        self.act_backup = QAction(theme.icon("hard-drive"), "", self)
        self.act_backup.setShortcut(QKeySequence("Ctrl+B"))
        self.act_backup.triggered.connect(self._backup_now)
        self.act_quit = QAction("", self)
        self.act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.act_quit.triggered.connect(self.close)
        self.menu_file.addAction(self.act_settings)
        self.menu_file.addAction(self.act_backup)
        self.menu_file.addSeparator()
        self.menu_file.addAction(self.act_quit)

        self.menu_lang = QMenu()
        self.lang_group = QActionGroup(self)
        self.act_sv = QAction("Svenska", self, checkable=True)
        self.act_en = QAction("English", self, checkable=True)
        self.act_sv.triggered.connect(lambda: i18n.set_language("sv"))
        self.act_en.triggered.connect(lambda: i18n.set_language("en"))
        for a in (self.act_sv, self.act_en):
            self.lang_group.addAction(a)
            self.menu_lang.addAction(a)
        self.menu_view.addMenu(self.menu_lang)

        self.act_about = QAction(theme.icon("info"), "", self)
        self.act_about.setShortcut(QKeySequence("F1"))
        self.act_about.triggered.connect(self.open_about)
        self.menu_help.addAction(self.act_about)

    # --------------------------------------------------------------- labels
    def retranslate(self) -> None:
        self.menu_file.setTitle(tr("Arkiv"))
        self.menu_view.setTitle(tr("Visa"))
        self.menu_help.setTitle(tr("Hjälp"))
        self.menu_lang.setTitle(tr("Språk"))
        self.act_settings.setText(tr("Inställningar…"))
        self.act_backup.setText(tr("Skapa backup nu"))
        self.act_quit.setText(tr("Avsluta"))
        self.act_about.setText(tr("Om Firmabok"))
        self.act_sv.setChecked(i18n.language == "sv")
        self.act_en.setChecked(i18n.language == "en")
        self.setWindowTitle("Firmabok" + (f" — {self._company_name()}" if self._company_name() else ""))

    def _company_name(self) -> str:
        db = get_session_factory()()
        try:
            return get_profile(db).company_name or ""
        finally:
            db.close()

    def refresh_brand(self) -> None:
        db = get_session_factory()()
        try:
            p = get_profile(db)
            self.header.load_brand(p.company_name, p.logo_path)
        finally:
            db.close()

    # ---------------------------------------------------------------- pages
    def _ensure_page(self, page_id: str) -> QWidget:
        if page_id not in self._pages:
            from PySide6.QtWidgets import QScrollArea
            cls = self._page_classes[page_id]
            page = cls(self.ctx)
            scroll = QScrollArea()
            scroll.setWidget(page)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._pages[page_id] = page
            self._page_scrolls[page_id] = scroll
            self.pages.addWidget(scroll)
        return self._pages[page_id]

    def go_page(self, page_id: str) -> None:
        page = self._ensure_page(page_id)
        self.pages.setCurrentWidget(self._page_scrolls[page_id])
        core_config.settings().set("last_page", page_id)
        if hasattr(page, "reload"):
            page.reload()
        self.header.set_current_page(page_id)
        self.statusBar().showMessage(tr(page_id.capitalize()) if False else "", 2000)

    def show_lock(self) -> None:
        self.lock.retranslate()
        self.stack.setCurrentIndex(0)
        self.statusBar().showMessage("")

    def show_content(self) -> None:
        self.stack.setCurrentIndex(1)
        self.refresh_brand()
        last = core_config.settings().get("last_page", "dashboard")
        self.go_page(last if last in self._page_classes else "dashboard")

    # ------------------------------------------------------------- actions
    def open_settings(self) -> None:
        db = get_session_factory()()
        try:
            dlg = SettingsDialog(db, self)
            if dlg.exec():
                self.refresh_brand()
                for p in self._pages.values():
                    if hasattr(p, "reload"):
                        p.reload()
                self.ctx.toast(tr("Inställningarna sparades."), "success")
        finally:
            db.close()

    def open_about(self) -> None:
        AboutDialog(self).exec()

    def _backup_now(self) -> None:
        from ..core import backup as backupmod
        from .pages.data_audit import DataPage  # noqa: F401 (toast via ctx)
        from .workers import Worker

        def _job():
            return str(backupmod.create_backup())

        w = Worker(_job)
        w.finished.connect(lambda p: self.ctx.toast(tr("Backup skapad") + f": {p}", "success"))
        w.failed.connect(lambda e: self.ctx.toast(f"{tr('Backup misslyckades')}: {e}", "error"))
        w.start()
        self._backup_worker = w

    def closeEvent(self, event):  # noqa: N802
        st = core_config.settings()
        st.set("window_geometry", bytes(self.saveGeometry().toHex()).decode())
        st.save()
        super().closeEvent(event)

    def restore_geometry(self) -> None:
        geo = core_config.settings().get("window_geometry", "")
        if geo:
            from PySide6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromHex(geo.encode()))
        else:
            self.resize(1280, 800)
