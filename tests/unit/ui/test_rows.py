from PySide6.QtCore import Qt
from pytestqt.modeltest import ModelTester
from pytestqt.qtbot import QtBot

from jiffin.ui.rows import Row, Rows


def rows(*keys: int, text: str = "") -> list[Row]:
    return [{"key": key, "text": text or f"riga {key}"} for key in keys]


def shown(model: Rows) -> list[tuple[object, object]]:
    key, text = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1
    return [
        (model.data(model.index(i), key), model.data(model.index(i), text))
        for i in range(model.rowCount())
    ]


class Signals:
    """What the model told its views, in order."""

    def __init__(self, model: Rows) -> None:
        self.heard: list[tuple[object, ...]] = []
        model.rowsInserted.connect(lambda _, first, last: self.heard.append(("in", first, last)))
        model.rowsRemoved.connect(lambda _, first, last: self.heard.append(("out", first, last)))
        model.dataChanged.connect(
            lambda first, last: self.heard.append(("changed", first.row(), last.row()))
        )
        model.modelReset.connect(lambda: self.heard.append(("reset",)))


def test_the_roles_are_the_key_and_the_others_by_name(qtmodeltester: ModelTester) -> None:
    model = Rows("key", ("text",))
    model.replace(rows(1, 2))
    qtmodeltester.check(model)  # type: ignore[no-untyped-call]
    assert [bytes(name.data()) for name in model.roleNames().values()] == [b"key", b"text"]
    assert shown(model) == [(1, "riga 1"), (2, "riga 2")]


def test_a_new_list_moves_only_what_changed(qtbot: QtBot) -> None:
    model = Rows("key", ("text",))
    model.replace(rows(3, 2, 1))
    signals = Signals(model)
    model.replace([*rows(4), *rows(3, text="cambiata"), *rows(1)])
    assert shown(model) == [(4, "riga 4"), (3, "cambiata"), (1, "riga 1")]
    assert signals.heard == [("out", 1, 1), ("in", 0, 0), ("changed", 1, 1)]
    signals.heard.clear()
    model.replace([*rows(4), *rows(3, text="cambiata"), *rows(1)])
    assert signals.heard == []


def test_rows_that_change_order_start_over(qtbot: QtBot) -> None:
    model = Rows("key", ("text",))
    model.replace(rows(1, 2))
    signals = Signals(model)
    model.replace(rows(2, 1))
    assert shown(model) == [(2, "riga 2"), (1, "riga 1")]
    assert signals.heard == [("reset",)]
