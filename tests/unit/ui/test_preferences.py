import gc
from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext, qmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.ui import win32
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Material, Settings
from jiffin.ui.places import Places
from jiffin.ui.preferences import Preferences

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
NAMES = ["Acrilico", "Acrilico dei menu", "Mica", "Mica Alt"]


class Windows:
    """Windows' settings, as the look reads them; the test changes them."""

    def __init__(self) -> None:
        self.settings = DARK

    def read(self) -> Settings:
        return self.settings


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def accessible(item: QQuickItem, name: str) -> object:
    """None for the items a control makes on its own, which QML never sees."""
    context = qmlContext(item)
    return None if context is None else QQmlProperty(item, f"Accessible.{name}", context).read()


class Screen:
    """The settings window on the offscreen screen, with the materials and the places it
    kept."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.kept: list[Material] = []
        self.placed: list[dict[str, tuple[int, int]]] = []
        self.places = Places(lambda places: self.placed.append(dict(places)))
        self.preferences = Preferences(
            self.engine, self.look, self.kept.append, Glass(self.look), self.places
        )
        (window,) = (w for w in QGuiApplication.topLevelWindows() if qmlEngine(w) is self.engine)
        assert isinstance(window, QQuickWindow)
        self.window = window

    def open(self) -> None:
        """What Impostazioni in the tray icon's menu does; ready once it has the focus."""
        self.preferences.open()
        self._qtbot.waitUntil(self.window.isActive)

    def press(self, key: Qt.Key) -> None:
        QTest.keyClick(self.window, key)

    def click(self, name: str) -> None:
        control = self._item(lambda item: accessible(item, "name") == name)
        centre = control.mapToScene(QPointF(control.width() / 2, control.height() / 2)).toPoint()
        QTest.mouseClick(
            self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre
        )

    def focused(self) -> object:
        item = self.window.activeFocusItem()
        return None if item is None else accessible(item, "name")

    def choices(self) -> list[QQuickItem]:
        return self._items(lambda item: item.inherits("QQuickRadioButton"))

    def checked(self) -> list[object]:
        return [accessible(item, "name") for item in self.choices() if item.property("checked")]

    def shows(self, text: str) -> bool:
        return bool(
            self._items(lambda item: item.inherits("QQuickText") and item.property("text") == text)
        )

    def _item(self, wanted: Callable[[QQuickItem], bool]) -> QQuickItem:
        (item, *_) = self._items(wanted)
        return item

    def _items(self, wanted: Callable[[QQuickItem], bool]) -> list[QQuickItem]:
        # Layouts place what they show only when polished, before the next frame.
        for item in items(self.window.contentItem()):
            item.ensurePolished()
        return [
            item for item in items(self.window.contentItem()) if item.isVisible() and wanted(item)
        ]


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]]) -> Iterator[Screen]:
    screen = Screen(qtbot)
    yield screen
    screen.preferences.close()


def centred(window: QWindow) -> bool:
    area = QGuiApplication.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    return (frame.x(), frame.y()) == (
        area.x() + (area.width() - frame.width()) // 2,
        area.y() + (area.height() - frame.height()) // 2,
    )


def stays_centred(qtbot: QtBot, window: QWindow) -> None:
    """The window grows as soon as its layout runs, and moves when Windows says it grew: Qt
    emits heightChanged from its window-system queue, after `height()` already reads the new
    height."""
    qtbot.waitUntil(lambda: centred(window))


def test_impostazioni_opens_the_window_centred_with_the_focus_on_the_material_in_use(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.open()
    window = screen.window
    stays_centred(qtbot, window)
    assert window.title() == "Impostazioni"
    assert screen.shows("Impostazioni")
    assert [accessible(choice, "name") for choice in screen.choices()] == NAMES
    assert screen.checked() == ["Acrilico dei menu"]
    assert screen.focused() == "Acrilico dei menu"


def test_each_material_says_what_it_looks_like(screen: Screen) -> None:
    screen.open()
    assert [accessible(choice, "description") for choice in screen.choices()] == [
        "Vetro chiaro: dietro si vede sfocato.",
        "Quasi pieno, come i menu di Windows. Predefinito.",
        "Come le Impostazioni di Windows: prende il colore dello sfondo.",
        "Più scuro, con più colore dello sfondo.",
    ]


def test_the_window_is_a_card_on_the_alerts_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    flags = screen.window.flags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    hwnd = int(screen.window.winId())
    assert dwm == [("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW)]


def test_a_click_on_a_material_changes_the_glass_at_once_and_keeps_the_choice(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    screen.open()
    del dwm[:]
    screen.click("Mica")
    hwnd = int(screen.window.winId())
    assert screen.look.material is Material.MICA
    assert dwm == [
        ("set_backdrop", hwnd, True, win32.DWMSBT_MAINWINDOW),
        ("activate_frame", hwnd),
    ]
    assert screen.checked() == ["Mica"]
    assert screen.kept == [Material.MICA]
    assert screen.window.isVisible()


def test_the_material_in_use_keeps_its_check_and_is_not_kept_again(screen: Screen) -> None:
    screen.open()
    screen.click("Acrilico dei menu")
    assert screen.checked() == ["Acrilico dei menu"]
    assert screen.kept == []


def test_the_check_follows_the_material_set_at_the_start(screen: Screen) -> None:
    screen.look.material = Material.MICA_ALT
    screen.open()
    assert screen.checked() == ["Mica Alt"]
    assert screen.focused() == "Mica Alt"
    assert screen.kept == []


def test_tab_moves_on_and_space_chooses(screen: Screen) -> None:
    screen.open()
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == "Mica"
    screen.press(Qt.Key.Key_Space)
    assert screen.checked() == ["Mica"]
    assert screen.kept == [Material.MICA]
    screen.press(Qt.Key.Key_Tab)
    # Back to the first material: Tab passes the X by, as Esc does the same.
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == "Acrilico"


@pytest.mark.parametrize("close", ["Chiudi", "Esc"])
def test_the_x_and_esc_close_the_window(screen: Screen, close: str) -> None:
    screen.open()
    # The X is the only Chiudi: no button at the bottom, as in Windows' Settings.
    assert len(screen._items(lambda item: accessible(item, "name") == "Chiudi")) == 1
    if close == "Esc":
        screen.press(Qt.Key.Key_Escape)
    else:
        screen.click(close)
    assert not screen.window.isVisible()


def test_the_window_drags_from_any_empty_point_but_not_from_its_controls(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.open()
    window = screen.window
    assert drags(window, QPoint(8, window.height() - 8))
    for control in (
        screen._item(lambda item: accessible(item, "name") == "Chiudi"),
        *screen.choices(),
    ):
        middle = QPointF(control.width() / 2, control.height() / 2)
        assert not drags(window, control.mapToScene(middle).toPoint())


def test_the_window_opens_again_where_it_was_left_and_stays_there_as_it_grows(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.open()
    # Where the user drags it: the offscreen platform has no system move.
    screen.window.setFramePosition(QPoint(30, 40))
    screen.preferences.close()
    screen.open()
    assert screen.window.framePosition() == QPoint(30, 40)
    assert screen.placed == [{"settings": (30, 40)}]
    screen.windows.settings = replace(DARK, transparency=False)
    # Qt says the window grew from its window-system queue, where it would move a centred one.
    with qtbot.waitSignal(screen.window.heightChanged):
        screen.look.refresh()
    assert screen.window.framePosition() == QPoint(30, 40)


def test_opening_again_puts_the_focus_back_on_the_material_in_use(screen: Screen) -> None:
    screen.open()
    screen.press(Qt.Key.Key_Tab)
    screen.press(Qt.Key.Key_Tab)
    screen.preferences.close()
    screen.open()
    assert screen.focused() == "Acrilico dei menu"


def test_without_transparency_the_window_says_why_every_surface_is_solid_and_stays_centred(
    screen: Screen, qtbot: QtBot
) -> None:
    note = "Gli effetti di trasparenza di Windows sono spenti: le finestre sono piene."
    screen.open()
    stays_centred(qtbot, screen.window)
    assert not screen.shows(note)
    height = screen.window.frameGeometry().height()
    screen.windows.settings = replace(DARK, transparency=False)
    screen.look.refresh()
    assert screen.shows(note)
    qtbot.waitUntil(lambda: screen.window.frameGeometry().height() > height)
    stays_centred(qtbot, screen.window)


def test_the_settings_go_with_the_engine_and_no_binding_reads_them_gone(
    qtbot: QtBot, dwm: list[tuple[object, ...]]
) -> None:
    """On quitting, Python lets go of the interface in any order: the settings stay until the
    engine goes, and then none of the window's bindings reads them gone (a warning fails)."""
    look = Look(Windows().read)
    engine = QQmlEngine()
    look.provide(engine)
    preferences = Preferences(
        engine, look, lambda material: None, Glass(look), Places(lambda places: None)
    )
    preferences.open()
    gone: list[str] = []
    preferences.destroyed.connect(lambda: gone.append("preferences"))
    del preferences
    gc.collect()
    assert gone == []
    del engine
    gc.collect()
    assert gone == ["preferences"]
