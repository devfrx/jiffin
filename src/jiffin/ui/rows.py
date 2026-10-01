"""Rows for a QML Repeater, one per key, that a new list updates in place.

A row whose key stays keeps its delegate: the keyboard focus stays on its buttons, and a panel
it has open stays open, while other rows come and go.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

Row = Mapping[str, object]
_ROOT = QModelIndex()
"""The parent of every row: a list has no tree."""


class Rows(QAbstractListModel):
    def __init__(self, key: str, roles: Sequence[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = key
        names = (key, *roles)
        self._roles = {Qt.ItemDataRole.UserRole + i: name for i, name in enumerate(names)}
        self._rows: list[Row] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        name = self._roles.get(role)
        if not index.isValid() or name is None:
            return None
        return self._rows[index.row()][name]

    def roleNames(self) -> dict[int, QByteArray]:
        return {role: QByteArray(name.encode()) for role, name in self._roles.items()}

    def replace(self, rows: Sequence[Row]) -> None:
        """Show these rows, in this order: the rows gone leave, the new ones come in, and the
        rows that stay change only where they differ."""
        keys = {row[self._key] for row in rows}
        old = {row[self._key] for row in self._rows}
        if [row[self._key] for row in self._rows if row[self._key] in keys] != [
            row[self._key] for row in rows if row[self._key] in old
        ]:
            # The rows that stay changed order, which the lists here never do.
            self.beginResetModel()
            self._rows = list(rows)
            self.endResetModel()
            return
        for index in reversed(range(len(self._rows))):
            if self._rows[index][self._key] not in keys:
                self.beginRemoveRows(_ROOT, index, index)
                del self._rows[index]
                self.endRemoveRows()
        for index, row in enumerate(rows):
            if index < len(self._rows) and self._rows[index][self._key] == row[self._key]:
                if self._rows[index] != row:
                    self._rows[index] = row
                    self.dataChanged.emit(self.index(index), self.index(index))
            else:
                self.beginInsertRows(_ROOT, index, index)
                self._rows.insert(index, row)
                self.endInsertRows()
