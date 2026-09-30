"""Data table base: sortable, zebra-optional, right-aligned numerics,
sticky-style header, empty-state overlay."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStackedLayout, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ...i18n import i18n, tr
from .cards import EmptyState


class DataTable(QWidget):
    """QTableWidget wrapper.

    * ``columns``: list of (key, align) where key is the Swedish source string
      used as translation key; align in {'l','r','c'}.
    * Sorting enabled; numeric columns right-aligned with tabular figures.
    * Empty state overlay swaps in automatically.
    """

    def __init__(self, columns: list[tuple[str, str]], parent=None,
                 empty_key: str = "", empty_cta: str = "", on_empty_cta=None,
                 sortable: bool = True):
        super().__init__(parent)
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # never force the parent page wider than the window: the table
        # scrolls horizontally inside itself instead
        self.setMinimumSize(240, 120)
        self._columns = columns
        self.table = QTableWidget(0, len(columns))
        self.table.setSortingEnabled(sortable)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.setMinimumSize(240, 120)
        self.table.horizontalHeader().setMinimumSectionSize(56)
        self._empty = EmptyState(empty_key, empty_cta, on_empty_cta) if empty_key else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        if self._empty:
            self.stack = QStackedLayout(lay)
            self.stack.setContentsMargins(0, 0, 0, 0)
            self.stack.addWidget(self.table)
            self.stack.addWidget(self._empty)
        self.retranslate()
        i18n.subscribe(self.retranslate)

    def retranslate(self) -> None:
        headers = [tr(key) for key, _align in self._columns]
        self.table.setHorizontalHeaderLabels(headers)
        for i, (_key, align) in enumerate(self._columns):
            item = self.table.horizontalHeaderItem(i)
            if item:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    if align == "r" else
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    # ------------------------------------------------------------------ rows
    def clear_rows(self) -> None:
        sortable = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(sortable)

    def add_row(self, values: list, aligns: str | None = None) -> int:
        """values: str/QTableWidgetItem per column. Returns row index."""
        sortable = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, val in enumerate(values):
            align = (aligns[col] if aligns else self._columns[col][1])
            if isinstance(val, QTableWidgetItem):
                item = val
            else:
                item = QTableWidgetItem(str(val))
            if align == "r":
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            elif align == "c":
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)
        self.table.setSortingEnabled(sortable)
        return row

    def add_total_row(self, values: list) -> None:
        row = self.add_row(values)
        for col in range(self.table.columnCount()):
            item = self.table.item(row, col)
            if item:
                from PySide6.QtGui import QFont
                f = QFont()
                f.setBold(True)
                item.setFont(f)

    def refresh_empty_state(self) -> None:
        if self._empty is not None:
            self.stack.setCurrentIndex(1 if self.table.rowCount() == 0 else 0)

    def selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def resize_columns(self) -> None:
        self.table.resizeColumnsToContents()
        for i in range(self.table.columnCount()):
            w = self.table.columnWidth(i)
            self.table.setColumnWidth(i, min(max(w, 60), 420))
