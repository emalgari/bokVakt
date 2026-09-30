"""Background workers (PDF, backup, restore, import, exports).

All slow work runs off the UI thread; widgets stay responsive and show
button loading states while a worker runs.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal


class Worker(QObject):
    """Runs `fn(*args)` on a QThread; emits result/error."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable, *args, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.args = args
        self._thread: QThread | None = None

    def start(self) -> None:
        self._thread = QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        self.finished.connect(self._thread.quit)
        self.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _run(self) -> None:
        try:
            result = self.fn(*self.args)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 — surfaced to the user as a toast
            from ..core.errors import DomainError
            if isinstance(exc, DomainError):
                self.failed.emit(exc.key)
            else:
                self.failed.emit(str(exc) or exc.__class__.__name__)
