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

from jiffin.lang.texts import TEXTS
from jiffin.ui import win32
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Material, Settings
from jiffin.ui.networks import Networks
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
PAUSE = TEXTS.settings.return_pause
UNIT = TEXTS.settings.unit


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


def shown(window: QQuickWindow, wanted: Callable[[QQuickItem], bool]) -> list[QQuickItem]:
    """The visible items of a window that are `wanted`."""
    # Layouts place what they show only when polished, before the next frame.
    for item in items(window.contentItem()):
        item.ensurePolished()
    return [item for item in items(window.contentItem()) if item.isVisible() and wanted(item)]


def click(window: QQuickWindow, item: QQuickItem) -> None:
    centre = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)


class Screen:
    """The settings window on the offscreen screen, with the materials, the pauses and the
    places it kept."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.kept: list[Material] = []
        self.paused: list[int] = []
        self.placed: list[dict[str, tuple[int, int]]] = []
        self.places = Places(lambda places: self.placed.append(dict(places)))
        self.labels: list[dict[str, str]] = []
        self.networks = Networks(self.engine, lambda labels: self.labels.append(dict(labels)))
        self.preferences = Preferences(
            self.engine,
            self.look,
            self.kept.append,
            self.paused.append,
            self.networks,
            Glass(self.look),
            self.places,
        )
        (window,) = (
            w
            for w in QGuiApplication.topLevelWindows()
            if qmlEngine(w) is self.engine and w.title() == TEXTS.settings.title
        )
        assert isinstance(window, QQuickWindow)
        self.window = window
        units = window.property("units")
        assert isinstance(units, QQuickWindow)
        self.units = units
        """The unit's list, a window of its own."""

    def open(self) -> None:
        """What Settings in the tray icon's menu does; ready once it has the focus."""
        self.preferences.open()
        self._qtbot.waitUntil(self.window.isActive)

    def press(
        self, key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    ) -> None:
        QTest.keyClick(self.window, key, modifier)

    def type(self, text: str) -> None:
        """In place of what the focused box holds."""
        self.press(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for character in text:
            QTest.keyClick(self.window, ord(character))

    def click(self, name: str) -> None:
        click(self.window, self._item(lambda item: accessible(item, "name") == name))

    def pick(self, unit: str) -> None:
        """Click a unit in its open list."""
        (item,) = shown(self.units, lambda item: accessible(item, "name") == unit)
        click(self.units, item)

    def focused(self) -> object:
        item = self.window.activeFocusItem()
        return None if item is None else accessible(item, "name")

    def pause(self) -> tuple[str, str]:
        """What the pause shows: its number and its unit."""
        number = self._item(
            lambda item: item.inherits("QQuickTextField") and accessible(item, "name") == PAUSE
        )
        return str(number.property("text")), str(self.unit().property("text"))

    def unit(self) -> QQuickItem:
        return self._item(lambda item: accessible(item, "name") == UNIT)

    def choices(self) -> list[QQuickItem]:
        return self._items(lambda item: item.inherits("QQuickRadioButton"))

    def checked(self) -> list[object]:
        return [accessible(item, "name") for item in self.choices() if item.property("checked")]

    def shows(self, text: str) -> bool:
        return bool(self._text(text))

    def top(self, text: str) -> float:
        """Where the text shows, from the top of the window."""
        (item,) = self._text(text)
        return item.mapToScene(QPointF(0, 0)).y()

    def _text(self, text: str) -> list[QQuickItem]:
        return self._items(
            lambda item: item.inherits("QQuickText") and item.property("text") == text
        )

    def _item(self, wanted: Callable[[QQuickItem], bool]) -> QQuickItem:
        (item, *_) = self._items(wanted)
        return item

    def _items(self, wanted: Callable[[QQuickItem], bool]) -> list[QQuickItem]:
        return shown(self.window, wanted)


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]], focus_stays: None) -> Iterator[Screen]:
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


def test_impostazioni_opens_the_window_centred_with_the_focus_on_the_pause(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.open()
    window = screen.window
    stays_centred(qtbot, window)
    assert window.title() == "Impostazioni"
    assert screen.shows("Impostazioni")
    assert [accessible(choice, "name") for choice in screen.choices()] == NAMES
    assert screen.checked() == [TEXTS.material.menu_acrylic.name]
    assert screen.focused() == PAUSE


def test_the_return_pause_comes_before_the_material_with_what_it_does(screen: Screen) -> None:
    screen.open()
    hint = (
        "Se torni a una cosa dopo almeno questo tempo, i suoi promemoria suonano di nuovo. "
        "Da 10 secondi in su."
    )
    assert screen.top(PAUSE) < screen.top(hint) < screen.top(TEXTS.settings.material)
    assert screen.pause() == ("2", "minuti")


def test_each_material_says_what_it_looks_like(screen: Screen) -> None:
    screen.open()
    assert [accessible(choice, "description") for choice in screen.choices()] == [
        "Vetro chiaro: dietro si vede sfocato.",
        "Quasi pieno, come i menu di Windows. Predefinito.",
        "Come le Impostazioni di Windows: prende il colore dello sfondo.",
        "Più scuro, con più colore dello sfondo.",
    ]


def test_the_window_and_the_units_list_are_cards_on_the_alerts_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    for window in (screen.window, screen.units):
        flags = window.flags()
        assert flags & Qt.WindowType.FramelessWindowHint
    assert not screen.window.flags() & Qt.WindowType.WindowDoesNotAcceptFocus
    # The list never takes the focus: the window keeps it, and hears the keys.
    assert screen.units.flags() & Qt.WindowType.WindowDoesNotAcceptFocus
    hwnd, units = int(screen.window.winId()), int(screen.units.winId())
    assert dwm == [
        ("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW),
        ("set_backdrop", units, True, win32.DWMSBT_TRANSIENTWINDOW),
    ]


def test_a_click_on_a_material_changes_the_glass_at_once_and_keeps_the_choice(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    screen.open()
    del dwm[:]
    screen.click(TEXTS.material.mica.name)
    hwnd = int(screen.window.winId())
    assert screen.look.material is Material.MICA
    assert [call for call in dwm if call[1] == hwnd] == [
        ("set_backdrop", hwnd, True, win32.DWMSBT_MAINWINDOW),
        ("activate_frame", hwnd),
    ]
    assert screen.checked() == [TEXTS.material.mica.name]
    assert screen.kept == [Material.MICA]
    assert screen.window.isVisible()


def test_the_material_in_use_keeps_its_check_and_is_not_kept_again(screen: Screen) -> None:
    screen.open()
    screen.click(TEXTS.material.menu_acrylic.name)
    assert screen.checked() == [TEXTS.material.menu_acrylic.name]
    assert screen.kept == []


def test_the_check_follows_the_material_set_at_the_start(screen: Screen) -> None:
    screen.look.material = Material.MICA_ALT
    screen.open()
    assert screen.checked() == [TEXTS.material.mica_alt.name]
    assert screen.kept == []


def test_tab_moves_on_and_space_chooses(screen: Screen) -> None:
    screen.open()
    order = []
    for _ in range(6):
        screen.press(Qt.Key.Key_Tab)
        order.append(screen.focused())
    # Back to the pause: Tab passes the X by, as Esc does the same.
    assert order == [UNIT, *NAMES, PAUSE]
    for _ in range(4):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == TEXTS.material.mica.name
    screen.press(Qt.Key.Key_Space)
    assert screen.checked() == [TEXTS.material.mica.name]
    assert screen.kept == [Material.MICA]


@pytest.mark.parametrize("close", [TEXTS.command.close, "Esc"])
def test_the_x_and_esc_close_the_window(screen: Screen, close: str) -> None:
    screen.open()
    # The X is the only Close: no button at the bottom, as in Windows' Settings.
    assert len(screen._items(lambda item: accessible(item, "name") == TEXTS.command.close)) == 1
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
        screen._item(lambda item: accessible(item, "name") == TEXTS.command.close),
        screen._item(lambda item: item.inherits("QQuickTextField")),
        screen._item(lambda item: accessible(item, "name") == TEXTS.number_box.increase),
        screen.unit(),
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


def test_opening_again_puts_the_focus_back_on_the_pause(screen: Screen) -> None:
    screen.open()
    screen.press(Qt.Key.Key_Tab)
    screen.press(Qt.Key.Key_Tab)
    screen.preferences.close()
    screen.open()
    assert screen.focused() == PAUSE


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


# The return pause


@pytest.mark.parametrize(
    ("seconds", "pause"),
    [
        (120, ("2", "minuti")),
        (7200, ("120", "minuti")),
        (90, ("90", "secondi")),
        (10, ("10", "secondi")),
    ],
)
def test_the_pause_shows_in_minutes_when_it_is_whole_minutes(
    screen: Screen, seconds: int, pause: tuple[str, str]
) -> None:
    screen.preferences.return_pause = seconds
    screen.open()
    assert screen.pause() == pause


def test_a_number_typed_is_kept_when_the_box_is_left_and_comes_back_within_the_range(
    screen: Screen,
) -> None:
    screen.open()
    screen.type("45")
    assert screen.paused == []
    screen.press(Qt.Key.Key_Tab)
    assert (screen.pause(), screen.paused) == (("45", "minuti"), [2700])
    screen.press(Qt.Key.Key_Backtab)
    screen.type("500")
    screen.press(Qt.Key.Key_Return)
    assert (screen.pause(), screen.paused[-1]) == (("120", "minuti"), 7200)
    screen.type("0")
    screen.press(Qt.Key.Key_Return)
    assert (screen.pause(), screen.paused[-1]) == (("1", "minuti"), 60)
    screen.type("tanto")
    screen.press(Qt.Key.Key_Return)
    assert (screen.pause(), screen.paused) == (("1", "minuti"), [2700, 7200, 60])
    assert screen.preferences.return_pause == 60


def test_in_seconds_the_pause_never_goes_under_10(screen: Screen) -> None:
    screen.preferences.return_pause = 30
    screen.open()
    screen.type("5")
    screen.press(Qt.Key.Key_Return)
    assert (screen.pause(), screen.paused) == (("10", "secondi"), [10])


def test_the_arrows_step_the_pause_and_stop_at_the_ends_of_its_range(screen: Screen) -> None:
    screen.open()
    screen.click(TEXTS.number_box.increase)
    assert (screen.pause(), screen.paused) == (("3", "minuti"), [180])
    screen.press(Qt.Key.Key_Up)
    screen.press(Qt.Key.Key_Down)
    screen.click(TEXTS.number_box.decrease)
    assert screen.paused == [180, 240, 180, 120]
    screen.type("120")
    screen.press(Qt.Key.Key_Return)
    up = screen._item(lambda item: accessible(item, "name") == TEXTS.number_box.increase)
    assert not up.isEnabled()
    screen.press(Qt.Key.Key_Up)
    assert screen.paused[-1] == 7200
    screen.type("1")
    screen.press(Qt.Key.Key_Return)
    down = screen._item(lambda item: accessible(item, "name") == TEXTS.number_box.decrease)
    assert (up.isEnabled(), down.isEnabled()) == (True, False)


def test_any_number_for_the_pause_comes_back_within_the_range_of_its_unit(
    screen: Screen,
) -> None:
    """Whatever number reaches the settings, not only through the box."""
    screen.preferences.setPause(500)
    screen.preferences.setPause(0)
    assert screen.paused == [7200, 60]
    screen.preferences.setMinutes(False)
    screen.preferences.setPause(3)
    screen.preferences.setPause(9000)
    assert screen.paused == [7200, 60, 10, 7200]


def test_a_pause_that_does_not_change_is_not_kept_again(screen: Screen) -> None:
    screen.open()
    screen.preferences.setMinutes(False)
    screen.preferences.setMinutes(True)
    screen.preferences.setPause(2)
    assert (screen.pause(), screen.paused) == (("2", "minuti"), [])


def test_another_unit_converts_the_pause_to_the_nearest_minute(screen: Screen) -> None:
    screen.preferences.return_pause = 90
    screen.open()
    screen.click(UNIT)
    screen.pick(TEXTS.settings.minutes)
    assert not screen.units.isVisible()
    assert (screen.pause(), screen.paused) == (("2", "minuti"), [120])
    screen.click(UNIT)
    screen.pick(TEXTS.settings.seconds)
    # The same pause, in seconds: nothing new to keep.
    assert (screen.pause(), screen.paused) == (("120", "secondi"), [120])


def test_a_pause_under_a_minute_becomes_one_minute(screen: Screen) -> None:
    screen.preferences.return_pause = 20
    screen.open()
    screen.click(UNIT)
    screen.pick(TEXTS.settings.minutes)
    assert (screen.pause(), screen.paused) == (("1", "minuti"), [60])


def test_the_unit_picked_stays_while_the_window_is_open(screen: Screen) -> None:
    screen.preferences.return_pause = 90
    screen.open()
    screen.type("120")
    screen.press(Qt.Key.Key_Return)
    assert screen.pause() == ("120", "secondi")
    screen.preferences.close()
    screen.open()
    assert screen.pause() == ("2", "minuti")


def test_the_units_list_opens_on_the_glass_with_the_chosen_unit_over_the_box(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    screen.open()
    screen.click(UNIT)
    units = screen.units
    assert units.isVisible()
    hwnd = int(units.winId())
    assert ("activate_frame", hwnd) in dwm
    assert ("nudge", hwnd) in dwm
    names = shown(units, lambda item: item.inherits("QQuickAbstractButton"))
    assert [accessible(item, "name") for item in names] == ["secondi", "minuti"]
    # As wide as the box, with minutes, the second item, over it.
    box = screen.unit()
    corner = box.mapToGlobal(QPointF(0, 0))
    assert (units.x(), units.width()) == (round(corner.x()), round(box.width()))
    minuti = names[1].mapToGlobal(QPointF(0, 0))
    assert minuti.y() == corner.y()
    assert units.y() == round(corner.y()) - 6 - 36


def test_a_press_anywhere_else_closes_the_units_list_and_does_nothing_more(
    screen: Screen,
) -> None:
    screen.open()
    screen.click(UNIT)
    screen.click(TEXTS.material.mica.name)
    assert not screen.units.isVisible()
    assert (screen.checked(), screen.kept) == ([TEXTS.material.menu_acrylic.name], [])
    screen.click(UNIT)
    screen.click(UNIT)
    assert not screen.units.isVisible()


def test_a_drag_while_the_units_list_is_open_only_closes_it(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.open()
    screen.click(UNIT)
    window = screen.window
    assert not drags(window, QPoint(8, window.height() - 8))
    assert not screen.units.isVisible()


def test_another_window_taking_the_focus_closes_the_units_list(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.open()
    screen.click(UNIT)
    other = QWindow()
    other.resize(100, 100)
    other.show()
    other.requestActivate()
    qtbot.waitUntil(lambda: not screen.units.isVisible())
    assert screen.window.isVisible()
    other.destroy()


def test_esc_closes_the_units_list_before_the_window(screen: Screen) -> None:
    screen.open()
    screen.click(UNIT)
    screen.press(Qt.Key.Key_Escape)
    assert (screen.units.isVisible(), screen.window.isVisible()) == (False, True)
    screen.press(Qt.Key.Key_Escape)
    assert not screen.window.isVisible()


def test_the_unit_by_keyboard(screen: Screen) -> None:
    screen.open()
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == UNIT
    # Closed, Up and Down pick the unit before or after, as in WinUI.
    screen.press(Qt.Key.Key_Up)
    assert (screen.pause(), screen.paused) == (("120", "secondi"), [])
    screen.press(Qt.Key.Key_Space)
    assert screen.units.isVisible()
    assert screen.unit().property("current") == 0
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Down)
    assert screen.unit().property("current") == 1
    screen.press(Qt.Key.Key_Return)
    assert not screen.units.isVisible()
    assert screen.pause() == ("2", "minuti")
    screen.press(Qt.Key.Key_Down, Qt.KeyboardModifier.AltModifier)
    assert screen.units.isVisible()
    screen.press(Qt.Key.Key_Tab)
    assert not screen.units.isVisible()
    assert screen.focused() == TEXTS.material.acrylic.name


def test_the_window_closes_with_its_units_list(screen: Screen) -> None:
    screen.open()
    screen.click(UNIT)
    screen.preferences.close()
    assert not screen.units.isVisible()


def test_the_settings_go_with_the_engine_and_no_binding_reads_them_gone(
    qtbot: QtBot, dwm: list[tuple[object, ...]]
) -> None:
    """On quitting, Python lets go of the interface in any order: the settings stay until the
    engine goes, and then none of the window's bindings reads them gone (a warning fails)."""
    look = Look(Windows().read)
    engine = QQmlEngine()
    look.provide(engine)
    preferences = Preferences(
        engine,
        look,
        lambda material: None,
        lambda seconds: None,
        Networks(engine, lambda labels: None),
        Glass(look),
        Places(lambda places: None),
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


# The network in use (ADR-0028, #153)

NETWORK_ID = "6f1d2c3b-0000-4000-8000-000000000001"
LABELS = [TEXTS.networks.home, TEXTS.networks.office, TEXTS.networks.neither]


def test_the_network_comes_between_the_pause_and_the_material(screen: Screen) -> None:
    screen.open()
    assert (
        screen.top(PAUSE) < screen.top(TEXTS.networks.title) < screen.top(TEXTS.settings.material)
    )
    assert screen.shows(TEXTS.networks.hint)


def test_without_a_network_the_settings_say_so_and_label_nothing(screen: Screen) -> None:
    screen.open()
    assert screen.shows("Ora non sei connesso a nessuna rete.")
    assert not any(accessible(choice, "name") in LABELS for choice in screen.choices())


def test_the_network_in_use_is_home_the_office_or_neither_and_the_check_follows_its_label(
    screen: Screen,
) -> None:
    screen.networks.show(frozenset({NETWORK_ID}))
    screen.open()
    assert not screen.shows(TEXTS.networks.offline)
    assert [accessible(choice, "name") for choice in screen.choices()][:3] == LABELS
    assert screen.checked()[0] == TEXTS.networks.neither
    screen.click(TEXTS.networks.home)
    assert screen.labels == [{NETWORK_ID: "home"}]
    assert screen.checked()[0] == TEXTS.networks.home
    screen.click(TEXTS.networks.neither)
    assert screen.labels[-1] == {}
    assert screen.checked()[0] == TEXTS.networks.neither
