"""The interface on the real screen, while the user types in another app: the alerts never
take the focus (#31, ADR-0009), and the shortcuts bring the creation window (#43) and the card
of Remind here (ADR-0029) to the front, which gives the focus back when it closes.

These tests run only on the owner's machine. `uv run pytest -m integration
tests/integration/test_ui.py` opens a window with a text box in front of everything, then
for about two minutes shows alerts, types in the box, moves the mouse over the alerts and
clicks their buttons, presses Win+Shift+N to write a reminder, and Win+Shift+Q to pick one.
Leave the computer alone meanwhile, and any window or dialog that shows up too: a click
anywhere moves the focus, which is what these tests watch.
"""

import ctypes
import subprocess
import sys
from collections.abc import Iterator, Mapping
from ctypes import POINTER, wintypes
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPointF, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlProperty, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.core.context import Context
from jiffin.core.records import Alert, Outcome, Reminder, Revision, Snooze
from jiffin.core.reminders import HereReminder, HereView, Pause
from jiffin.lang.texts import TEXTS
from jiffin.ui import hotkey
from jiffin.ui.alert import AlertSlot
from jiffin.ui.first_run import ModelFile
from jiffin.ui.interface import Interface
from jiffin.ui.look import Material

TARGET = [sys.executable, str(Path(__file__).with_name("target_window.py"))]
ROUNDS = 20
ANSWERS: tuple[tuple[tuple[str, ...], tuple[object, ...]], ...] = (
    ((TEXTS.alert.done,), ("done",)),
    ((TEXTS.alert.snooze, TEXTS.snooze.hour), ("snooze", Snooze.HOUR)),
    ((TEXTS.alert.snooze, TEXTS.snooze.next_time), ("snooze", Snooze.NEXT_TIME)),
    ((TEXTS.command.close,), ("close",)),
    ((TEXTS.alert.done, TEXTS.command.cancel, TEXTS.command.close), ("close",)),
)
"""How the rounds answer, in turn: the buttons clicked, on the alert or on Snooze's menu, and
the answer they give; the last one undoes a Done first (ADR-0030)."""
ON_THE_TEXT = QPointF(100, 20)
"""A point of an alert over its text, away from the buttons."""
VANISH_MS = 15_000
"""The alerts' 10 s, with room."""
HOLD_MS = 8_000
"""The 5 s an answer waits with Undo before the alert leaves, with room (ADR-0030)."""


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput), ("ki", _KeyboardInput))


class _Input(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _InputUnion))


class _GuiThreadInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    )


# name -> (result, arguments)
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "SendInput": (wintypes.UINT, [wintypes.UINT, POINTER(_Input), ctypes.c_int]),
    "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
    "GetForegroundWindow": (wintypes.HWND, []),
    "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, POINTER(wintypes.DWORD)]),
    "GetGUIThreadInfo": (wintypes.BOOL, [wintypes.DWORD, POINTER(_GuiThreadInfo)]),
    "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, POINTER(wintypes.RECT)]),
    "WindowFromPoint": (wintypes.HWND, [wintypes.POINT]),
    "SetWindowPos": (
        wintypes.BOOL,
        [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ],
    ),
    "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    "SendMessageW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "PostMessageW": (
        wintypes.BOOL,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
for _name, (_result, _arguments) in _USER32.items():
    _function = getattr(_user32, _name)
    _function.restype, _function.argtypes = _result, _arguments

_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_KEYEVENTF_KEYUP, _KEYEVENTF_UNICODE = 0x0002, 0x0004
_VK_TAB, _VK_RETURN, _VK_SHIFT, _VK_DOWN, _VK_LWIN = 0x09, 0x0D, 0x10, 0x28, 0x5B
_MOUSEEVENTF_MOVE, _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
_MOUSEEVENTF_VIRTUALDESK, _MOUSEEVENTF_ABSOLUTE = 0x4000, 0x8000
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77
_SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 78, 79
_WM_CLOSE, _WM_GETTEXT, _WM_GETTEXTLENGTH = 0x0010, 0x000D, 0x000E
_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010


def _send(events: list[_Input]) -> None:
    batch = (_Input * len(events))(*events)
    sent = _user32.SendInput(len(events), batch, ctypes.sizeof(_Input))
    assert sent == len(events), f"SendInput: {ctypes.WinError(ctypes.get_last_error())}"


def move_mouse(x: int, y: int) -> None:
    """Move the mouse as a real one does, to physical pixels; SetCursorPos alone sends no
    WM_MOUSEMOVE to the window below."""
    left = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    top = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    event = _Input(type=_INPUT_MOUSE)
    event.u.mi = _MouseInput(
        round((x - left) * 65535 / (width - 1)),
        round((y - top) * 65535 / (height - 1)),
        0,
        _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
        0,
        0,
    )
    _send([event])


def click(hwnd: int, x: int, y: int) -> None:
    """Click at a point of `hwnd`, only if it is the window there: never on another app."""
    under = _user32.WindowFromPoint(wintypes.POINT(x, y)) or 0
    assert under == hwnd, f"{class_name(under)!r} is where the click should go: no click"
    move_mouse(x, y)
    events = [_Input(type=_INPUT_MOUSE), _Input(type=_INPUT_MOUSE)]
    events[0].u.mi.dwFlags = _MOUSEEVENTF_LEFTDOWN
    events[1].u.mi.dwFlags = _MOUSEEVENTF_LEFTUP
    _send(events)


def on_top(hwnd: int, topmost: bool) -> None:
    after = _HWND_TOPMOST if topmost else _HWND_NOTOPMOST
    flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
    assert _user32.SetWindowPos(hwnd, after, 0, 0, 0, 0, flags)


def type_text(text: str) -> None:
    """Characters to the foreground window, as a keyboard types them."""
    events = []
    for character in text:
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            event = _Input(type=_INPUT_KEYBOARD)
            event.u.ki = _KeyboardInput(0, ord(character), flags, 0, 0)
            events.append(event)
    _send(events)


def press(*keys: int) -> None:
    """Keys held down in order, then let go: `press(_VK_LWIN, _VK_SHIFT, ord("N"))`."""
    events = []
    for key, flags in [(key, 0) for key in keys] + [(key, _KEYEVENTF_KEYUP) for key in keys[::-1]]:
        event = _Input(type=_INPUT_KEYBOARD)
        event.u.ki = _KeyboardInput(key, 0, flags, 0, 0)
        events.append(event)
    _send(events)


def foreground() -> int:
    return _user32.GetForegroundWindow() or 0


def rect(hwnd: int) -> tuple[int, int, int, int]:
    """Left, top, right and bottom, in physical pixels."""
    found = wintypes.RECT()
    assert _user32.GetWindowRect(hwnd, ctypes.byref(found))
    return found.left, found.top, found.right, found.bottom


def class_name(hwnd: int) -> str:
    name = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, name, len(name))
    return name.value


class Desk:
    """The app the user types in, in a process of its own, and where Windows says the focus is."""

    def __init__(self) -> None:
        self._process = subprocess.Popen(TARGET, stdout=subprocess.PIPE, text=True)
        assert self._process.stdout is not None
        self.window, self.box = (int(handle) for handle in self._process.stdout.readline().split())
        self.typed = ""
        self.moves: list[str] = []
        """Each step at which the focus was not in the box, and where it was."""

    def centre(self) -> tuple[int, int]:
        """The middle of the text box, away from the alerts, in physical pixels."""
        left, top, right, bottom = rect(self.box)
        return (left + right) // 2, (top + bottom) // 2

    def front(self) -> None:
        """Click in the box, as the user would, to bring it to the front. For the click its
        window is on top of every other, so that the click cannot reach another app."""
        on_top(self.window, True)
        click(self.box, *self.centre())
        on_top(self.window, False)

    def rest(self) -> None:
        """The mouse on the text box, away from the alerts."""
        move_mouse(*self.centre())

    def check(self, step: str) -> None:
        """The foreground window, the focus and the caret are still the box's."""
        foreground = _user32.GetForegroundWindow() or 0
        thread = _user32.GetWindowThreadProcessId(self.window, None)
        info = _GuiThreadInfo(cbSize=ctypes.sizeof(_GuiThreadInfo))
        _user32.GetGUIThreadInfo(thread, ctypes.byref(info))
        focus, caret = info.hwndFocus or 0, info.hwndCaret or 0
        if (foreground, focus, caret) != (self.window, self.box, self.box):
            self.moves.append(
                f"{step}: foreground {class_name(foreground)!r}, focus {focus:#x}, caret {caret:#x}"
            )

    def type(self, text: str, step: str) -> None:
        """Type in the box, and never elsewhere: if it has lost the foreground, the test stops."""
        if (_user32.GetForegroundWindow() or 0) != self.window:
            self.check(step)
            pytest.fail(f"the text box lost the foreground: {self.moves}")
        type_text(text)
        self.typed += text

    def text(self) -> str:
        length = _user32.SendMessageW(self.box, _WM_GETTEXTLENGTH, 0, 0)
        text = ctypes.create_unicode_buffer(length + 1)
        _user32.SendMessageW(self.box, _WM_GETTEXT, length + 1, ctypes.addressof(text))
        return text.value

    def close(self) -> None:
        _user32.PostMessageW(self.window, _WM_CLOSE, 0, 0)
        try:
            self._process.wait(10)
        except subprocess.TimeoutExpired:
            self._process.kill()


class Core:
    """What the interface asks of `core`, in order: the answers given on screen, (what, alert
    id[, snooze]), and the reminders changed there, (what, reminder id or texts). The card of
    Remind here gets `view`, on the next turn of the loop, as from the worker."""

    def __init__(self) -> None:
        self.given: list[tuple[object, ...]] = []
        self.made: list[tuple[object, ...]] = []
        self.view = HereView(None)
        self.interface: Interface | None = None

    def here(self) -> None:
        interface, view = self.interface, self.view
        assert interface is not None
        QTimer.singleShot(0, lambda: interface.show_here(view))

    def remind_here(self, reminder_id: int, context: Context) -> None:
        self.given.append(("remind_here", reminder_id, context))

    def withdraw(self, reminder_id: int, context: Context) -> None:
        self.made.append(("withdraw", reminder_id, context))

    def withdraw_all(self, reminder_id: int) -> None:
        self.made.append(("withdraw_all", reminder_id))

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

    def seen(self) -> None:
        self.given.append(("seen",))

    def create(self, condition: str, action: str, perennial: bool) -> None:
        self.made.append(("create", condition, action, perennial))

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None:
        self.made.append(("edit", reminder_id, condition, action, perennial))

    def complete(self, reminder_id: int) -> None:
        self.made.append(("complete", reminder_id))

    def reopen(self, reminder_id: int) -> None:
        self.made.append(("reopen", reminder_id))

    def delete(self, reminder_id: int) -> None:
        self.made.append(("delete", reminder_id))


class Upkeep:
    """The app's part around core: nothing here asks for it."""

    def restart_engine(self) -> None:
        pass

    def fetch_model(self) -> None:
        pass

    def keep_material(self, material: Material) -> None:
        pass

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        pass

    def keep_return_pause(self, seconds: int) -> None:
        pass

    def pause(self, pause: Pause) -> None:
        pass

    def resume(self) -> None:
        pass


class Screen:
    """The app's interface, made as the app makes it, with core's part played by the test."""

    def __init__(self, app: QGuiApplication, tmp: Path) -> None:
        self.core = Core()
        model = ModelFile("model.gguf", "https://example.org/model.gguf", 1, "0" * 64, tmp)
        self.interface = Interface(app, self.core, Upkeep(), model)
        self.core.interface = self.interface

    def show(self, *alert_ids: int) -> None:
        alerts = tuple(alert(alert_id) for alert_id in alert_ids)
        self.interface.show_alerts(AlertsView(alerts, 0, ()))

    def window(self, alert_id: int) -> QQuickWindow:
        for window in QGuiApplication.topLevelWindows():
            found = window.findChild(AlertSlot)
            if window.isVisible() and found is not None and found.alert_id == alert_id:
                assert isinstance(window, QQuickWindow)
                return window
        raise LookupError(f"alert {alert_id} is not on screen")

    def none_shown(self) -> bool:
        return not any(w.isVisible() for w in QGuiApplication.topLevelWindows())

    def creation(self) -> QQuickWindow:
        for window in QGuiApplication.topLevelWindows():
            if window.title() in (TEXTS.creation.new, TEXTS.creation.edit):
                assert isinstance(window, QQuickWindow)
                return window
        raise LookupError("no creation window")

    def card(self) -> QQuickWindow:
        for window in QGuiApplication.topLevelWindows():
            if window.title() == TEXTS.remind_here.title:
                assert isinstance(window, QQuickWindow)
                return window
        raise LookupError("no card of Remind here")


def alert(alert_id: int) -> Alert:
    revision = Revision(
        alert_id,
        alert_id,
        1,
        "quando apro Figma",
        f"esportare le icone {alert_id}",
        "quando apro Figma",
    )
    context = Context("figma.exe", "Icone - Figma", None)
    return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, 0, 0, shown_at=0)


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def button(window: QQuickWindow, name: str) -> QPointF:
    """The centre of the button a screen reader calls `name`, in the window."""

    def named(item: QQuickItem) -> bool:
        context = qmlContext(item)
        return context is not None and QQmlProperty(item, "Accessible.name", context).read() == name

    # Rows place what they show only when polished, before the next frame.
    for item in items(window.contentItem()):
        item.ensurePolished()
    found = next(item for item in items(window.contentItem()) if item.isVisible() and named(item))
    return found.mapToScene(QPointF(found.width() / 2, found.height() / 2))


def holder(window: QQuickWindow) -> QQuickWindow:
    """Where the next button is: Snooze's menu while it is open, else the alert."""
    menu = window.property("menu")
    assert isinstance(menu, QQuickWindow)
    return menu if menu.isVisible() else window


def on_screen(window: QQuickWindow, point: QPointF) -> tuple[int, int]:
    """A point of the window, in physical pixels on the screen."""
    left, top, _, _ = rect(int(window.winId()))
    ratio = window.devicePixelRatio()
    return round(left + point.x() * ratio), round(top + point.y() * ratio)


@pytest.fixture(scope="session")
def qapp_cls() -> type[QGuiApplication]:
    return QGuiApplication


@pytest.fixture(scope="module")
def screen(qapp: QGuiApplication, tmp_path_factory: pytest.TempPathFactory) -> Screen:
    assert qapp.platformName() == "windows", "run the integration tests apart from the unit tests"
    return Screen(qapp, tmp_path_factory.mktemp("models"))


@pytest.fixture
def desk(qtbot: QtBot) -> Iterator[Desk]:
    desk = Desk()
    qtbot.wait(1000)  # the window shows, maximized
    desk.front()
    qtbot.wait(500)
    desk.check("start")
    assert desk.moves == [], "the text box must have the focus to start"
    yield desk
    desk.close()


@pytest.mark.integration
def test_an_alert_never_takes_the_focus_from_where_the_user_types(
    qtbot: QtBot, screen: Screen, desk: Desk
) -> None:
    before = len(screen.core.given)
    expected: list[tuple[object, ...]] = []
    for turn in range(1, ROUNDS + 1):
        screen.show(turn)
        qtbot.wait(500)
        desk.check(f"{turn} shown")
        desk.type(f"a{turn:02d} ", f"{turn} typing")
        qtbot.wait(200)
        desk.check(f"{turn} typed")

        window = screen.window(turn)
        move_mouse(*on_screen(window, ON_THE_TEXT))
        qtbot.wait(300)
        progress = window.property("progress")
        qtbot.wait(1200)
        assert window.property("progress") == progress, f"{turn}: the time ran under the mouse"
        desk.check(f"{turn} hovered")

        names, (what, *rest) = ANSWERS[turn % len(ANSWERS)]
        for name in names:
            target = holder(window)
            x, y = on_screen(target, button(target, name))
            move_mouse(x, y)
            qtbot.wait(200)
            click(int(target.winId()), x, y)
            qtbot.wait(300)
            desk.check(f"{turn} clicked {name}")
        expected.append((what, turn, *rest))
        qtbot.waitUntil(screen.none_shown, timeout=HOLD_MS)
        desk.check(f"{turn} left")

        desk.rest()
        desk.type(f"b{turn:02d} ", f"{turn} typing again")
        qtbot.wait(200)
        desk.check(f"{turn} typed again")

    assert desk.moves == []
    assert desk.text() == desk.typed
    assert screen.core.given[before:] == expected


@pytest.mark.integration
def test_rimandas_menu_is_over_the_alert_below(qtbot: QtBot, screen: Screen, desk: Desk) -> None:
    """A window shown without activation keeps its old place among those always on top: the
    menu of the alert above went under the alert below (#102)."""
    before = len(screen.core.given)
    screen.show(201, 202)
    qtbot.wait(500)
    upper, lower = screen.window(201), screen.window(202)
    x, y = on_screen(upper, button(upper, TEXTS.alert.snooze))
    move_mouse(x, y)
    qtbot.wait(200)
    click(int(upper.winId()), x, y)
    qtbot.wait(300)
    menu = holder(upper)
    assert menu is not upper, "Rimanda's menu did not open"
    left, top, right, bottom = rect(int(menu.winId()))
    lower_left, lower_top, lower_right, lower_bottom = rect(int(lower.winId()))
    # A point of the menu over the alert below.
    inside = wintypes.POINT(
        (max(left, lower_left) + min(right, lower_right)) // 2,
        (max(top, lower_top) + min(bottom, lower_bottom)) // 2,
    )
    under = _user32.WindowFromPoint(inside) or 0
    assert under == int(menu.winId()), f"{class_name(under)!r} is over the menu"
    desk.check("menu open over the alert below")
    click(int(upper.winId()), x, y)  # Snooze again: the menu closes
    qtbot.waitUntil(lambda: not menu.isVisible())
    screen.show()  # `core` takes both alerts away
    qtbot.waitUntil(screen.none_shown)
    desk.check("menu and alerts gone")
    assert desk.moves == []
    assert screen.core.given[before:] == []


@pytest.mark.integration
def test_three_alerts_vanish_on_their_own_and_leave_the_focus_alone(
    qtbot: QtBot, screen: Screen, desk: Desk
) -> None:
    before = len(screen.core.given)
    screen.show(101, 102, 103)
    qtbot.wait(500)
    desk.check("three shown")
    desk.type("tre ", "three shown")
    qtbot.waitUntil(lambda: len(screen.core.given) == before + 3, timeout=VANISH_MS)
    qtbot.waitUntil(screen.none_shown)
    desk.check("three vanished")
    assert desk.moves == []
    assert sorted(screen.core.given[before:], key=str) == [
        ("vanished", 101),
        ("vanished", 102),
        ("vanished", 103),
    ]
    assert desk.text() == desk.typed


@pytest.mark.integration
def test_the_shortcut_brings_the_creation_window_over_another_app(
    qtbot: QtBot, screen: Screen, desk: Desk
) -> None:
    assert hotkey.NEW in screen.interface.hotkeys.registered, "another app holds Win+Shift+N"
    window = screen.creation()
    desk.type("prima ", "before the shortcut")
    press(_VK_LWIN, _VK_SHIFT, ord("N"))
    qtbot.waitUntil(lambda: foreground() == int(window.winId()))
    qtbot.waitUntil(lambda: focused(window) == TEXTS.creation.condition)
    type_text("quando apro Figma")
    press(_VK_TAB)
    type_text("esportare le icone")
    press(_VK_RETURN)
    qtbot.waitUntil(lambda: not window.isVisible())
    assert screen.core.made == [("create", "quando apro Figma", "esportare le icone", False)]
    qtbot.waitUntil(lambda: foreground() == desk.window)
    qtbot.wait(300)
    desk.check("creation window closed")
    desk.type("dopo ", "after the creation window")
    qtbot.wait(200)
    assert desk.moves == []
    assert desk.text() == desk.typed


@pytest.mark.integration
def test_the_shortcut_brings_the_card_of_remind_here_over_another_app_and_gives_it_back(
    qtbot: QtBot, screen: Screen, desk: Desk
) -> None:
    assert hotkey.HERE in screen.interface.hotkeys.registered, "another app holds Win+Shift+Q"
    place = Context("figma.exe", "Icone - Figma", None)
    first, second = alert(1), alert(2)
    screen.core.view = HereView(
        place,
        (
            HereReminder(Reminder(1, 0, first.revision), None),
            HereReminder(Reminder(2, 0, second.revision), Outcome.SNOOZED),
        ),
    )
    desk.type("prima ", "before the shortcut")
    press(_VK_LWIN, _VK_SHIFT, ord("Q"))
    card = screen.card()
    qtbot.waitUntil(lambda: foreground() == int(card.winId()))
    press(_VK_DOWN)
    press(_VK_DOWN)
    press(_VK_RETURN)
    qtbot.waitUntil(lambda: not card.isVisible())
    assert screen.core.given[-1] == ("remind_here", 2, place)
    qtbot.waitUntil(lambda: foreground() == desk.window)
    qtbot.wait(300)
    desk.check("card closed")
    desk.type("dopo ", "after the card")
    qtbot.wait(200)
    assert desk.moves == []
    assert desk.text() == desk.typed


def focused(window: QQuickWindow) -> object:
    """The name a screen reader gives the item with the keyboard focus."""
    item = window.activeFocusItem()
    context = None if item is None else qmlContext(item)
    if item is None or context is None:
        return None
    return QQmlProperty(item, "Accessible.name", context).read()
