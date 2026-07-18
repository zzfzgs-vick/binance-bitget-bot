"""Reusable empty/read-only table model for UI wiring."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class ReadOnlyTableModel(QAbstractTableModel):
    """Minimal read-only model; real DTO mapping will be added later."""

    def __init__(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[Any]] | None = None,
    ) -> None:
        super().__init__()
        self._headers = tuple(headers)
        self._rows = [tuple(row) for row in (rows or ())]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        return self._rows[index.row()][index.column()]

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        return section + 1
