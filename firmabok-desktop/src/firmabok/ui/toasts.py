"""Toast/snackbar notifications anchored to the main window."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class ToastManager:
    """Stack of transient toasts at the bottom-right of `host`."""

    def __init__(self, host: QWidget):
        self.host = host
        self._toasts: list[QFrame] = []

    def show(self, text: str, kind: str = "info", ms: int = 4200) -> None:
        t = QFrame(self.host)
        t.setObjectName("toast")
        t.setProperty("kind", kind)
        lay = QHBoxLayout(t)
        lay.setContentsMargins(16, 10, 16, 10)
        label = QLabel(text)
        label.setWordWrap(False)
        lay.addWidget(label)
        t.adjustSize()
        self._toasts.append(t)
        self._reposition()
        t.show()
        t.raise_()
        QTimer.singleShot(ms, lambda: self._close(t))

    def _close(self, t: QFrame) -> None:
        if t in self._toasts:
            self._toasts.remove(t)
        t.deleteLater()
        self._reposition()

    def _reposition(self) -> None:
        host_rect = self.host.rect()
        y = host_rect.bottom() - 16
        for t in reversed(self._toasts):
            t.adjustSize()
            x = host_rect.right() - t.width() - 24
            t.move(QPoint(max(8, x), y - t.height()))
            y -= t.height() + 8

    def clear(self) -> None:
        for t in list(self._toasts):
            self._close(t)
