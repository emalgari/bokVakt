"""Translatable mixin + language-change plumbing."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ..i18n import i18n


class Translatable(QWidget):
    """Base for widgets that must retranslate live on language switch.

    Subclasses implement ``retranslate()``; the base registers/unregisters
    with the i18n bus and calls retranslate() once on init.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registered = True
        i18n.subscribe(self._on_lang)

    def _on_lang(self) -> None:
        if self._registered:
            self.retranslate()

    def retranslate(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def hideEvent(self, event):
        super().hideEvent(event)

    def unregister_i18n(self) -> None:
        self._registered = False
        i18n.unsubscribe(self._on_lang)
