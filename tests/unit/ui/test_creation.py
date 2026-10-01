import gc
from collections.abc import Callable, Iterator
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.ui import win32
from jiffin.ui.creation import Creation
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
WHEN, WHAT = "Quando", "Ricordami di"
"""The two boxes, as a screen reader names them."""


class Changes:
    """The changes saved on screen, in order: (what, [reminder id,] condition, action)."""

    def __init__(self) -> None:
        self.made: list[tuple[object, ...]] = []

    def create(self, condition: str, action: str) -> None:
        self.made.append(("create", condition, action))

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        self.made.append(("edit", reminder_id, condition, action))


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


def accessible_name(item: QQuickItem) -> object:
    """None for the items a control makes on its own, which QML never sees."""
    context = qmlContext(item)
    return None if context is None else QQmlProperty(item, "Accessible.name", context).read()


class Screen:
    """The creation window on the offscreen screen, with the changes saved there."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.changes = Changes()
        before = set(QGuiApplication.topLevelWindows())
        self.creation = Creation(self.engine, self.changes, Glass(self.look))
        (window,) = (w for w in QGuiApplication.topLevelWindows() if w not in before)
        assert isinstance(window, QQuickWindow)
        self.window = window

    def new(self) -> None:
        """What the shortcut does; the window is ready once it has the focus."""
        self.creation.new()
        self._qtbot.waitUntil(self.window.isActive)

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        self.creation.edit(reminder_id, condition, action)
        self._qtbot.waitUntil(self.window.isActive)

    def type(self, text: str) -> None:
        """ASCII only: QTest types into a window one character code at a time."""
        for character in text:
            QTest.keyClick(self.window, ord(character))

    def press(self, key: Qt.Key) -> None:
        QTest.keyClick(self.window, key)

    def click(self, name: str) -> None:
        button = self._item(lambda item: accessible_name(item) == name)
        centre = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(
            self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre
        )

    def box(self, name: str) -> QQuickItem:
        return self._item(
            lambda item: item.inherits("QQuickTextEdit") and name == accessible_name(item)
        )

    def text(self, name: str) -> object:
        return self.box(name).property("text")

    def focused(self) -> object:
        """The box or button with the keyboard focus, by its name."""
        item = self.window.activeFocusItem()
        return None if item is None else accessible_name(item)

    def button(self, name: str) -> QQuickItem:
        return self._item(
            lambda item: item.inherits("QQuickAbstractButton") and accessible_name(item) == name
        )

    def sentence(self) -> object:
        """The sentence under the boxes."""
        return self._item(
            lambda item: (
                item.inherits("QQuickText") and ", ti ricordo di " in str(item.property("text"))
            )
        ).property("text")

    def shows(self, text: str) -> bool:
        """A line of the card reads `text`."""
        try:
            self._item(lambda item: item.inherits("QQuickText") and item.property("text") == text)
        except StopIteration:
            return False
        return True

    def examples(self) -> set[str]:
        """The examples the boxes show in grey."""
        for item in items(self.window.contentItem()):
            item.ensurePolished()
        return {
            str(item.property("text"))
            for item in items(self.window.contentItem())
            if item.isVisible()
            and item.inherits("QQuickText")
            and (box := item.parentItem()) is not None
            and box.inherits("QQuickTextEdit")
        }

    def _item(self, wanted: Callable[[QQuickItem], bool]) -> QQuickItem:
        # Layouts place what they show only when polished, before the next frame.
        for item in items(self.window.contentItem()):
            item.ensurePolished()
        return next(
            item for item in items(self.window.contentItem()) if item.isVisible() and wanted(item)
        )


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]]) -> Iterator[Screen]:
    screen = Screen(qtbot)
    yield screen
    screen.creation.cancel()


def centred(window: QWindow) -> tuple[int, int]:
    area = QGuiApplication.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    return (
        area.x() + (area.width() - frame.width()) // 2,
        area.y() + (area.height() - frame.height()) // 2,
    )


def test_the_shortcut_opens_a_blank_reminder_centred_with_the_focus(screen: Screen) -> None:
    screen.new()
    window = screen.window
    assert window.isVisible()
    assert (window.frameGeometry().x(), window.frameGeometry().y()) == centred(window)
    assert window.title() == "Nuovo promemoria"
    assert screen.shows("Nuovo promemoria")
    assert (screen.text(WHEN), screen.text(WHAT)) == ("", "")
    assert screen.focused() == WHEN
    assert not screen.button("Salva").isEnabled()


def test_the_window_is_a_card_on_the_alerts_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    flags = screen.window.flags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    hwnd = int(screen.window.winId())
    assert dwm == [("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW)]
    screen.new()
    screen.creation.cancel()
    screen.new()
    assert dwm[1:] == [("activate_frame", hwnd), ("nudge", hwnd), ("activate_frame", hwnd)]


def test_without_transparency_the_card_is_painted_solid(screen: Screen) -> None:
    screen.windows.settings = replace(DARK, dark=False, transparency=False)
    screen.look.refresh()
    screen.new()
    surface = screen._item(
        lambda item: item.inherits("QQuickRectangle") and item.width() == screen.window.width()
    )
    assert QColor(surface.property("color")) == QColor("#FFF9F9F9")


def test_salva_sends_the_two_boxes_with_their_spaces_tidied(screen: Screen) -> None:
    screen.new()
    screen.type("  quando   apro Figma ")
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == WHAT
    screen.type("esportare  le icone")
    screen.click("Salva")
    assert screen.changes.made == [("create", "quando apro Figma", "esportare le icone")]
    assert not screen.window.isVisible()


def test_enter_goes_to_the_empty_box_then_saves(screen: Screen) -> None:
    screen.new()
    screen.press(Qt.Key.Key_Return)
    assert screen.focused() == WHEN
    screen.type("se sono su Amazon")
    screen.press(Qt.Key.Key_Return)
    assert screen.focused() == WHAT
    assert screen.changes.made == []
    screen.type("controllare le cuffie")
    screen.press(Qt.Key.Key_Enter)
    assert screen.changes.made == [("create", "se sono su Amazon", "controllare le cuffie")]
    assert not screen.window.isVisible()


def test_a_box_never_breaks_a_line(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Figma")
    screen.press(Qt.Key.Key_Return)
    screen.press(Qt.Key.Key_Tab)
    assert "\n" not in str(screen.text(WHEN))


def test_salva_waits_for_both_boxes(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Figma")
    assert not screen.button("Salva").isEnabled()
    screen.creation.save()
    screen.press(Qt.Key.Key_Tab)
    screen.type("   ")
    assert not screen.button("Salva").isEnabled()
    screen.type("x")
    assert screen.button("Salva").isEnabled()
    assert screen.changes.made == []


def test_the_sentence_under_the_boxes_follows_them(screen: Screen) -> None:
    screen.new()
    assert screen.sentence() == "Quando …, ti ricordo di …"
    screen.type("quando apro  Figma")
    assert screen.sentence() == "Quando apro Figma, ti ricordo di …"
    screen.press(Qt.Key.Key_Tab)
    screen.type("esportare le icone!")
    assert screen.sentence() == "Quando apro Figma, ti ricordo di esportare le icone."


def test_an_empty_box_shows_an_example(screen: Screen) -> None:
    screen.new()
    assert screen.examples() == {"quando lavoro al progetto Rossi", "aggiornare il changelog"}
    screen.type("quando apro Figma")
    assert screen.examples() == {"aggiornare il changelog"}


@pytest.mark.parametrize("close", ["Annulla", "Esc"])
def test_annulla_and_esc_close_without_saving(screen: Screen, close: str) -> None:
    screen.new()
    screen.type("quando apro Figma")
    screen.press(Qt.Key.Key_Tab)
    screen.type("esportare le icone")
    if close == "Esc":
        screen.press(Qt.Key.Key_Escape)
    else:
        screen.click(close)
    assert not screen.window.isVisible()
    assert screen.changes.made == []


def test_tab_reaches_the_buttons_and_enter_clicks_them(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Figma")
    screen.press(Qt.Key.Key_Tab)
    screen.type("esportare le icone")
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == "Annulla"
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == "Salva"
    screen.press(Qt.Key.Key_Return)
    assert screen.changes.made == [("create", "quando apro Figma", "esportare le icone")]


def test_editing_shows_the_reminder_and_saves_its_new_text(screen: Screen) -> None:
    screen.edit(7, "quando apro Figma", "esportare le icone")
    assert screen.window.title() == "Modifica promemoria"
    assert screen.shows("Modifica promemoria")
    assert (screen.text(WHEN), screen.text(WHAT)) == ("quando apro Figma", "esportare le icone")
    assert screen.focused() == WHEN
    screen.press(Qt.Key.Key_Tab)
    QTest.keyClick(screen.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    screen.type("esportare i loghi")
    screen.click("Salva")
    assert screen.changes.made == [("edit", 7, "quando apro Figma", "esportare i loghi")]


def test_the_shortcut_again_keeps_the_reminder_being_written(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro")
    screen.new()
    assert screen.text(WHEN) == "quando apro"
    screen.creation.cancel()
    screen.new()
    assert screen.text(WHEN) == ""


def test_the_creation_goes_with_the_engine_and_no_binding_reads_it_gone(
    qtbot: QtBot, dwm: list[tuple[object, ...]]
) -> None:
    """On quitting, Python lets go of the interface in any order: the creation stays until the
    engine goes, and then none of its window's bindings reads it gone (a warning fails)."""
    look = Look(Windows().read)
    engine = QQmlEngine()
    look.provide(engine)
    creation = Creation(engine, Changes(), Glass(look))
    creation.new()
    gone: list[str] = []
    creation.destroyed.connect(lambda: gone.append("creation"))
    del creation
    gc.collect()
    assert gone == []
    del engine
    gc.collect()
    assert gone == ["creation"]


def test_the_shortcut_while_editing_starts_a_new_reminder(screen: Screen) -> None:
    screen.edit(7, "quando apro Figma", "esportare le icone")
    screen.new()
    assert screen.window.title() == "Nuovo promemoria"
    assert (screen.text(WHEN), screen.text(WHAT)) == ("", "")
    screen.edit(8, "se sono su Amazon", "controllare le cuffie")
    screen.edit(9, "quando apro GitHub", "rispondere alla review")
    assert screen.text(WHEN) == "quando apro GitHub"
