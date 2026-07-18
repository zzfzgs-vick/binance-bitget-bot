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
        self._rows = self._validated_rows(rows or ())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        if not (0 <= index.row() < len(self._rows)):
            return None
        if not (0 <= index.column() < len(self._headers)):
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
        if orientation == Qt.Orientation.Vertical and 0 <= section < len(self._rows):
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def replace_rows(self, rows: Sequence[Sequence[Any]]) -> None:
        """Replace all rows after validating their column counts."""
        validated_rows = self._validated_rows(rows)
        self.beginResetModel()
        try:
            self._rows = validated_rows
        finally:
            self.endResetModel()

    def _validated_rows(self, rows: Sequence[Sequence[Any]]) -> list[tuple[Any, ...]]:
        validated: list[tuple[Any, ...]] = []
        expected = len(self._headers)
        for row_index, row in enumerate(rows):
            values = tuple(row)
            if len(values) != expected:
                raise ValueError(
                    f"第 {row_index} 行列数错误: 期望 {expected}, 实际 {len(values)}"
                )
            validated.append(values)
        return validated
