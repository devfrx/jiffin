import gc
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.clock import SimulatedClock
from jiffin.core.meanings import read
from jiffin.core.records import Revision
from jiffin.core.reminders import HOUR_MS
from jiffin.lang.texts import TEXTS
from jiffin.ui import win32
from jiffin.ui.creation import Creation
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings
from jiffin.ui.places import Places

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
WHEN, WHAT, EVERY_TIME = TEXTS.creation.condition, TEXTS.creation.action, TEXTS.creation.perennial
"""The two boxes and the check box, as a screen reader names them."""
HINT = "Descrivi dove sei o quando: un'app, un sito, un orario."
CLOCK = ""
SECONDARY, CAUTION = QColor("#C5FFFFFF"), QColor("#FFFCE100")
"""The clock's colours in dark: at rest, and for a time over or not understood."""
FRIDAY = datetime(2026, 10, 2, 10, tzinfo=UTC)
"""Venerdì 2 ottobre 2026 alle 10:00, on a clock in UTC."""


def instant(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def saved(
    reminder_id: int,
    condition: str,
    action: str,
    perennial: bool = False,
    written_at: datetime = FRIDAY,
) -> Revision:
    """A reminder's revision as `core` saved it: its time read when it was written."""
    reading = read(condition, written_at)
    return Revision(
        reminder_id,
        reminder_id,
        1,
        condition,
        action,
        reading.remainder,
        schedule=reading.schedule,
        written_at=instant(written_at),
        perennial=perennial,
    )


class Changes:
    """The changes saved on screen, in order: (what, [reminder id,] condition, action,
    perennial)."""

    def __init__(self) -> None:
        self.made: list[tuple[object, ...]] = []

    def create(self, condition: str, action: str, perennial: bool) -> None:
        self.made.append(("create", condition, action, perennial))

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None:
        self.made.append(("edit", reminder_id, condition, action, perennial))


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
    """The creation window on the offscreen screen, with the changes saved there and the places
    kept."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.changes = Changes()
        self.kept: list[dict[str, tuple[int, int]]] = []
        self.places = Places(lambda places: self.kept.append(dict(places)))
        self.clock = SimulatedClock(instant(FRIDAY))
        before = set(QGuiApplication.topLevelWindows())
        self.creation = Creation(
            self.engine, self.changes, Glass(self.look), self.places, self.clock
        )
        (window,) = (w for w in QGuiApplication.topLevelWindows() if w not in before)
        assert isinstance(window, QQuickWindow)
        self.window = window

    def new(self) -> None:
        """What the shortcut does; the window is ready once it has the focus."""
        self.creation.new()
        self._qtbot.waitUntil(self.window.isActive)

    def edit(self, revision: Revision) -> None:
        self.creation.edit(revision)
        self._qtbot.waitUntil(self.window.isActive)

    def retype(self, text: str) -> None:
        """Select the whole box with the focus and type over it."""
        QTest.keyClick(self.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.type(text)

    def ticked(self) -> object:
        """Whether "Ogni volta" shows its check."""
        return self.button(EVERY_TIME).property("checked")

    def clock_colour(self) -> QColor | None:
        """The colour of the clock beside the line under "Quando"; None when it does not show."""
        try:
            glyph = self._item(
                lambda item: item.inherits("QQuickText") and item.property("text") == CLOCK
            )
        except StopIteration:
            return None
        return QColor(glyph.property("color"))

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
                item.inherits("QQuickText") and ", ti ricordo " in str(item.property("text"))
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
    assert not screen.button(TEXTS.creation.save).isEnabled()


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
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == [("create", "quando apro Figma", "esportare le icone", False)]
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
    assert screen.changes.made == [("create", "se sono su Amazon", "controllare le cuffie", False)]
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
    assert not screen.button(TEXTS.creation.save).isEnabled()
    screen.creation.save()
    screen.press(Qt.Key.Key_Tab)
    screen.type("   ")
    assert not screen.button(TEXTS.creation.save).isEnabled()
    screen.type("x")
    assert screen.button(TEXTS.creation.save).isEnabled()
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


@pytest.mark.parametrize("close", [TEXTS.command.cancel, "Esc", TEXTS.command.close])
def test_annulla_esc_and_the_x_close_without_saving(screen: Screen, close: str) -> None:
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


def test_the_x_sits_on_the_titles_line_12_px_from_the_edge_and_tab_passes_it_by(
    screen: Screen,
) -> None:
    screen.new()
    x = screen.button(TEXTS.command.close)
    title = screen._item(
        lambda item: item.inherits("QQuickText") and item.property("text") == TEXTS.creation.new
    )
    corner = x.mapToScene(QPointF(0, 0))
    assert corner.x() + x.width() == screen.window.width() - 12
    assert corner.y() + x.height() / 2 == title.mapToScene(QPointF(0, title.height() / 2)).y()
    screen.type("quando apro Figma")
    screen.press(Qt.Key.Key_Tab)
    screen.type("esportare le icone")
    for name in (EVERY_TIME, TEXTS.command.cancel, TEXTS.creation.save, WHEN):
        screen.press(Qt.Key.Key_Tab)
        assert screen.focused() == name


def test_the_window_drags_from_any_empty_point_but_not_from_its_controls(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.new()
    window = screen.window
    title = screen._item(
        lambda item: item.inherits("QQuickText") and item.property("text") == TEXTS.creation.new
    )
    assert drags(window, QPoint(8, window.height() - 8))
    assert drags(window, title.mapToScene(QPointF(4, title.height() / 2)).toPoint())
    for control in (
        screen.button(TEXTS.command.close),
        screen.button(TEXTS.command.cancel),
        screen.box(WHEN),
    ):
        middle = QPointF(control.width() / 2, control.height() / 2)
        assert not drags(window, control.mapToScene(middle).toPoint())


def test_the_window_opens_again_where_it_was_left(screen: Screen) -> None:
    screen.new()
    # Where the user drags it: the offscreen platform has no system move.
    screen.window.setFramePosition(QPoint(30, 40))
    screen.creation.cancel()
    screen.new()
    assert screen.window.framePosition() == QPoint(30, 40)
    assert screen.kept == [{"creation": (30, 40)}]


def test_the_shortcut_brings_an_open_window_to_the_front_where_it_is(screen: Screen) -> None:
    screen.new()
    # Even partly off the screen: it opens at the centre only from hidden.
    area = QGuiApplication.primaryScreen().availableGeometry()
    partly_off = QPoint(area.right() - 100, area.y() + 40)
    screen.window.setFramePosition(partly_off)
    screen.new()
    assert screen.window.framePosition() == partly_off


def test_tab_reaches_the_buttons_and_enter_clicks_them(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Figma")
    screen.press(Qt.Key.Key_Tab)
    screen.type("esportare le icone")
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == EVERY_TIME
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == TEXTS.command.cancel
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == TEXTS.creation.save
    screen.press(Qt.Key.Key_Return)
    assert screen.changes.made == [("create", "quando apro Figma", "esportare le icone", False)]


def test_editing_shows_the_reminder_and_saves_its_new_text(screen: Screen) -> None:
    screen.edit(saved(7, "quando apro Figma", "esportare le icone"))
    assert screen.window.title() == "Modifica promemoria"
    assert screen.shows("Modifica promemoria")
    assert (screen.text(WHEN), screen.text(WHAT)) == ("quando apro Figma", "esportare le icone")
    assert screen.focused() == WHEN
    screen.press(Qt.Key.Key_Tab)
    QTest.keyClick(screen.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    screen.type("esportare i loghi")
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == [("edit", 7, "quando apro Figma", "esportare i loghi", False)]


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
    creation = Creation(
        engine, Changes(), Glass(look), Places(lambda places: None), SimulatedClock(0)
    )
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
    screen.edit(saved(7, "quando apro Figma", "esportare le icone"))
    screen.new()
    assert screen.window.title() == "Nuovo promemoria"
    assert (screen.text(WHEN), screen.text(WHAT)) == ("", "")
    screen.edit(saved(8, "se sono su Amazon", "controllare le cuffie"))
    screen.edit(saved(9, "quando apro GitHub", "rispondere alla review"))
    assert screen.text(WHEN) == "quando apro GitHub"


YESTERDAY = datetime(2026, 10, 1, 10, tzinfo=UTC)
PAST_WARNING = "è già passato. Per salvare, scrivi un giorno o un'ora che deve ancora venire."


def test_without_a_time_the_hint_stays_under_quando(screen: Screen) -> None:
    screen.new()
    assert screen.shows(HINT)
    screen.type("quando apro Teams")
    assert screen.shows(HINT)
    assert screen.clock_colour() is None


def test_the_time_understood_takes_the_hints_place_beside_a_clock(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Teams domani alle 15")
    assert screen.shows("Domani, sabato 3 ottobre, alle 15:00")
    assert not screen.shows(HINT)
    assert screen.clock_colour() == SECONDARY
    # The sentence keeps the user's words (#84).
    assert screen.sentence() == "Quando apro Teams domani alle 15, ti ricordo di …"


def test_the_words_not_understood_are_named_and_the_reminder_still_saves(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Steam verso sera e a dicembre")
    assert screen.shows("Non capisco «verso sera» e «dicembre»: suona a qualsiasi ora.")
    assert screen.clock_colour() == CAUTION
    screen.press(Qt.Key.Key_Tab)
    screen.type("giocare")
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == [
        ("create", "quando apro Steam verso sera e a dicembre", "giocare", False)
    ]


def test_a_time_already_over_turns_salva_off_and_says_why(screen: Screen) -> None:
    screen.new()
    screen.type("oggi alle 9")
    screen.press(Qt.Key.Key_Tab)
    screen.type("chiamare Mario")
    assert screen.shows("Oggi, venerdì 2 ottobre, alle 09:00")
    assert screen.shows(f"Oggi alle 09:00 {PAST_WARNING}")
    assert screen.clock_colour() == CAUTION
    assert not screen.button(TEXTS.creation.save).isEnabled()
    screen.press(Qt.Key.Key_Return)
    assert screen.focused() == WHEN
    screen.creation.save()
    assert screen.changes.made == []
    screen.retype("oggi alle 11")
    assert screen.button(TEXTS.creation.save).isEnabled()
    assert not screen.shows(f"Oggi alle 09:00 {PAST_WARNING}")
    assert screen.clock_colour() == SECONDARY


def test_a_time_that_passes_while_the_window_is_open_is_not_saved(screen: Screen) -> None:
    screen.new()
    screen.type("oggi alle 11")
    screen.press(Qt.Key.Key_Tab)
    screen.type("chiamare Mario")
    screen.clock.advance(2 * HOUR_MS)
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == []
    assert screen.window.isVisible()
    assert screen.shows(f"Oggi alle 11:00 {PAST_WARNING}")
    assert not screen.button(TEXTS.creation.save).isEnabled()


def test_ogni_volta_makes_the_reminder_perennial(screen: Screen) -> None:
    screen.new()
    assert screen.shows("Suona ogni volta che succede, e non si completa mai.")
    assert screen.ticked() is False
    screen.type("quando apro Teams")
    screen.press(Qt.Key.Key_Tab)
    screen.type("bere un caffe")
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == EVERY_TIME
    screen.press(Qt.Key.Key_Space)
    assert screen.ticked() is True
    assert screen.sentence() == "Quando apro Teams, ti ricordo ogni volta di bere un caffe."
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == [("create", "quando apro Teams", "bere un caffe", True)]


def test_a_new_reminder_starts_without_ogni_volta(screen: Screen) -> None:
    screen.new()
    screen.click(EVERY_TIME)
    screen.creation.cancel()
    screen.new()
    assert screen.ticked() is False
    # The box touched on the reminder before does not stop the words of this one.
    screen.type("quando apro Dropbox ogni mese")
    assert screen.ticked() is True


def test_the_words_of_the_reminder_before_never_untick_a_saved_box(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Dropbox ogni mese")
    screen.creation.cancel()
    screen.edit(saved(7, "quando apro Teams", "bere un caffe", True))
    screen.type(" ogni mese")
    screen.retype("quando apro Teams")
    assert screen.ticked() is True


def test_at_night_today_is_still_the_day_before(screen: Screen) -> None:
    """At 02:00 on Saturday the Jiffin day is Friday's, as for the meanings (#91)."""
    screen.clock.advance(16 * HOUR_MS)
    screen.new()
    screen.type("domani alle 15")
    assert screen.shows("Domani, sabato 3 ottobre, alle 15:00")


def test_every_day_goes_before_the_hours_of_a_perennial_reminder_only(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Claude dopo le 23")
    assert screen.shows("Dalle 23:00 alle 04:00")
    screen.click(EVERY_TIME)
    assert screen.shows("Ogni giorno dalle 23:00 alle 04:00")


def test_recurring_words_tick_ogni_volta_while_the_user_has_not_touched_it(
    screen: Screen,
) -> None:
    screen.new()
    screen.type("quando apro Dropbox ogni due settimane")
    assert screen.ticked() is True
    # The words go, and the check they put goes with them.
    screen.retype("quando apro Dropbox")
    assert screen.ticked() is False
    screen.type(" ogni mese")
    assert screen.ticked() is True
    # Taken off by the user, the same words never put it back (#92).
    screen.click(EVERY_TIME)
    assert screen.ticked() is False
    screen.box(WHEN).forceActiveFocus()
    screen.retype("quando apro Dropbox")
    screen.retype("quando apro Dropbox ogni due settimane")
    assert screen.ticked() is False


def test_a_check_put_by_the_user_stays_when_the_words_go(screen: Screen) -> None:
    screen.new()
    screen.type("quando apro Teams")
    screen.click(EVERY_TIME)
    screen.box(WHEN).forceActiveFocus()
    screen.retype("quando apro Teams ogni mese")
    screen.retype("quando apro Teams")
    assert screen.ticked() is True


def test_editing_opens_with_the_box_and_the_time_as_saved(screen: Screen) -> None:
    screen.edit(
        saved(7, "quando apro Teams domani alle 15", "chiamare Mario", True, written_at=YESTERDAY)
    )
    assert screen.ticked() is True
    # The saved time, written for today: not read again from now (ADR-0020).
    assert screen.shows("Oggi, venerdì 2 ottobre, alle 15:00")
    screen.press(Qt.Key.Key_Tab)
    screen.retype("chiamare Giulia")
    screen.click(TEXTS.creation.save)
    assert screen.changes.made == [
        ("edit", 7, "quando apro Teams domani alle 15", "chiamare Giulia", True)
    ]


def test_editing_reads_the_time_again_once_the_condition_changes(screen: Screen) -> None:
    screen.edit(
        saved(7, "quando apro Teams domani alle 15", "chiamare Mario", written_at=YESTERDAY)
    )
    screen.retype("quando apro Teams domani alle 16")
    assert screen.shows("Domani, sabato 3 ottobre, alle 16:00")
    # Back to the saved words, the saved time is back.
    screen.retype("quando apro Teams domani alle 15")
    assert screen.shows("Oggi, venerdì 2 ottobre, alle 15:00")


def test_a_saved_time_already_over_does_not_stop_an_edit(screen: Screen) -> None:
    screen.edit(saved(7, "oggi alle 9", "chiamare Mario", written_at=FRIDAY.replace(hour=8)))
    assert screen.shows("Oggi, venerdì 2 ottobre, alle 09:00")
    assert not screen.shows(f"Oggi alle 09:00 {PAST_WARNING}")
    assert screen.clock_colour() == SECONDARY
    assert screen.button(TEXTS.creation.save).isEnabled()


def test_editing_keeps_the_box_as_it_was_whatever_its_words(screen: Screen) -> None:
    screen.edit(saved(7, "il 15 di ogni mese", "pagare l'affitto"))
    assert screen.ticked() is False
    screen.type(" alle 9")
    assert screen.ticked() is False


def test_editing_names_the_words_not_understood_again(screen: Screen) -> None:
    screen.edit(saved(7, "quando apro Steam verso sera", "giocare"))
    assert screen.shows("Non capisco «verso sera»: suona a qualsiasi ora.")
