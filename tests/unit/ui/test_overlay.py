from collections.abc import Callable, Iterator

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.core.context import Context
from jiffin.core.records import Alert, Revision, Snooze
from jiffin.ui.alert import AlertSlot
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings
from jiffin.ui.overlay import GAP, TOP, Overlay

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
LIGHT_SOLID_STILL = Settings(
    dark=False,
    accent="#005fb8",
    transparency=False,
    animations=False,
    taskbar_dark=False,
    taskbar_accent="#005fb8",
)
WAIT_MS = 500
"""How long the alerts of these tests wait for an answer, instead of 10 s."""
ACTION = "esportare le icone"
LONG_ACTION = (
    "esportare le icone del progetto Rossi in tutti i formati che ha chiesto il cliente, "
    "con i nomi giusti e le cartelle in ordine"
)


class Answers:
    """The answers given on screen, in order: (what, alert id[, snooze])."""

    def __init__(self) -> None:
        self.given: list[tuple[object, ...]] = []

    def done(self, alert_id: int) -> None:
        self.given.append(("done", alert_id))

    def useful(self, alert_id: int) -> None:
        self.given.append(("useful", alert_id))

    def not_here(self, alert_id: int) -> None:
        self.given.append(("not_here", alert_id))

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self.given.append(("snooze", alert_id, snooze))

    def vanished(self, alert_id: int) -> None:
        self.given.append(("vanished", alert_id))


class Windows:
    """Windows' settings, as the look reads them; the test changes them."""

    def __init__(self) -> None:
        self.settings = DARK

    def read(self) -> Settings:
        return self.settings


def alert(alert_id: int, action: str = ACTION) -> Alert:
    revision = Revision(alert_id, alert_id, 1, "quando apro Figma", action, "quando apro Figma")
    context = Context("figma.exe", "Icone - Figma", None)
    return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, 0, 0, shown_at=0)


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def slot(window: QWindow) -> AlertSlot:
    found = window.findChild(AlertSlot)
    assert found is not None
    return found


class Screen:
    """The overlay on the offscreen screen, with the answers given there."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.answers = Answers()
        before = set(QGuiApplication.topLevelWindows())
        self.overlay = Overlay(self.engine, self.answers, Glass(self.look))
        self._windows = [w for w in QGuiApplication.topLevelWindows() if w not in before]
        for window in self._windows:
            window.setProperty("duration", WAIT_MS)

    def show(self, *alerts: Alert) -> None:
        """`core`'s view: these alerts on screen, oldest first."""
        self.overlay.show(AlertsView(alerts, 0, ()))

    def on_screen(self) -> list[int | None]:
        """The alerts whose window is shown, from the top."""
        shown = sorted((w for w in self._windows if w.isVisible()), key=lambda w: w.y())
        return [slot(window).alert_id for window in shown]

    def window(self, alert_id: int) -> QQuickWindow:
        found = next(w for w in self._windows if w.isVisible() and slot(w).alert_id == alert_id)
        assert isinstance(found, QQuickWindow)
        return found

    def click(self, alert_id: int, name: str) -> None:
        """Click the button a screen reader calls `name` on the alert."""
        window = self.window(alert_id)
        button = self._item(window, lambda item: accessible_name(item) == name)
        centre = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)

    def hover(self, alert_id: int) -> None:
        QTest.mouseMove(self.window(alert_id), QPoint(20, 20))

    def leave(self, alert_id: int) -> None:
        QTest.mouseMove(self.window(alert_id), QPoint(-20, -20))

    def text(self, alert_id: int, shown: str) -> QQuickItem:
        """The text item that shows `shown`."""
        return self._item(self.window(alert_id), lambda item: item.property("text") == shown)

    def _item(self, window: QQuickWindow, wanted: Callable[[QQuickItem], bool]) -> QQuickItem:
        # Rows place what they show only when polished, before the next frame.
        for item in items(window.contentItem()):
            item.ensurePolished()
        return next(
            item for item in items(window.contentItem()) if item.isVisible() and wanted(item)
        )


def accessible_name(item: QQuickItem) -> object:
    context = qmlContext(item)
    assert context is not None
    return QQmlProperty(item, "Accessible.name", context).read()


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]]) -> Iterator[Screen]:
    screen = Screen(qtbot)
    yield screen
    screen.show()  # every window leaves, and no countdown is left running
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def top_centre(window: QWindow) -> tuple[int, int]:
    area = QGuiApplication.primaryScreen().availableGeometry()
    return area.x() + (area.width() - window.width()) // 2, area.y() + TOP


def test_an_alert_shows_at_the_top_centre_with_the_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    screen.show(alert(1))
    assert screen.on_screen() == [1]
    window = screen.window(1)
    assert (window.x(), window.y()) == top_centre(window)
    assert ("nudge", int(window.winId())) in dwm


def test_an_alert_window_never_takes_the_focus(screen: Screen) -> None:
    screen.show(alert(1))
    flags = screen.window(1).flags()
    for flag in (
        Qt.WindowType.WindowDoesNotAcceptFocus,
        Qt.WindowType.Tool,
        Qt.WindowType.WindowStaysOnTopHint,
        Qt.WindowType.FramelessWindowHint,
    ):
        assert flags & flag


def test_alerts_stack_from_the_top_in_the_order_they_came(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1, LONG_ACTION), alert(2), alert(3))
    assert screen.on_screen() == [1, 2, 3]
    first, second, third = (screen.window(i) for i in (1, 2, 3))

    def stacked() -> bool:
        # The long action wraps once the window is laid out, and the others move down.
        return (
            first.height() > second.height()
            and (first.x(), first.y()) == top_centre(first)
            and second.y() == first.y() + first.height() + GAP
            and third.y() == second.y() + second.height() + GAP
        )

    qtbot.waitUntil(stacked)


def test_the_alerts_below_move_up_once_one_has_left(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1), alert(2), alert(3))
    screen.click(1, "Fatto")
    assert screen.answers.given == [("done", 1)]
    qtbot.waitUntil(lambda: screen.on_screen() == [2, 3])
    second = screen.window(2)
    assert (second.x(), second.y()) == top_centre(second)


def test_an_answered_alert_does_not_come_back_with_an_older_view(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1), alert(2))
    screen.click(1, "Fatto")
    screen.show(alert(1), alert(2))  # `core` has not had the answer yet
    qtbot.waitUntil(lambda: screen.on_screen() == [2])
    screen.show(alert(1), alert(2))
    assert screen.on_screen() == [2]


def test_a_new_alert_waits_for_a_window_that_is_leaving(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1), alert(2), alert(3))
    screen.click(1, "Fatto")
    screen.show(alert(2), alert(3), alert(4))  # `core` put the next alert in its place
    assert 4 not in screen.on_screen()
    qtbot.waitUntil(lambda: screen.on_screen() == [2, 3, 4])


def test_an_alert_core_no_longer_shows_leaves_without_an_answer(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1), alert(2))
    screen.show(alert(2))
    qtbot.waitUntil(lambda: screen.on_screen() == [2])
    assert screen.answers.given == []


@pytest.mark.parametrize(
    ("clicks", "answer"),
    [
        (["Fatto"], ("done", 1)),
        (["Rimanda", "15 min"], ("snooze", 1, Snooze.QUARTER_HOUR)),
        (["Rimanda", "1 ora"], ("snooze", 1, Snooze.HOUR)),
        (["Rimanda", "Domani"], ("snooze", 1, Snooze.TOMORROW)),
        (["Altre azioni", "Utile"], ("useful", 1)),
        (["Altre azioni", "Non qui"], ("not_here", 1)),
        (["Rimanda", "Indietro", "Altre azioni", "Indietro", "Fatto"], ("done", 1)),
    ],
)
def test_each_answer_is_a_click_or_two_away(
    qtbot: QtBot, screen: Screen, clicks: list[str], answer: tuple[object, ...]
) -> None:
    screen.show(alert(1))
    for name in clicks:
        screen.click(1, name)
    assert screen.answers.given == [answer]
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def test_an_alert_vanishes_when_its_time_is_up(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    qtbot.waitUntil(lambda: screen.answers.given == [("vanished", 1)], timeout=3 * WAIT_MS)
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def test_the_time_stops_while_the_mouse_is_over_the_alert(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.hover(1)
    progress = screen.window(1).property("progress")
    qtbot.wait(2 * WAIT_MS)
    assert screen.answers.given == []
    assert screen.window(1).property("progress") == progress
    screen.leave(1)
    qtbot.waitUntil(lambda: screen.answers.given == [("vanished", 1)], timeout=3 * WAIT_MS)


def test_the_time_stops_while_a_panel_is_open(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, "Altre azioni")
    screen.leave(1)
    qtbot.wait(2 * WAIT_MS)
    assert screen.answers.given == []
    screen.click(1, "Indietro")
    screen.leave(1)
    qtbot.waitUntil(lambda: screen.answers.given == [("vanished", 1)], timeout=3 * WAIT_MS)


def test_the_alert_follows_a_change_of_look_while_it_is_on_screen(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1))
    action = screen.text(1, "Esportare le icone")
    assert QColor(action.property("color")) == QColor("#FFFFFFFF")
    screen.windows.settings = LIGHT_SOLID_STILL
    screen.look.refresh()
    assert QColor(action.property("color")) == QColor("#E4000000")
    screen.click(1, "Rimanda")
    screen.click(1, "Domani")
    qtbot.waitUntil(lambda: screen.on_screen() == [])
