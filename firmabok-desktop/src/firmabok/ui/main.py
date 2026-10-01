"""Firmabok Desktop entry point.

    firmabok-desktop            (console script)
    python -m firmabok.ui.main

Bootstrap order: XDG dirs → logging → settings → migrations/seeds → language
→ single-instance lock → wizard (first run) → lock screen / main window.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import __version__
from ..core import config as core_config
from ..core.db import get_session_factory
from ..core.migrate import run_migrations, seed_reference_data
from ..i18n import i18n, init_language, tr
from . import theme


def _setup_logging() -> None:
    core_config.ensure_dirs()
    log_file = core_config.LOG_DIR / "firmabok.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)],
    )


def main() -> int:
    _setup_logging()
    log = logging.getLogger("firmabok")

    app = QApplication(sys.argv)
    app.setApplicationName("Firmabok")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Firmabok")
    app.setDesktopFileName("firmabok.desktop")
    theme.apply(app)

    # single instance
    lock = QLockFile(str(core_config.LOCK_PATH))
    lock.setStaleLockTime(30_000)
    if not lock.tryLock(100):
        QMessageBox.warning(None, "Firmabok",
                            tr("Programmet körs redan i ett annat fönster."))
        return 1

    # database
    core_config.ensure_dirs()
    run_migrations()
    db = get_session_factory()()
    try:
        seed_reference_data(db)
    finally:
        db.close()

    st = core_config.settings()
    init_language(st.get("language", "sv"))

    # --- account gate (Phase 2, additive) ---------------------------------
    # New user_accounts system in front of the app: Login when accounts
    # exist, Welcome (create account / import .bokvakt) on a true first run.
    # Legacy flow below is untouched: no accounts + wizard completed → the
    # gate never runs and behavior is exactly as before.
    from .auth.gate import AuthGate, accounts_exist
    gate_account = None
    if accounts_exist() or not st.get("wizard_completed", False):
        gate = AuthGate()
        if gate.exec() != AuthGate.DialogCode.Accepted:
            gate.deleteLater()
            return 0  # user cancelled/closed the gate — nothing to show yet
        gate_account = gate.account
        gate.detach()
        gate.deleteLater()
        # an archive import inside the gate replaces settings.json
        st = core_config.settings()

    from .app import MainWindow
    win = MainWindow()
    win.restore_geometry()

    if not st.get("wizard_completed", False):
        from .wizard.first_run import FirstRunWizard
        wizard = FirstRunWizard(win)
        result = wizard.exec()
        if result != FirstRunWizard.DialogCode.Accepted:
            return 0  # user cancelled the wizard — nothing to show yet
        st.save()
        win.refresh_brand()
        win.show_content()
    else:
        win.show()
        if gate_account is not None:
            # authenticated through the new account system — skip legacy lock
            win.show_content()
        elif st.get("auth.enabled", False):
            win.show_lock()
        else:
            win.show_content()

    log.info("Firmabok %s started (lang=%s)", __version__, i18n.language)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
