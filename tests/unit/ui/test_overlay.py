import math
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.records import Alert, Revision, Snooze
from jiffin.lang.texts import TEXTS
from jiffin.ui import win32
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
HOLD_MS = 300
"""How long an answer waits with Undo in these tests, instead of 5 s."""
FRIDAY = datetime.fromisoformat("2026-10-02T19:00+00:00")
ACTION = "esportare le icone"
LONG_ACTION = (
    "esportare le icone del progetto Rossi in tutti i formati che ha chiesto il cliente, "
    "con i nomi giusti e le cartelle in ordine"
)
MENU = (
    TEXTS.snooze.next_time,
    TEXTS.snooze.quarter_hour,
    TEXTS.snooze.hour,
    TEXTS.snooze.tomorrow,
    TEXTS.alert.not_here,
)
"""Snooze's menu, from the top (#83)."""


class Answers:
    """The answers given on screen, in order: (what, alert id[, snooze])."""

    def __init__(self) -> None:
        self.given: list[tuple[object, ...]] = []

    def done(self, alert_id: int) -> None:
        self.given.append(("done", alert_id))

    def not_here(self, alert_id: int) -> None:
        self.given.append(("not_here", alert_id))

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self.given.append(("snooze", alert_id, snooze))

    def close(self, alert_id: int) -> None:
        self.given.append(("close", alert_id))

    def vanished(self, alert_id: int) -> None:
        self.given.append(("vanished", alert_id))


class Windows:
    """Windows' settings, as the look reads them; the test changes them."""

    def __init__(self) -> None:
        self.settings = DARK

    def read(self) -> Settings:
        return self.settings


class Capture:
    """What the overlay asks of screen capture, recorded instead of done: (window, excluded,
    whether the window showed then)."""

    def __init__(self) -> None:
        self.asked: list[tuple[int, bool, bool]] = []
        self.error = 0
        """What Windows answers: 0, or an error."""

    def exclude(self, hwnd: int, exclude: bool) -> int:
        window = next(w for w in QGuiApplication.topLevelWindows() if int(w.winId()) == hwnd)
        self.asked.append((hwnd, exclude, window.isVisible()))
        return self.error


class Front:
    """The windows the overlay put over all those always on top, in order."""

    def __init__(self) -> None:
        self.brought: list[int] = []

    def bring(self, hwnd: int) -> None:
        self.brought.append(hwnd)


class Mouse:
    """The mouse buttons, as Windows says them; the test presses them."""

    def __init__(self) -> None:
        self.down = False
        self.reads = 0

    def pressed(self) -> bool:
        self.reads += 1
        return self.down


def alert(
    alert_id: int,
    action: str = ACTION,
    condition: str = "quando apro Figma",
    perennial: bool = False,
) -> Alert:
    """An alert of a reminder written now, as `core` makes one."""
    reading = read(condition, FRIDAY)
    revision = Revision(
        alert_id,
        alert_id,
        1,
        condition,
        action,
        reading.remainder,
        schedule=reading.schedule,
        written_at=millis(FRIDAY),
        perennial=perennial,
    )
    context = Context("figma.exe", "Icone - Figma", None)
    now = millis(FRIDAY)
    return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, now, now, shown_at=now)


def millis(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


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

    def __init__(self, qtbot: QtBot, capture: Capture, mouse: Mouse, front: Front) -> None:
        self._qtbot = qtbot
        self.capture = capture
        self.mouse = mouse
        self.front = front
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.answers = Answers()
        before = set(QGuiApplication.topLevelWindows())
        clock = SimulatedClock(millis(FRIDAY))
        self.overlay = Overlay(self.engine, self.answers, Glass(self.look), clock)
        made = [w for w in QGuiApplication.topLevelWindows() if w not in before]
        self._windows = [w for w in made if w.title() == TEXTS.alert.title]
        for window in self._windows:
            window.setProperty("duration", WAIT_MS)
            window.setProperty("holdDuration", HOLD_MS)

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

    def menu(self, alert_id: int) -> QQuickWindow:
        """Snooze's menu of the alert, shown or not."""
        found = self.window(alert_id).property("menu")
        assert isinstance(found, QQuickWindow)
        return found

    def menus_shown(self) -> int:
        return sum(1 for window in self._windows if window.property("menu").isVisible())

    def click(self, alert_id: int, name: str) -> None:
        """Click the button a screen reader calls `name`, on the alert or on its open menu."""
        menu = self.menu(alert_id)
        window = menu if name in MENU and menu.isVisible() else self.window(alert_id)
        button = self.item(window, name)
        centre = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)

    def press(self, point: QPoint) -> None:
        """Press a mouse button at a point of the screen, wherever it is, and let it go."""
        self.hold(point)
        self.release()

    def hold(self, point: QPoint) -> None:
        """Press a mouse button at a point of the screen, until `release`."""
        QCursor.setPos(point)
        self.mouse.down = True
        self.read()

    def release(self) -> None:
        self.mouse.down = False
        self.read()

    def read(self) -> None:
        """Until the overlay has read the buttons once more, or reads them no more."""
        reads = self.mouse.reads
        self._qtbot.waitUntil(lambda: self.mouse.reads > reads or not self.menus_shown())

    def hover(self, alert_id: int) -> None:
        QTest.mouseMove(self.window(alert_id), QPoint(20, 20))

    def leave(self, alert_id: int) -> None:
        QTest.mouseMove(self.window(alert_id), QPoint(-20, -20))

    def text(self, alert_id: int, shown: str) -> QQuickItem:
        """The text item that shows `shown`."""
        return self._find(self.window(alert_id), lambda item: item.property("text") == shown)

    def item(self, window: QQuickWindow, name: str) -> QQuickItem:
        """The item a screen reader calls `name`."""
        return self._find(window, lambda item: accessible_name(item) == name)

    def names(self, window: QQuickWindow) -> list[str]:
        """What a screen reader calls the visible buttons of a window, from the top left."""
        for item in items(window.contentItem()):
            item.ensurePolished()
        found = [
            item
            for item in items(window.contentItem())
            if item.isVisible() and item.inherits("QQuickAbstractButton")
        ]
        found.sort(
            key=lambda item: (item.mapToScene(QPointF()).y(), item.mapToScene(QPointF()).x())
        )
        return [str(accessible_name(item)) for item in found]

    def _find(self, window: QQuickWindow, wanted: Callable[[QQuickItem], bool]) -> QQuickItem:
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
def capture(monkeypatch: pytest.MonkeyPatch) -> Capture:
    capture = Capture()
    monkeypatch.setattr(win32, "exclude_from_capture", capture.exclude)
    return capture


@pytest.fixture
def mouse(monkeypatch: pytest.MonkeyPatch) -> Mouse:
    mouse = Mouse()
    monkeypatch.setattr(win32, "mouse_pressed", mouse.pressed)
    return mouse


@pytest.fixture
def front(monkeypatch: pytest.MonkeyPatch) -> Front:
    front = Front()
    monkeypatch.setattr(win32, "bring_to_front", front.bring)
    return front


@pytest.fixture
def screen(
    qtbot: QtBot, dwm: list[tuple[object, ...]], capture: Capture, mouse: Mouse, front: Front
) -> Iterator[Screen]:
    screen = Screen(qtbot, capture, mouse, front)
    yield screen
    screen.show()  # every window leaves, and no countdown is left running
    qtbot.waitUntil(lambda: screen.on_screen() == [] and screen.menus_shown() == 0)


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


def test_an_alert_and_its_menu_never_take_the_focus(screen: Screen) -> None:
    screen.show(alert(1))
    for window in (screen.window(1), screen.menu(1)):
        for flag in (
            Qt.WindowType.WindowDoesNotAcceptFocus,
            Qt.WindowType.Tool,
            Qt.WindowType.WindowStaysOnTopHint,
            Qt.WindowType.FramelessWindowHint,
        ):
            assert window.flags() & flag


def test_an_alert_has_fatto_rimanda_and_the_x(screen: Screen) -> None:
    screen.show(alert(1))
    assert screen.names(screen.window(1)) == ["Fatto", "Rimanda", "Chiudi"]


def test_a_perennial_alert_has_the_icon_of_repetition(screen: Screen) -> None:
    screen.show(alert(1), alert(2, perennial=True))
    assert screen.text(1, "\ue8a5").isVisible()  # Document
    assert screen.text(2, "\ue8ee").isVisible()  # RepeatAll


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


def test_the_card_of_remind_here_goes_on_top_and_the_alerts_move_under_it_and_back(
    qtbot: QtBot, screen: Screen
) -> None:
    card = QQuickWindow()
    card.resize(540, 200)
    screen.overlay.above(card)
    assert (card.x(), card.y()) == top_centre(card)  # put in place before it shows
    screen.show(alert(1), alert(2))
    first, second = screen.window(1), screen.window(2)
    card.show()
    qtbot.waitUntil(lambda: first.y() == card.y() + card.height() + GAP)
    assert second.y() == first.y() + first.height() + GAP
    # An alert that comes while the card shows goes under it too.
    screen.show(alert(1), alert(2), alert(3))
    third = screen.window(3)
    assert third.y() == second.y() + second.height() + GAP
    card.hide()
    qtbot.waitUntil(lambda: (first.x(), first.y()) == top_centre(first))
    assert second.y() == first.y() + first.height() + GAP
    card.destroy()


def test_the_alerts_below_move_up_once_one_has_left(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1), alert(2), alert(3))
    screen.click(1, TEXTS.command.close)
    assert screen.answers.given == [("close", 1)]
    qtbot.waitUntil(lambda: screen.on_screen() == [2, 3])
    second = screen.window(2)
    assert (second.x(), second.y()) == top_centre(second)


def test_an_answered_alert_does_not_come_back_with_an_older_view(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1), alert(2))
    screen.click(1, TEXTS.alert.done)
    screen.show(alert(1), alert(2))  # `core` has not had the answer yet
    qtbot.waitUntil(lambda: screen.on_screen() == [2])
    screen.show(alert(1), alert(2))
    assert screen.on_screen() == [2]


def test_a_new_alert_waits_for_a_window_that_is_leaving(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1), alert(2), alert(3))
    screen.click(1, TEXTS.command.close)
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
        ([TEXTS.alert.done], ("done", 1)),
        ([TEXTS.alert.snooze, TEXTS.snooze.next_time], ("snooze", 1, Snooze.NEXT_TIME)),
        ([TEXTS.alert.snooze, TEXTS.snooze.quarter_hour], ("snooze", 1, Snooze.QUARTER_HOUR)),
        ([TEXTS.alert.snooze, TEXTS.snooze.hour], ("snooze", 1, Snooze.HOUR)),
        ([TEXTS.alert.snooze, TEXTS.snooze.tomorrow], ("snooze", 1, Snooze.TOMORROW)),
        ([TEXTS.alert.snooze, TEXTS.alert.not_here], ("not_here", 1)),
        ([TEXTS.command.close], ("close", 1)),
        ([TEXTS.alert.snooze, TEXTS.alert.snooze, TEXTS.alert.done], ("done", 1)),
    ],
)
def test_each_answer_is_a_click_or_two_away(
    qtbot: QtBot, screen: Screen, clicks: list[str], answer: tuple[object, ...]
) -> None:
    screen.show(alert(1))
    for name in clicks:
        screen.click(1, name)
    qtbot.waitUntil(lambda: screen.answers.given == [answer], timeout=3 * HOLD_MS)
    qtbot.waitUntil(lambda: screen.on_screen() == [] and screen.menus_shown() == 0)


@pytest.mark.parametrize(
    ("clicks", "name"),
    [
        ([TEXTS.alert.done], TEXTS.alert.done),
        ([TEXTS.alert.snooze, TEXTS.snooze.quarter_hour], TEXTS.snooze.quarter_hour),
        ([TEXTS.alert.snooze, TEXTS.alert.not_here], TEXTS.alert.not_here),
    ],
)
def test_an_answer_waits_5_seconds_under_its_name_with_annulla(
    qtbot: QtBot, screen: Screen, clicks: list[str], name: str
) -> None:
    screen.show(alert(1))
    window = screen.window(1)
    screen.hover(1)  # the mouse stays on the alert after the click, and does not stop the 5 s
    for click in clicks:
        screen.click(1, click)
    assert screen.names(window) == [TEXTS.command.cancel]
    assert screen.text(1, name).isVisible()
    assert screen.menus_shown() == 0
    assert screen.answers.given == []
    qtbot.waitUntil(lambda: len(screen.answers.given) == 1, timeout=3 * HOLD_MS)
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def test_annulla_puts_the_alert_back_with_its_10_seconds(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.done)
    screen.click(1, TEXTS.command.cancel)
    assert screen.names(screen.window(1)) == [
        TEXTS.alert.done,
        TEXTS.alert.snooze,
        TEXTS.command.close,
    ]
    assert screen.window(1).property("progress") > 0.8
    screen.hover(1)  # the 10 s stop under the mouse again
    qtbot.wait(2 * HOLD_MS)
    assert screen.answers.given == []
    screen.leave(1)
    qtbot.waitUntil(lambda: screen.answers.given == [("vanished", 1)], timeout=3 * WAIT_MS)


def test_an_alert_withdrawn_while_its_answer_waits_takes_the_answer_away(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.done)
    screen.show()  # its reminder was completed in the tray list meanwhile
    qtbot.waitUntil(lambda: screen.on_screen() == [])
    qtbot.wait(2 * HOLD_MS)
    assert screen.answers.given == []


def test_quitting_sends_a_waiting_answer_at_once(screen: Screen) -> None:
    screen.show(alert(1), alert(2))
    screen.click(1, TEXTS.alert.done)
    screen.click(2, TEXTS.alert.snooze)
    screen.click(2, TEXTS.snooze.hour)
    screen.overlay.close()
    assert screen.answers.given == [("done", 1), ("snooze", 2, Snooze.HOUR)]


def test_rimanda_opens_its_menu_under_the_button(screen: Screen) -> None:
    screen.windows.settings = LIGHT_SOLID_STILL  # no slide while it enters
    screen.look.refresh()
    screen.show(alert(1))
    window = screen.window(1)
    screen.click(1, TEXTS.alert.snooze)
    menu = screen.menu(1)
    assert menu.isVisible()
    assert screen.names(menu) == list(MENU)
    # On Snooze's left edge, 4 px under it, as QML rounds.
    button = screen.item(window, TEXTS.alert.snooze)
    corner = button.mapToItem(window.contentItem(), QPointF(0, button.height() + 4))
    x, y = (math.floor(value + 0.5) for value in (corner.x(), corner.y()))
    assert (menu.x(), menu.y()) == (window.x() + x, window.y() + y)
    # As wide as its longest item and 32 px, 120 px at least (#83).
    longest = screen.item(menu, TEXTS.snooze.next_time)
    assert menu.width() == max(120, round(longest.implicitWidth()) + 8)


def test_the_menu_has_alla_prossima_volta_only_with_a_next_unit(screen: Screen) -> None:
    screen.show(alert(1, condition="stasera"))
    screen.click(1, TEXTS.alert.snooze)
    assert screen.names(screen.menu(1)) == list(MENU[1:])
    assert screen.menu(1).width() >= 120


def test_the_menu_has_the_alerts_glass(screen: Screen, dwm: list[tuple[object, ...]]) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.snooze)
    hwnd = int(screen.menu(1).winId())
    assert ("set_backdrop", hwnd) in [call[:2] for call in dwm]
    assert ("nudge", hwnd) in dwm


def test_a_second_click_on_rimanda_closes_the_menu(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.snooze)
    screen.click(1, TEXTS.alert.snooze)
    assert not screen.menu(1).isVisible()
    assert screen.answers.given == []


def test_a_click_outside_the_menu_and_its_alert_closes_the_menu(screen: Screen) -> None:
    screen.show(alert(1))
    window = screen.window(1)
    screen.click(1, TEXTS.alert.snooze)
    menu = screen.menu(1)
    screen.press(menu.geometry().center())
    screen.press(window.geometry().topLeft() + QPoint(20, 20))
    assert menu.isVisible()
    screen.press(menu.geometry().bottomRight() + QPoint(40, 40))
    assert not menu.isVisible()
    assert screen.answers.given == []


def test_a_press_that_began_inside_does_not_close_the_menu_outside(screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.snooze)
    menu = screen.menu(1)
    screen.hold(menu.geometry().center())
    QCursor.setPos(menu.geometry().bottomRight() + QPoint(40, 40))
    screen.read()
    screen.read()
    assert menu.isVisible()
    screen.release()


def test_a_button_already_down_when_the_menu_opens_is_no_press(screen: Screen) -> None:
    screen.show(alert(1))
    QCursor.setPos(screen.window(1).geometry().bottomRight() + QPoint(40, 40))
    screen.mouse.down = True
    screen.click(1, TEXTS.alert.snooze)
    screen.read()
    screen.read()
    assert screen.menu(1).isVisible()
    screen.release()


def test_the_mouse_is_read_only_while_a_menu_is_open(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    qtbot.wait(100)
    assert screen.mouse.reads == 0
    screen.click(1, TEXTS.alert.snooze)
    qtbot.waitUntil(lambda: screen.mouse.reads > 1)
    screen.click(1, TEXTS.alert.snooze)
    reads = screen.mouse.reads
    qtbot.wait(100)
    assert screen.mouse.reads == reads


def test_alerts_and_menus_go_over_the_windows_always_on_top(screen: Screen) -> None:
    screen.show(alert(1))
    hwnd = int(screen.window(1).winId())
    assert screen.front.brought == [hwnd]
    screen.click(1, TEXTS.alert.snooze)
    assert screen.front.brought == [hwnd, int(screen.menu(1).winId())]


def test_an_open_menu_stays_over_a_new_alert(screen: Screen) -> None:
    screen.show(alert(1), alert(2))
    screen.click(1, TEXTS.alert.snooze)
    screen.show(alert(1), alert(2), alert(3))
    new, menu = int(screen.window(3).winId()), int(screen.menu(1).winId())
    assert screen.front.brought[-2:] == [new, menu]


def test_one_menu_is_open_at_a_time(screen: Screen) -> None:
    screen.show(alert(1), alert(2))
    screen.click(1, TEXTS.alert.snooze)
    screen.click(2, TEXTS.alert.snooze)
    assert (screen.menu(1).isVisible(), screen.menu(2).isVisible()) == (False, True)


def test_the_menu_leaves_with_its_alert(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.snooze)
    menu = screen.menu(1)
    screen.show()  # `core` no longer shows it
    assert not menu.isVisible()
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def test_the_menu_follows_its_alert_when_it_moves_up(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1), alert(2))
    screen.click(2, TEXTS.alert.snooze)
    menu, window = screen.menu(2), screen.window(2)
    below = menu.y() - window.y()
    screen.click(1, TEXTS.alert.done)
    qtbot.waitUntil(lambda: screen.on_screen() == [2])
    qtbot.waitUntil(lambda: window.y() == top_centre(window)[1])
    assert menu.isVisible()
    assert menu.y() - window.y() == below


def test_alerts_and_menus_are_out_of_screen_capture_while_they_show(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.show(alert(1))
    hwnd, menu = int(screen.window(1).winId()), int(screen.menu(1).winId())
    # Out of capture while still hidden, so that no frame of it is captured; back in once hidden.
    assert screen.capture.asked == [(hwnd, True, False)]
    screen.click(1, TEXTS.alert.snooze)
    screen.click(1, TEXTS.snooze.hour)
    qtbot.waitUntil(lambda: screen.on_screen() == [])
    assert screen.capture.asked == [
        (hwnd, True, False),
        (menu, True, False),
        (menu, False, False),
        (hwnd, False, False),
    ]


def test_a_refused_exclusion_leaves_the_alert_on_screen_and_says_why(
    screen: Screen, caplog: pytest.LogCaptureFixture
) -> None:
    screen.capture.error = 5
    screen.show(alert(1))
    assert screen.on_screen() == [1]
    assert "Windows error 5" in caplog.text


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


def test_the_time_stops_while_the_menu_is_open(qtbot: QtBot, screen: Screen) -> None:
    screen.show(alert(1))
    screen.click(1, TEXTS.alert.snooze)
    screen.leave(1)
    qtbot.wait(2 * WAIT_MS)
    assert screen.answers.given == []
    screen.click(1, TEXTS.alert.snooze)
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
    screen.click(1, TEXTS.alert.snooze)
    screen.click(1, TEXTS.snooze.tomorrow)
    qtbot.waitUntil(lambda: screen.on_screen() == [])


def test_the_line_names_the_time_understood(screen: Screen) -> None:
    screen.show(alert(1, condition="quando apro Claude dopo le 23"))
    assert screen.text(1, "Quando apro Claude · dalle 23:00 alle 04:00").isVisible()
