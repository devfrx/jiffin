"""Where the windows that keep their place open (ADR-0023), on bare windows on the offscreen
screen. The offscreen platform has no system move: the user's drag is played by moving the window,
which is all `Place` sees of it."""

from collections.abc import Mapping

import pytest
from PySide6.QtCore import QCoreApplication, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow
from pytestqt.qtbot import QtBot

from jiffin.ui.places import KEEP_AFTER_MS, Place, Places


class Desk:
    """The places, with what they gave the app to keep."""

    def __init__(self, kept: Mapping[str, tuple[int, int]] | None = None) -> None:
        self.kept: list[dict[str, tuple[int, int]]] = []
        self.places = Places(lambda places: self.kept.append(dict(places)))
        self.places.restore(kept or {})

    def window(self, name: str = "creation") -> "Window":
        return Window(self.places, name)


class Window:
    """A frameless window that follows its place, as the creation window does."""

    def __init__(self, places: Places, name: str) -> None:
        self.window = QQuickWindow()
        self.window.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.window.resize(400, 300)
        self.window.create()
        self.place: Place = places.follow(name, self.window)

    def open(self) -> None:
        self.place.open()
        self.window.show()

    def drag(self, x: int, y: int) -> None:
        """The user's drag, in three steps, each reaching the window before the next, as
        Windows' moves do."""
        start = self.window.framePosition()
        for step in (1, 2, 3):
            self.window.setFramePosition(
                QPoint(
                    start.x() + (x - start.x()) * step // 3, start.y() + (y - start.y()) * step // 3
                )
            )
            QCoreApplication.processEvents()

    def grow(self) -> None:
        self.window.resize(self.window.width(), self.window.height() + 100)
        self.place.resized()

    def at(self) -> tuple[int, int]:
        point = self.window.framePosition()
        return point.x(), point.y()

    def centred(self) -> tuple[int, int]:
        area = QGuiApplication.primaryScreen().availableGeometry()
        frame = self.window.frameGeometry()
        return (
            area.x() + (area.width() - frame.width()) // 2,
            area.y() + (area.height() - frame.height()) // 2,
        )


def settled(qtbot: QtBot) -> None:
    """Long enough for a move to be kept: nothing more comes after it."""
    qtbot.wait(2 * KEEP_AFTER_MS)


def test_a_window_never_moved_opens_at_the_centre_of_the_work_area(qtbot: QtBot) -> None:
    window = Desk().window()
    window.open()
    assert window.at() == window.centred()


def test_a_moved_window_is_kept_once_it_stops_moving(qtbot: QtBot) -> None:
    desk = Desk()
    window = desk.window()
    window.open()
    window.drag(30, 40)
    qtbot.waitUntil(lambda: desk.kept != [])
    settled(qtbot)
    assert desk.kept == [{"creation": (30, 40)}]


def test_a_moved_window_opens_again_where_it_was_left(qtbot: QtBot) -> None:
    desk = Desk()
    window = desk.window()
    window.open()
    window.drag(30, 40)
    # Closed at once: the move is kept as the window opens again.
    window.window.hide()
    window.open()
    assert window.at() == (30, 40)
    assert desk.kept == [{"creation": (30, 40)}]


def test_after_a_restart_a_window_opens_where_it_was_left(qtbot: QtBot) -> None:
    desk = Desk({"creation": (30, 40)})
    window = desk.window()
    window.open()
    assert window.at() == (30, 40)
    settled(qtbot)
    assert desk.kept == []


@pytest.mark.parametrize("where", ["unplugged", "partly off"])
def test_a_place_no_longer_whole_on_a_screen_opens_the_window_at_the_centre_and_stays_kept(
    qtbot: QtBot, where: str
) -> None:
    area = QGuiApplication.primaryScreen().availableGeometry()
    kept = (-5000, -5000) if where == "unplugged" else (area.right() - 100, area.y())
    desk = Desk({"creation": kept})
    window = desk.window()
    window.open()
    assert window.at() == window.centred()
    settled(qtbot)
    assert desk.kept == []
    assert desk.places.kept("creation") == QPoint(*kept)


def test_a_centred_window_stays_centred_as_it_grows_and_where_jiffin_puts_it_is_never_kept(
    qtbot: QtBot,
) -> None:
    desk = Desk()
    window = desk.window()
    window.open()
    window.grow()
    assert window.at() == window.centred()
    settled(qtbot)
    assert desk.kept == []


def test_a_moved_window_keeps_its_corner_as_it_grows(qtbot: QtBot) -> None:
    window = Desk().window()
    window.open()
    window.drag(30, 40)
    window.grow()
    assert window.at() == (30, 40)


def test_a_window_back_where_it_was_left_keeps_its_corner_as_it_grows(qtbot: QtBot) -> None:
    window = Desk({"creation": (30, 40)}).window()
    window.open()
    window.grow()
    assert window.at() == (30, 40)


def test_each_window_keeps_its_own_place(qtbot: QtBot) -> None:
    desk = Desk({"settings": (50, 60)})
    creation, settings = desk.window("creation"), desk.window("settings")
    creation.open()
    settings.open()
    creation.drag(30, 40)
    qtbot.waitUntil(lambda: desk.kept != [])
    assert desk.kept == [{"settings": (50, 60), "creation": (30, 40)}]
    assert settings.at() == (50, 60)
