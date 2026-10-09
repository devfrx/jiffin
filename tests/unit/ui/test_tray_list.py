import gc
import math
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWheelEvent, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext, qmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.records import Alert, Here, Reminder, Revision, Snooze
from jiffin.core.reminders import (
    HOUR_MS,
    MINUTE_MS,
    ActiveReminder,
    HereView,
    Place,
    RemindersView,
)
from jiffin.lang.texts import TEXTS
from jiffin.ui import tray_list, win32
from jiffin.ui.first_run import FirstRun, ModelFile, ModelState
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings
from jiffin.ui.places import Places
from jiffin.ui.preferences import Preferences
from jiffin.ui.remind_here import RemindHere
from jiffin.ui.rows import Rows
from jiffin.ui.tray_list import MARGIN, REOPEN_MS, TrayList

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
ROME = timezone(timedelta(hours=2))
START = int(datetime(2026, 10, 1, 10, 0, tzinfo=ROME).timestamp() * 1000)
"""Thursday 1 October 2026, 10:00 in Rome."""
FIGMA = Context("figma.exe", "Icone - Figma", None)
SIZE = 2_600_224_416
MODEL = ModelFile("model.gguf", "https://example.org/model.gguf", SIZE, "0" * 64, Path("models"))
PAUSE = "Gli avvisi tornano se riprendi una cosa dopo almeno 2 min."
"""The last line of the list, with the default return pause."""
MENU = (
    TEXTS.snooze.next_time,
    TEXTS.snooze.quarter_hour,
    TEXTS.snooze.hour,
    TEXTS.snooze.tomorrow,
    TEXTS.alert.not_here,
)
"""The alert's menu, from the top (#83), which the unseen alerts' Snooze opens (#84)."""
F24 = "Controllare la scadenza dell'F24"
HOLD_MS = 300
"""How long an unseen alert's answer waits with Undo in these tests, instead of 5 s."""


class Commands:
    """What the list asked of `core`, in order: (what, id[, snooze])."""

    def __init__(self) -> None:
        self.sent: list[tuple[object, ...]] = []

    def done(self, alert_id: int) -> None:
        self.sent.append(("done", alert_id))

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self.sent.append(("snooze", alert_id, snooze))

    def not_here(self, alert_id: int) -> None:
        self.sent.append(("not_here", alert_id))

    def complete(self, reminder_id: int) -> None:
        self.sent.append(("complete", reminder_id))

    def reopen(self, reminder_id: int) -> None:
        self.sent.append(("reopen", reminder_id))

    def delete(self, reminder_id: int) -> None:
        self.sent.append(("delete", reminder_id))

    def seen(self) -> None:
        self.sent.append(("seen",))

    def withdraw(self, reminder_id: int, context: Context) -> None:
        self.sent.append(("withdraw", reminder_id, context))

    def withdraw_all(self, reminder_id: int) -> None:
        self.sent.append(("withdraw_all", reminder_id))


class Asked:
    """What the card of Remind here asked of `core`: how many times what it shows, and each
    Remind here."""

    def __init__(self) -> None:
        self.times = 0
        self.reminded: list[tuple[int, Context]] = []

    def here(self) -> None:
        self.times += 1

    def remind_here(self, reminder_id: int, context: Context) -> None:
        self.reminded.append((reminder_id, context))


class Stacked:
    """The overlay, for the card: nothing to stack it over in these tests."""

    def above(self, window: QQuickWindow) -> None:
        pass

    def layout(self) -> None:
        pass


class Writer:
    """What the list opened the creation window for: (what[, the revision to edit])."""

    def __init__(self) -> None:
        self.opened: list[tuple[object, ...]] = []

    def new(self) -> None:
        self.opened.append(("new",))

    def edit(self, revision: Revision) -> None:
        self.opened.append(("edit", revision))


def revision(
    revision_id: int, condition: str, action: str, perennial: bool, written_at: int
) -> Revision:
    """As `core` makes one: its time read when written."""
    reading = read(condition, datetime.fromtimestamp(written_at / 1000, ROME))
    return Revision(
        revision_id,
        revision_id,
        1,
        condition,
        action,
        reading.remainder,
        schedule=reading.schedule,
        written_at=written_at,
        perennial=perennial,
    )


def active(
    reminder_id: int,
    condition: str,
    action: str,
    silences: int = 0,
    snoozed_until: int | None = None,
    *,
    perennial: bool = False,
    written_at: int = START,
) -> ActiveReminder:
    written = revision(reminder_id, condition, action, perennial, written_at)
    places = tuple(
        Place(Context("olk.exe", f"Posta {n} - Outlook", None), Here.NO) for n in range(silences)
    )
    return ActiveReminder(Reminder(reminder_id, written_at, written, None, snoozed_until), places)


def completed(reminder_id: int, condition: str, action: str, completed_at: int) -> Reminder:
    """A reminder among the completed (ADR-0030)."""
    return replace(active(reminder_id, condition, action).reminder, completed_at=completed_at)


def unseen(
    alert_id: int,
    action: str,
    shown_at: int,
    seen_at: int | None = None,
    condition: str = "quando apro il gestionale delle fatture",
) -> Alert:
    return Alert(
        alert_id,
        alert_id,
        revision(alert_id, condition, action, False, START - HOUR_MS),
        alert_id,
        FIGMA,
        2.0,
        shown_at,
        shown_at,
        shown_at=shown_at,
        vanished_at=shown_at + 10_000,
        seen_at=seen_at,
    )


def at(day: int, hour: int, minute: int, month: int = 10) -> int:
    return int(datetime(2026, month, day, hour, minute, tzinfo=ROME).timestamp() * 1000)


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def accessible(item: QQuickItem, name: str) -> object:
    """None for the items a control makes on its own, which QML never sees."""
    context = qmlContext(item)
    return None if context is None else QQmlProperty(item, f"Accessible.{name}", context).read()


def in_button(item: QQuickItem) -> bool:
    parent = item.parentItem()
    while parent is not None:
        if parent.inherits("QQuickAbstractButton"):
            return True
        parent = parent.parentItem()
    return False


def column(rows: Rows, role: str) -> list[object]:
    """One role of every row, top to bottom."""
    number = next(n for n, name in rows.roleNames().items() if bytes(name.data()) == role.encode())
    return [rows.data(rows.index(i), number) for i in range(rows.rowCount())]


def shown(window: QQuickWindow) -> list[QQuickItem]:
    # Layouts place what they show only when polished, before the next frame.
    for item in items(window.contentItem()):
        item.ensurePolished()
    return [item for item in items(window.contentItem()) if item.isVisible()]


def rounded(value: float) -> int:
    """As QML's Math.round."""
    return math.floor(value + 0.5)


def ringed(item: QQuickItem) -> bool:
    """Whether the item shows WinUI's focus ring: its 2 px outer stroke."""
    return any(
        child.inherits("QQuickRectangle")
        and child.isVisible()
        and (context := qmlContext(child)) is not None
        and QQmlProperty(child, "border.width", context).read() == 2
        for child in items(item)
    )


class Screen:
    """The tray list on the offscreen screen, with what it asked of `core` and the creation
    window."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.look = Look(lambda: DARK)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.clock = SimulatedClock(START, ROME)
        self.commands = Commands()
        self.writer = Writer()
        self.retries = 0
        self.resumes = 0
        self.fetches = 0
        self.first_run = FirstRun(
            self.engine,
            MODEL,
            self._fetch,
            Glass(self.look),
            Places(lambda places: None),
            self.clock,
        )
        self.preferences = Preferences(
            self.engine,
            self.look,
            lambda material: None,
            lambda seconds: None,
            Glass(self.look),
            Places(lambda places: None),
        )
        self.asked = Asked()
        self.remind_here = RemindHere(
            self.engine, self.asked, Stacked(), Glass(self.look), self.clock
        )
        self.list = TrayList(
            self.engine,
            self.commands,
            self.writer,
            self.remind_here,
            self._retry,
            self._resume,
            self.first_run,
            self.preferences,
            Glass(self.look),
            self.clock,
        )
        # The lists of earlier tests may still be there, until their engines go; the first-run
        # window and the settings are this engine's too.
        (window,) = (
            w
            for w in QGuiApplication.topLevelWindows()
            if qmlEngine(w) is self.engine and w.title() == TEXTS.tray_list.title
        )
        assert isinstance(window, QQuickWindow)
        self.window = window
        window.setProperty("holdDuration", HOLD_MS)
        menu = window.property("menu")
        assert isinstance(menu, QQuickWindow)
        self.menu = menu
        """Snooze's menu, a window of its own."""

    def model(self, stage: FirstRun.Stage, done: int = 0) -> None:
        """What the app says of the model file, with the first-run window closed by the user."""
        self.first_run.show(ModelState(stage, done, SIZE))
        self.first_run.close()

    def open(self) -> None:
        """What a click on the tray icon does; the list is ready once it has the focus."""
        self.list.toggle()
        self._qtbot.waitUntil(self.window.isActive)

    def lines(self) -> list[str]:
        """What the list reads, top to bottom, without its buttons and icons."""
        found = []
        for item in shown(self.window):
            text = str(item.property("text")) if item.inherits("QQuickText") else ""
            if text and not in_button(item) and not "" <= text[0] <= "":
                corner = item.mapToScene(QPointF(0, 0))
                found.append((corner.y(), corner.x(), text))
        return [text for _, _, text in sorted(found)]

    def button(self, name: str, row: str | None = None) -> QQuickItem:
        """The button a screen reader calls `name`, in the card or row that reads `row`."""
        return next(
            item
            for item in shown(self.window)
            if item.inherits("QQuickAbstractButton")
            and accessible(item, "name") == name
            and (row is None or self._reads(item, row))
        )

    def buttons(self, row: str) -> list[object]:
        """What a screen reader calls the visible buttons of the card or row that reads `row`,
        from the left."""
        found = [
            item
            for item in shown(self.window)
            if item.inherits("QQuickAbstractButton") and self._reads(item, row)
        ]
        found.sort(key=lambda item: item.mapToScene(QPointF(0, 0)).x())
        return [accessible(item, "name") for item in found]

    def named(self, name: str) -> list[QQuickItem]:
        """The visible items a screen reader calls `name`."""
        return [item for item in shown(self.window) if accessible(item, "name") == name]

    def click(self, name: str, row: str | None = None) -> None:
        self.click_item(self.button(name, row))

    def click_item(self, button: QQuickItem) -> None:
        """Click the button once the window's scene holds it. The scene takes the window's new
        height through the event queue, and QTest's click skips the queue: after a row grows,
        it would land below the scene, on nothing."""

        def centre() -> QPointF:
            return button.mapToScene(QPointF(button.width() / 2, button.height() / 2))

        scene = self.window.contentItem()
        self._qtbot.waitUntil(lambda: scene.boundingRect().contains(centre()))
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            centre().toPoint(),
        )

    def menu_items(self) -> list[QQuickItem]:
        """The items of Snooze's menu, from the top."""
        found = [item for item in shown(self.menu) if item.inherits("QQuickAbstractButton")]
        return sorted(found, key=lambda item: item.mapToScene(QPointF(0, 0)).y())

    def choose(self, name: str) -> None:
        """Click an item of the open menu."""
        (item,) = (item for item in self.menu_items() if accessible(item, "name") == name)
        centre = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(
            self.menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre
        )

    def press(self, key: Qt.Key) -> None:
        """A key, once the list has the focus back from a menu it showed (`focus_stays`)."""
        self._qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is self.window)
        QTest.keyClick(self.window, key)

    def focused(self) -> tuple[object, object]:
        """The button with the keyboard focus: its name, and the row it acts on."""
        item = self.window.activeFocusItem()
        assert item is not None
        return accessible(item, "name"), accessible(item, "description")

    def window_titled(self, title: str) -> QQuickWindow:
        (window,) = (
            w
            for w in QGuiApplication.topLevelWindows()
            if qmlEngine(w) is self.engine and w.title() == title
        )
        assert isinstance(window, QQuickWindow)
        return window

    def _reads(self, button: QQuickItem, text: str) -> bool:
        """The card or row of the button reads `text`."""
        row = button.parentItem()
        while row is not None and row.property("alertId") is None:
            if row.property("reminderId") is not None:
                break
            row = row.parentItem()
        return row is not None and any(
            child.inherits("QQuickText") and child.property("text") == text for child in items(row)
        )

    def _retry(self) -> None:
        self.retries += 1

    def _resume(self) -> None:
        self.resumes += 1

    def _fetch(self) -> None:
        self.fetches += 1


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]], focus_stays: None) -> Iterator[Screen]:
    screen = Screen(qtbot)
    yield screen
    screen.list.close()
    screen.preferences.close()


@pytest.fixture
def elsewhere(qtbot: QtBot) -> Iterator[Callable[[], None]]:
    """Another window takes the focus, as the taskbar does when the tray icon is clicked."""
    other = QWindow()
    other.resize(100, 100)

    def focus() -> None:
        other.show()
        other.requestActivate()
        qtbot.waitUntil(other.isActive)

    yield focus
    other.destroy()


def test_the_tray_icon_opens_the_list_at_the_bottom_right_with_the_focus(screen: Screen) -> None:
    screen.open()
    area = QGuiApplication.primaryScreen().availableGeometry()
    frame = screen.window.frameGeometry()
    assert (frame.right(), frame.bottom()) == (area.right() - MARGIN, area.bottom() - MARGIN)
    assert screen.window.title() == "Promemoria"
    assert screen.lines() == ["Promemoria", "Attivi", "Nessun promemoria attivo.", PAUSE]


def test_the_list_is_a_card_on_the_alerts_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    flags = screen.window.flags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    hwnd = int(screen.window.winId())
    calls = [call for call in dwm if call[1] == hwnd]
    assert calls == [("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW)]
    screen.open()
    calls = [call for call in dwm if call[1] == hwnd]
    assert calls[1:] == [("activate_frame", hwnd), ("nudge", hwnd)]


def test_esc_the_x_and_the_tray_icon_close_the_list(screen: Screen) -> None:
    screen.open()
    screen.press(Qt.Key.Key_Escape)
    assert not screen.window.isVisible()
    screen.open()
    screen.click(TEXTS.command.close)
    assert not screen.window.isVisible()
    screen.open()
    screen.list.toggle()
    assert not screen.window.isVisible()


def test_the_x_sits_after_nuovo_12_px_from_the_edge(screen: Screen) -> None:
    screen.open()
    new, x = screen.button(TEXTS.tray_list.new), screen.button(TEXTS.command.close)
    corner = x.mapToScene(QPointF(0, 0))
    assert corner.x() + x.width() == screen.window.width() - 12
    assert corner.x() - new.mapToScene(QPointF(new.width(), 0)).x() == 4
    assert corner.y() == new.mapToScene(QPointF(0, 0)).y()


def test_the_list_drags_from_any_empty_point_but_not_from_its_controls(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.list.show_reminders(
        RemindersView((active(1, "quando apro Figma", "esportare le icone"),))
    )
    screen.open()
    window = screen.window
    assert drags(window, QPoint(4, window.height() - 4))
    for name in (
        TEXTS.tray_list.new,
        TEXTS.command.close,
        TEXTS.tray_list.complete,
        TEXTS.tray_list.edit,
        TEXTS.tray_list.change,
    ):
        button = screen.button(name)
        middle = QPointF(button.width() / 2, button.height() / 2)
        assert not drags(window, button.mapToScene(middle).toPoint())


def test_a_moved_list_stays_where_it_was_left_as_it_grows_and_opens_over_the_tray_again(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.open()
    # Where the user drags it: the offscreen platform has no system move.
    screen.window.setFramePosition(QPoint(30, 40))
    # Qt says the window grew from its window-system queue, where the list keeps its bottom.
    with qtbot.waitSignal(screen.window.heightChanged):
        screen.list.show_reminders(
            RemindersView((active(1, "quando apro Figma", "esportare le icone"),))
        )
    assert screen.window.framePosition() == QPoint(30, 40)
    screen.press(Qt.Key.Key_Escape)
    screen.open()
    area = QGuiApplication.primaryScreen().availableGeometry()
    frame = screen.window.frameGeometry()
    assert (frame.right(), frame.bottom()) == (area.right() - MARGIN, area.bottom() - MARGIN)


def test_a_click_elsewhere_closes_the_list_and_the_icon_does_not_reopen_it_at_once(
    qtbot: QtBot, screen: Screen, elsewhere: Callable[[], None]
) -> None:
    screen.open()
    elsewhere()
    qtbot.waitUntil(lambda: not screen.window.isVisible())
    # Counted on the list's clock, from after it closed: qtbot.wait counts on a Windows timer,
    # which can end a few ms before REOPEN_MS have passed there, and the click is ignored.
    closed = QElapsedTimer()
    closed.start()
    screen.list.toggle()  # the click on the icon that took the focus
    assert not screen.window.isVisible()
    qtbot.waitUntil(lambda: closed.elapsed() >= REOPEN_MS)
    screen.open()


def test_the_active_reminders_show_newest_first_with_their_state(screen: Screen) -> None:
    screen.list.show_reminders(
        RemindersView(
            (
                active(3, "quando apro Figma", "esportare le icone", 0, START + 690_000),
                active(2, "quando apro la posta", "rispondere a Giulia", silences=2),
                active(1, "se sono sul sito della banca", "pagare l'F24", 1, START + HOUR_MS),
            )
        )
    )
    screen.open()
    assert screen.lines() == [
        "Promemoria",
        "Attivi",
        "Esportare le icone",
        "Quando apro Figma",
        "Rimandato: torna tra 12 min",
        "Rispondere a Giulia",
        "Quando apro la posta",
        "Pagare l'F24",
        "Se sono sul sito della banca",
        "Rimandato: torna alle 11:00",
        PAUSE,
    ]
    # What they learned, under them, opens their places (ADR-0029).
    assert len(screen.named("Taciuto in 2 posti")) == 1
    assert len(screen.named("Taciuto in 1 posto")) == 1


MAIL = Context("vivaldi.exe", "Preventivi", "mail.google.com/mail/u/0")
ROSSI = Context("code.exe", "changelog.md - rossi", None)
TEAMS = Context("ms-teams.exe", "Chat con Marco", None)


LEARNED = "Taciuto in 1 posto · Chiesto in 2 posti · Più attento"
PLACES = ["changelog.md - rossi", "Chat con Marco", "Preventivi · mail.google.com"]


def learned() -> ActiveReminder:
    """A reminder Remind here asked in two places, the last first, and Not here silenced in one,
    whose threshold went down (ADR-0029)."""
    figma = active(1, "quando lavoro al progetto Rossi", "aggiornare il changelog")
    places = (Place(ROSSI, Here.YES), Place(TEAMS, Here.NO), Place(MAIL, Here.YES))
    return replace(figma, places=places, attentive=True)


def open_places(qtbot: QtBot, screen: Screen) -> None:
    """A click on what the reminder learned; its places are in place once the rows under them
    have moved down, through the event queue."""
    screen.click(LEARNED)
    qtbot.waitUntil(lambda: screen.lines()[-4:-1] == PLACES)


def test_the_row_at_the_top_writes_the_place_core_gives_each_time_the_list_opens(
    screen: Screen,
) -> None:
    screen.open()
    assert screen.asked.times == 1
    [row] = screen.named(TEXTS.remind_here.title)
    assert accessible(row, "description") == ""  # no place yet: only its name
    screen.remind_here.show(HereView(MAIL))
    assert accessible(row, "description") == "Preventivi · mail.google.com"
    texts = [item.property("text") for item in items(row) if item.inherits("QQuickText")]
    assert texts[1:3] == ["Qui dovevi avvisarmi", "Preventivi · mail.google.com"]
    screen.press(Qt.Key.Key_Escape)
    screen.open()
    assert screen.asked.times == 2


def test_the_row_at_the_top_opens_the_card_and_closes_the_list(screen: Screen) -> None:
    screen.open()
    screen.click(TEXTS.remind_here.title)
    assert not screen.window.isVisible()
    assert screen.asked.times == 2  # the list's, then the card's
    screen.remind_here.show(HereView(MAIL))
    assert screen.window_titled(TEXTS.remind_here.title).isVisible()


def test_what_a_reminder_learned_shows_under_it_and_opens_its_places(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.list.show_reminders(RemindersView((learned(),)))
    screen.open()
    assert len(screen.named(LEARNED)) == 1
    assert "Preventivi · mail.google.com" not in screen.lines()
    # The last answered first, each with its bell, struck where Not here silenced it.
    open_places(qtbot, screen)
    bells = [
        str(item.property("text"))
        for item in shown(screen.window)
        if item.inherits("QQuickText") and str(item.property("text")) in ("", "")
    ]
    assert bells[1:] == ["", "", ""]  # after the row of Remind here's
    assert [
        accessible(button, "description") for button in screen.named(TEXTS.tray_list.forget)
    ] == PLACES
    screen.click(LEARNED)
    assert "Chat con Marco" not in screen.lines()


def test_a_places_x_forgets_it_there_and_dimentica_tutto_forgets_everything(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.list.show_reminders(RemindersView((learned(),)))
    screen.open()
    open_places(qtbot, screen)
    screen.click_item(screen.named(TEXTS.tray_list.forget)[1])
    assert screen.commands.sent == [("withdraw", 1, TEAMS)]
    screen.click(TEXTS.tray_list.forget_all)
    assert screen.commands.sent == [("withdraw", 1, TEAMS), ("withdraw_all", 1)]
    # What `core` says next: the place gone, the line and the places with it.
    screen.list.show_reminders(RemindersView((replace(learned(), places=(), attentive=False),)))
    assert screen.named(TEXTS.tray_list.forget_all) == []
    assert screen.lines()[-3:-1] == ["Aggiornare il changelog", "Quando lavoro al progetto Rossi"]


def test_the_places_close_when_the_list_opens_again(qtbot: QtBot, screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((learned(),)))
    screen.open()
    open_places(qtbot, screen)
    assert len(screen.named(TEXTS.tray_list.forget)) == 3
    screen.press(Qt.Key.Key_Escape)
    screen.open()
    assert screen.named(TEXTS.tray_list.forget) == []


def test_the_learned_line_and_the_places_are_reached_by_tab(screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((learned(),)))
    screen.open()
    for _ in range(4):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (LEARNED, "Aggiornare il changelog")
    screen.press(Qt.Key.Key_Return)
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.tray_list.forget, "changelog.md - rossi")
    for _ in range(3):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.tray_list.forget_all, "Aggiornare il changelog")
    screen.press(Qt.Key.Key_Space)
    assert screen.commands.sent[-1] == ("withdraw_all", 1)


def test_a_reminder_shows_its_condition_without_the_time_and_the_time_written_for_today(
    screen: Screen,
) -> None:
    yesterday = START - 24 * HOUR_MS
    screen.list.show_reminders(
        RemindersView(
            (
                active(
                    3, "quando apro Claude dopo le 23", "bere un bicchiere d'acqua", perennial=True
                ),
                active(2, "domani alle 15", "chiamare Giulia", written_at=yesterday),
                active(1, "quando apro YouTube verso sera", "staccare"),
            )
        )
    )
    screen.open()
    assert screen.lines()[2:-1] == [
        "Bere un bicchiere d'acqua",
        "Quando apro Claude",
        "Ogni giorno dalle 23:00 alle 04:00",
        # Written yesterday: its "domani" is today. A reminder with only a time has only its line.
        "Chiamare Giulia",
        "Oggi, giovedì 1 ottobre, alle 15:00",
        # A time not understood: the condition whole, as written, and no line of a time.
        "Staccare",
        "Quando apro YouTube verso sera",
    ]
    # The time's line has the clock in front, as in the creation window.
    clocks = [item for item in shown(screen.window) if item.property("text") == ""]
    assert len(clocks) == 2


def test_the_time_is_written_for_the_jiffin_day_which_ends_at_4(screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((active(1, "domani alle 15", "chiamare Giulia"),)))
    screen.clock.advance(15 * HOUR_MS)  # 01:00 on Friday: still Thursday's night
    screen.open()
    assert "Domani, venerdì 2 ottobre, alle 15:00" in screen.lines()


def test_a_perennial_reminder_has_the_arrows_of_its_alert_where_completa_was(
    screen: Screen,
) -> None:
    screen.list.show_reminders(
        RemindersView(
            (
                active(2, "quando apro la posta", "rispondere a Giulia", perennial=True),
                active(1, "quando apro Figma", "esportare le icone"),
            )
        )
    )
    screen.open()
    [arrows] = screen.named(TEXTS.creation.perennial)
    assert arrows.property("text") == ""  # RepeatAll
    assert not arrows.inherits("QQuickAbstractButton")
    with pytest.raises(StopIteration):
        screen.button(TEXTS.tray_list.complete, "Rispondere a Giulia")
    assert screen.button(TEXTS.tray_list.complete, "Esportare le icone").isVisible()
    for name in (TEXTS.tray_list.edit, TEXTS.tray_list.delete):
        assert screen.button(name, "Rispondere a Giulia").isVisible()
    # In the same place, 32 px wide: the rows line up.
    complete = screen.button(TEXTS.tray_list.complete)
    assert (
        arrows.mapToScene(QPointF(arrows.width() / 2, 0)).x()
        == complete.mapToScene(QPointF(complete.width() / 2, 0)).x()
    )


def test_a_period_over_says_when_it_ended(screen: Screen) -> None:
    written = at(25, 9, 0, month=9)
    screen.list.show_reminders(
        RemindersView(
            (
                active(
                    2, "dal 28 al 30 settembre quando apro Figma", "esportare", written_at=written
                ),
                active(1, "dal 28 settembre all'8 ottobre quando apro Teams", "chiamare"),
            )
        )
    )
    screen.open()
    lines = screen.lines()
    assert "Periodo finito il 30 settembre" in lines
    assert not any(line.startswith("Periodo finito") and "ottobre" in line for line in lines)
    screen.clock.advance(8 * 24 * HOUR_MS)
    screen.list.show_reminders(
        RemindersView((active(1, "dal 28 settembre all'8 ottobre quando apro Teams", "chiamare"),))
    )
    assert "Periodo finito l'8 ottobre" in screen.lines()


def test_a_snooze_counts_down_while_the_list_is_open(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    dwm: list[tuple[object, ...]],
    focus_stays: None,
) -> None:
    monkeypatch.setattr(tray_list, "REFRESH_MS", 50)
    screen = Screen(qtbot)
    tomorrow = active(2, "quando apro Figma", "esportare le icone", 0, at(2, 8, 0))
    soon = active(1, "quando apro la posta", "rispondere a Giulia", 0, START + 5 * MINUTE_MS)
    screen.list.show_reminders(RemindersView((tomorrow, soon)))
    screen.open()
    assert "Rimandato: torna domani alle 08:00" in screen.lines()
    assert "Rimandato: torna tra 5 min" in screen.lines()
    screen.clock.advance(3 * MINUTE_MS)
    qtbot.waitUntil(lambda: "Rimandato: torna tra 2 min" in screen.lines())
    screen.clock.advance(2 * MINUTE_MS)
    qtbot.waitUntil(lambda: "Rimandato: torna tra 2 min" not in screen.lines())
    assert screen.lines()[-3:] == ["Rispondere a Giulia", "Quando apro la posta", PAUSE]
    screen.list.close()


def test_the_return_pause_shows_at_the_bottom_and_cambia_opens_the_settings(
    screen: Screen,
) -> None:
    screen.preferences.return_pause = 90
    screen.open()
    assert screen.lines()[-1] == "Gli avvisi tornano se riprendi una cosa dopo almeno 90 s."
    screen.preferences.return_pause = 300
    assert screen.lines()[-1] == "Gli avvisi tornano se riprendi una cosa dopo almeno 5 min."
    # After a thin line, the whole width of the list.
    lines = [
        item
        for item in shown(screen.window)
        if item.inherits("QQuickRectangle") and item.height() == 1 and not in_button(item)
    ]
    assert [line.width() for line in lines] == [screen.window.width()]
    screen.click(TEXTS.tray_list.change)
    assert not screen.window.isVisible()
    assert screen.window_titled(TEXTS.settings.title).isVisible()


def test_cambia_closes_the_list_itself_and_the_icon_opens_it_again_at_once(
    qtbot: QtBot, screen: Screen
) -> None:
    """Not closed by the settings taking the focus, which would hold the icon's next click for
    REOPEN_MS."""
    screen.open()
    screen.click(TEXTS.tray_list.change)
    qtbot.waitUntil(screen.window_titled(TEXTS.settings.title).isActive)
    screen.list.toggle()
    assert screen.window.isVisible()


def test_unseen_alerts_sit_on_top_with_fatto_and_rimanda(qtbot: QtBot, screen: Screen) -> None:
    alert = unseen(8, "controllare la scadenza dell'F24", at(1, 9, 31))
    screen.list.show_alerts(AlertsView((), 0, (alert,)))
    screen.list.show_reminders(RemindersView((active(1, "quando apro Figma", "esportare"),)))
    screen.open()
    assert screen.lines() == [
        "Promemoria",
        "Non visti",
        F24,
        "Quando apro il gestionale delle fatture, alle 09:31",
        "Attivi",
        "Esportare",
        "Quando apro Figma",
        PAUSE,
    ]
    assert screen.commands.sent == [("seen",)]
    screen.click(TEXTS.alert.done, F24)
    qtbot.waitUntil(lambda: screen.commands.sent[1:] == [("done", 8)])


def test_an_unseen_alerts_answer_waits_on_its_card_with_annulla(
    qtbot: QtBot, screen: Screen
) -> None:
    alerts = (unseen(9, "altro", at(1, 9, 40)), unseen(8, F24, at(1, 9, 31)))
    screen.list.show_alerts(AlertsView((), 0, alerts))
    screen.open()
    screen.click(TEXTS.alert.done, F24)
    assert screen.lines()[2:7] == [
        "Altro",
        "Quando apro il gestionale delle fatture, alle 09:40",
        F24,
        "Quando apro il gestionale delle fatture, alle 09:31",
        TEXTS.alert.done,
    ]
    assert screen.buttons(F24) == [TEXTS.command.cancel]
    screen.click(TEXTS.command.cancel, F24)
    qtbot.wait(2 * HOLD_MS)
    assert screen.commands.sent[1:] == []
    assert screen.buttons(F24) == [TEXTS.alert.done, TEXTS.alert.snooze]
    screen.click(TEXTS.alert.snooze, F24)
    screen.choose(TEXTS.alert.not_here)
    assert TEXTS.alert.not_here in screen.lines()
    qtbot.waitUntil(lambda: screen.commands.sent[1:] == [("not_here", 8)])
    # Gone to `core`: the card keeps the answer's name until `core` takes it away.
    assert TEXTS.alert.not_here in screen.lines()
    screen.list.show_alerts(AlertsView((), 0, alerts[:1]))
    assert F24 not in screen.lines()


def test_closing_the_list_sends_the_answers_still_waiting_at_once(screen: Screen) -> None:
    alerts = (unseen(9, "altro", at(1, 9, 40)), unseen(8, F24, at(1, 9, 31)))
    screen.list.show_alerts(AlertsView((), 0, alerts))
    screen.open()
    screen.click(TEXTS.alert.done, F24)
    screen.click(TEXTS.alert.snooze, "Altro")
    screen.choose(TEXTS.snooze.hour)
    screen.list.close()
    assert screen.commands.sent[1:] == [("done", 8), ("snooze", 9, Snooze.HOUR)]
    screen.open()  # if `core` is late, the cards come back with their buttons
    assert TEXTS.alert.done not in screen.lines()


def test_an_alert_that_leaves_the_unseen_takes_its_waiting_answer_away(
    qtbot: QtBot, screen: Screen
) -> None:
    # Its reminder was completed or deleted in the list meanwhile, or rang again (ADR-0030).
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.done, F24)
    screen.list.show_alerts(AlertsView((), 0, ()))
    qtbot.wait(2 * HOLD_MS)
    screen.list.close()
    assert screen.commands.sent == [("seen",)]


def test_by_keyboard_annulla_takes_the_focus_and_gives_it_back_to_fatto(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.list.show_reminders(RemindersView((active(1, "quando apro Figma", "esportare"),)))
    screen.open()
    for _ in range(3):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.alert.done, "")
    screen.press(Qt.Key.Key_Space)
    assert screen.focused() == (TEXTS.command.cancel, F24)
    assert ringed(screen.button(TEXTS.command.cancel, F24))
    screen.press(Qt.Key.Key_Space)
    assert screen.focused() == (TEXTS.alert.done, "")
    assert ringed(screen.button(TEXTS.alert.done, F24))
    assert screen.commands.sent == [("seen",)]


def test_an_unseen_alert_names_its_condition_without_the_time(screen: Screen) -> None:
    alerts = (
        unseen(9, "bere", at(1, 9, 0), condition="quando apro Claude dopo le 23"),
        unseen(8, "chiamare Giulia", at(30, 15, 0, month=9), condition="alle 15"),
    )
    screen.list.show_alerts(AlertsView((), 0, alerts))
    screen.open()
    assert screen.lines()[2:6] == [
        "Bere",
        "Quando apro Claude, alle 09:00",
        "Chiamare Giulia",
        "Ieri alle 15:00",
    ]


def test_older_unseen_alerts_say_which_day_they_came(screen: Screen) -> None:
    alerts = (
        unseen(4, "ieri", at(30, 18, 20, month=9)),
        unseen(3, "tre giorni fa", at(28, 9, 5, month=9)),
        unseen(2, "un mese fa", at(1, 12, 0, month=9)),
    )
    screen.list.show_alerts(AlertsView((), 0, alerts))
    screen.open()
    condition = "Quando apro il gestionale delle fatture, "
    assert [line for line in screen.lines() if line.startswith(condition)] == [
        condition + "ieri alle 18:20",
        condition + "il 28 settembre alle 09:05",
        condition + "l'1 settembre alle 12:00",
    ]


def test_an_alert_new_to_the_list_keeps_its_dot_until_the_list_closes(screen: Screen) -> None:
    old = unseen(7, "vecchio", START - HOUR_MS, seen_at=START - 30 * MINUTE_MS)
    new = unseen(8, "nuovo", START - MINUTE_MS)
    screen.list.show_alerts(AlertsView((), 0, (new, old)))
    screen.open()
    assert screen.commands.sent == [("seen",)]
    assert column(screen.list.property("unseen"), "fresh") == [True, False]
    seen = replace(new, seen_at=screen.clock.now())
    screen.list.show_alerts(AlertsView((), 0, (seen, old)))
    assert column(screen.list.property("unseen"), "fresh") == [True, False]
    newer = unseen(9, "appena sparito", screen.clock.now())
    screen.list.show_alerts(AlertsView((), 0, (newer, seen, old)))
    assert screen.commands.sent == [("seen",), ("seen",)]
    assert column(screen.list.property("unseen"), "fresh") == [True, True, False]
    screen.list.close()
    assert column(screen.list.property("unseen"), "fresh") == [False, False, False]


# Snooze's menu, on an unseen alert


def test_rimanda_opens_the_alerts_menu_over_its_button_where_the_work_area_ends(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    menu, window = screen.menu, screen.window
    assert menu.isVisible()
    assert [accessible(item, "name") for item in screen.menu_items()] == list(MENU)
    hwnd = int(menu.winId())
    assert ("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW) in dwm
    assert ("nudge", hwnd) in dwm
    # The list sits over the tray: under its button the menu would go past the work area.
    button = screen.button(TEXTS.alert.snooze, F24)
    corner = button.mapToScene(QPointF(0, 0))
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert window.y() + corner.y() + button.height() + 4 + menu.height() > area.bottom() + 1
    assert (menu.x(), menu.y()) == (
        window.x() + rounded(corner.x()),
        rounded(window.y() + corner.y() - 4 - menu.height()),
    )


def test_rimanda_opens_the_menu_under_its_button_where_there_is_room(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    # Where the user drags it: the offscreen platform has no system move.
    screen.window.setFramePosition(QPoint(30, 40))
    screen.click(TEXTS.alert.snooze, F24)
    button = screen.button(TEXTS.alert.snooze, F24)
    corner = button.mapToScene(QPointF(0, 0))
    window = screen.window
    assert (screen.menu.x(), screen.menu.y()) == (
        window.x() + rounded(corner.x()),
        rounded(window.y() + corner.y() + button.height() + 4),
    )


@pytest.mark.parametrize(
    ("item", "answer"),
    [
        (TEXTS.snooze.next_time, ("snooze", 8, Snooze.NEXT_TIME)),
        (TEXTS.snooze.quarter_hour, ("snooze", 8, Snooze.QUARTER_HOUR)),
        (TEXTS.snooze.hour, ("snooze", 8, Snooze.HOUR)),
        (TEXTS.snooze.tomorrow, ("snooze", 8, Snooze.TOMORROW)),
        (TEXTS.alert.not_here, ("not_here", 8)),
    ],
)
def test_each_item_of_the_menu_answers_for_its_alert(
    qtbot: QtBot, screen: Screen, item: str, answer: tuple[object, ...]
) -> None:
    alerts = (unseen(9, "altro", at(1, 9, 40)), unseen(8, F24, at(1, 9, 31)))
    screen.list.show_alerts(AlertsView((), 0, alerts))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    screen.choose(item)
    assert item in screen.lines()  # it waits 5 s under its name
    qtbot.waitUntil(lambda: screen.commands.sent[1:] == [answer])
    assert not screen.menu.isVisible()
    assert screen.window.isVisible()


def test_the_menu_has_alla_prossima_volta_only_with_a_next_unit(screen: Screen) -> None:
    # It rang this evening, the only instance of its time.
    tonight = unseen(8, F24, at(1, 19, 31), condition="stasera quando apro il gestionale")
    screen.clock.advance(10 * HOUR_MS)
    screen.list.show_alerts(AlertsView((), 0, (tonight,)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    assert [accessible(item, "name") for item in screen.menu_items()] == list(MENU[1:])


def test_a_press_anywhere_in_the_list_closes_the_menu_and_does_nothing_more(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    screen.click(TEXTS.alert.done, F24)
    assert not screen.menu.isVisible()
    # A second click on Snooze only closes it.
    screen.click(TEXTS.alert.snooze, F24)
    screen.click(TEXTS.alert.snooze, F24)
    assert not screen.menu.isVisible()
    # And a drag does not move the list.
    screen.click(TEXTS.alert.snooze, F24)
    window = screen.window
    assert not drags(window, QPoint(4, window.height() - 4))
    assert not screen.menu.isVisible()
    assert screen.commands.sent == [("seen",)]


def test_the_wheel_closes_the_menu(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    middle = QPointF(screen.window.width() / 2, screen.window.height() / 2)
    notch = QWheelEvent(
        middle,
        screen.window.mapToGlobal(middle),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QGuiApplication.sendEvent(screen.window, notch)
    assert not screen.menu.isVisible()


def test_esc_closes_the_menu_before_the_list(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    screen.press(Qt.Key.Key_Escape)
    assert (screen.menu.isVisible(), screen.window.isVisible()) == (False, True)
    screen.press(Qt.Key.Key_Escape)
    assert not screen.window.isVisible()


def test_the_menu_by_keyboard(qtbot: QtBot, screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    for _ in range(4):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.alert.snooze, "")
    # Opened by the keyboard, on its first item, with WinUI's focus ring.
    screen.press(Qt.Key.Key_Return)
    assert screen.menu.isVisible()
    assert screen.menu.property("current") == 0
    assert [ringed(item) for item in screen.menu_items()] == [True, False, False, False, False]
    # Round from the first to the last, as in Windows' menus.
    screen.press(Qt.Key.Key_Up)
    assert screen.menu.property("current") == len(MENU) - 1
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Down)
    assert screen.menu.property("current") == 2
    screen.press(Qt.Key.Key_Space)
    assert not screen.menu.isVisible()
    # The answer waits on the card, and Undo takes the focus from Snooze.
    assert screen.focused() == (TEXTS.command.cancel, F24)
    qtbot.waitUntil(lambda: screen.commands.sent[-1] == ("snooze", 8, Snooze.HOUR))


def test_tab_moving_on_closes_the_menu(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.list.show_reminders(RemindersView((active(1, "quando apro Figma", "esportare"),)))
    screen.open()
    for _ in range(4):
        screen.press(Qt.Key.Key_Tab)
    screen.press(Qt.Key.Key_Space)
    assert screen.menu.isVisible()
    screen.press(Qt.Key.Key_Tab)
    assert not screen.menu.isVisible()
    assert screen.focused() == (TEXTS.tray_list.complete, "Esportare")


def test_opened_under_the_mouse_the_menu_waits_for_a_key_to_mark_an_item(
    qtbot: QtBot, screen: Screen
) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    assert screen.menu.property("current") == -1
    assert not any(ringed(item) for item in screen.menu_items())
    screen.press(Qt.Key.Key_Down)
    assert screen.menu.property("current") == 0
    screen.press(Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: screen.commands.sent[-1] == ("snooze", 8, Snooze.NEXT_TIME))


def test_enter_before_a_key_moves_is_a_click_on_rimanda(screen: Screen) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    screen.press(Qt.Key.Key_Return)
    assert not screen.menu.isVisible()
    assert screen.commands.sent == [("seen",)]


def test_the_menu_goes_with_its_alert_and_with_the_list(screen: Screen) -> None:
    alert = unseen(8, F24, at(1, 9, 31))
    screen.list.show_alerts(AlertsView((), 0, (alert,)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    # Answered on another alert of its reminder, or replaced by a newer one.
    screen.list.show_alerts(AlertsView((), 0, ()))
    assert not screen.menu.isVisible()
    screen.list.show_alerts(AlertsView((), 0, (alert,)))
    screen.click(TEXTS.alert.snooze, F24)
    screen.list.close()
    assert not screen.menu.isVisible()
    assert screen.list.property("menuFor") == 0


def test_a_click_elsewhere_closes_the_list_with_its_menu(
    qtbot: QtBot, screen: Screen, elsewhere: Callable[[], None]
) -> None:
    screen.list.show_alerts(AlertsView((), 0, (unseen(8, F24, at(1, 9, 31)),)))
    screen.open()
    screen.click(TEXTS.alert.snooze, F24)
    qtbot.waitUntil(lambda: QGuiApplication.focusWindow() is screen.window)
    elsewhere()
    qtbot.waitUntil(lambda: not screen.window.isVisible())
    assert not screen.menu.isVisible()


# Reminders


def test_nuovo_and_modifica_open_the_creation_window_and_close_the_list(screen: Screen) -> None:
    posta = active(2, "quando apro la posta", "rispondere a Giulia", perennial=True)
    screen.list.show_reminders(RemindersView((posta,)))
    screen.open()
    screen.click(TEXTS.tray_list.new)
    assert not screen.window.isVisible()
    screen.open()
    screen.click(TEXTS.tray_list.edit, "Rispondere a Giulia")
    assert not screen.window.isVisible()
    # The whole revision: the creation window shows its "Ogni volta" and its saved time.
    assert screen.writer.opened == [("new",), ("edit", posta.reminder.revision)]


def test_completa_goes_to_core_and_elimina_asks_first(screen: Screen) -> None:
    screen.list.show_reminders(
        RemindersView(
            (
                active(2, "quando apro la posta", "rispondere a Giulia"),
                active(1, "quando apro Figma", "esportare le icone"),
            )
        )
    )
    screen.open()
    screen.click(TEXTS.tray_list.complete, "Rispondere a Giulia")
    screen.click(TEXTS.tray_list.delete, "Esportare le icone")
    assert screen.lines()[-3:-1] == ["Esportare le icone", "Eliminare il promemoria per sempre?"]
    screen.click(TEXTS.command.cancel, "Esportare le icone")
    assert screen.lines()[-3:-1] == ["Esportare le icone", "Quando apro Figma"]
    screen.click(TEXTS.tray_list.delete, "Esportare le icone")
    screen.click(TEXTS.tray_list.delete, "Esportare le icone")
    assert screen.commands.sent == [("complete", 2), ("delete", 1)]
    assert screen.window.isVisible()


COMPLETED = (
    completed(4, "quando apro la posta", "mandare la fattura a Rossi", at(1, 9, 40)),
    completed(3, "quando apro il calendario", "prenotare il tagliando", at(30, 8, 0, month=9)),
    completed(2, "domani alle 9", "chiamare l'idraulico", at(26, 18, 0, month=9)),
)
"""Completed today, yesterday and days ago, the last one with only a time."""
FATTURA = "Mandare la fattura a Rossi"


def test_the_completed_reminders_sit_under_the_active_ones_closed_at_first(
    screen: Screen,
) -> None:
    figma = active(1, "quando apro Figma", "esportare le icone")
    screen.list.show_reminders(RemindersView((figma,), completed=COMPLETED))
    screen.open()
    assert screen.lines()[-3:] == ["Esportare le icone", "Quando apro Figma", PAUSE]
    screen.click("Completati · 3")
    assert screen.lines()[-9:] == [
        "Esportare le icone",
        "Quando apro Figma",
        FATTURA,
        "Quando apro la posta · completato alle 09:40",
        "Prenotare il tagliando",
        "Quando apro il calendario · completato ieri",
        "Chiamare l'idraulico",
        "Completato il 26 settembre",
        PAUSE,
    ]
    screen.list.close()
    screen.open()
    assert screen.lines()[-3:] == ["Esportare le icone", "Quando apro Figma", PAUSE]


def test_a_completed_reminders_action_is_struck_through_and_grey(screen: Screen) -> None:
    figma = active(1, "quando apro Figma", "esportare le icone")
    screen.list.show_reminders(RemindersView((figma,), completed=COMPLETED[:1]))
    screen.open()
    screen.click("Completati · 1")
    texts = {
        str(item.property("text")): item
        for item in shown(screen.window)
        if item.inherits("QQuickText") and not in_button(item)
    }
    struck, condition = texts[FATTURA], texts["Quando apro Figma"]
    assert struck.property("font").strikeOut()
    assert not texts["Esportare le icone"].property("font").strikeOut()
    assert struck.property("color") == condition.property("color")


def test_the_full_circle_reopens_and_the_bin_asks_first(screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((), completed=COMPLETED[:1]))
    screen.open()
    screen.click("Completati · 1")
    screen.click(TEXTS.tray_list.reopen, FATTURA)
    screen.click(TEXTS.tray_list.delete, FATTURA)
    assert screen.lines()[-3:-1] == [FATTURA, TEXTS.tray_list.delete_question]
    screen.click(TEXTS.command.cancel, FATTURA)
    assert screen.lines()[-3:-1] == [FATTURA, "Quando apro la posta · completato alle 09:40"]
    screen.click(TEXTS.tray_list.delete, FATTURA)
    screen.click(TEXTS.tray_list.delete, FATTURA)
    assert screen.commands.sent == [("reopen", 4), ("delete", 4)]
    assert screen.window.isVisible()


def test_the_completed_section_by_keyboard(screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((), completed=COMPLETED[:1]))
    screen.open()
    for _ in range(3):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == ("Completati · 1", "")
    assert ringed(screen.button("Completati · 1"))
    screen.press(Qt.Key.Key_Return)
    screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.tray_list.reopen, FATTURA)
    screen.press(Qt.Key.Key_Space)
    assert screen.commands.sent == [("reopen", 4)]


def test_without_completed_reminders_there_is_no_section(screen: Screen) -> None:
    screen.list.show_reminders(RemindersView((active(1, "quando apro Figma", "esportare"),)))
    screen.open()
    names = [str(accessible(item, "name")) for item in shown(screen.window)]
    assert not any(name.startswith("Completati") for name in names)


def test_elimina_asks_by_keyboard_too_and_annulla_comes_first(screen: Screen) -> None:
    screen.list.show_reminders(
        RemindersView((active(1, "quando apro Figma", "esportare le icone"),))
    )
    screen.open()
    for _ in range(5):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.tray_list.delete, "Esportare le icone")
    screen.press(Qt.Key.Key_Return)
    assert screen.focused() == (TEXTS.command.cancel, "Esportare le icone")
    screen.press(Qt.Key.Key_Return)
    assert screen.focused() == (TEXTS.tray_list.delete, "Esportare le icone")
    screen.press(Qt.Key.Key_Return)
    screen.press(Qt.Key.Key_Tab)
    screen.press(Qt.Key.Key_Return)
    assert screen.commands.sent == [("delete", 1)]


def test_the_question_of_elimina_goes_when_the_list_closes(screen: Screen) -> None:
    screen.list.show_reminders(
        RemindersView((active(1, "quando apro Figma", "esportare le icone"),))
    )
    screen.open()
    screen.click(TEXTS.tray_list.delete, "Esportare le icone")
    screen.press(Qt.Key.Key_Escape)
    screen.open()
    assert screen.lines()[-3:-1] == ["Esportare le icone", "Quando apro Figma"]


def test_tab_goes_from_button_to_button_and_keeps_its_place_while_rows_come(
    screen: Screen,
) -> None:
    alert = unseen(8, "controllare la scadenza dell'F24", at(1, 9, 31))
    screen.list.show_alerts(AlertsView((), 0, (alert,)))
    figma = active(1, "quando apro Figma", "esportare le icone")
    screen.list.show_reminders(RemindersView((figma,)))
    screen.open()
    order = []
    for _ in range(8):
        screen.press(Qt.Key.Key_Tab)
        order.append(screen.focused())
    assert order == [
        (TEXTS.tray_list.new, ""),
        (TEXTS.remind_here.title, ""),
        (TEXTS.alert.done, ""),
        (TEXTS.alert.snooze, ""),
        (TEXTS.tray_list.complete, "Esportare le icone"),
        (TEXTS.tray_list.edit, "Esportare le icone"),
        (TEXTS.tray_list.delete, "Esportare le icone"),
        (TEXTS.tray_list.change, ""),
    ]
    screen.press(Qt.Key.Key_Backtab)
    posta = active(2, "quando apro la posta", "rispondere a Giulia")
    screen.list.show_reminders(RemindersView((posta, figma)))
    assert screen.focused() == (TEXTS.tray_list.delete, "Esportare le icone")


def test_a_long_list_scrolls_to_the_button_tab_reaches(screen: Screen) -> None:
    many = tuple(
        active(n, f"quando apro il progetto {n}", f"chiudere il ticket {n}")
        for n in range(40, 0, -1)
    )
    screen.list.show_reminders(RemindersView(many))
    screen.open()
    area = QGuiApplication.primaryScreen().availableGeometry()
    assert screen.window.height() == area.height() - 2 * MARGIN
    for _ in range(2 + 3 * 40):
        screen.press(Qt.Key.Key_Tab)
    assert screen.focused() == (TEXTS.tray_list.delete, "Chiudere il ticket 1")
    button = screen.window.activeFocusItem()
    assert button is not None
    bottom = button.mapToScene(QPointF(0, button.height())).y()
    assert 0 < bottom <= screen.window.height()


def test_a_long_list_scrolls_with_the_wheel(screen: Screen, qtbot: QtBot) -> None:
    """The mouse no longer scrolls it by dragging, which moves the window instead."""
    many = tuple(
        active(n, f"quando apro il progetto {n}", f"chiudere il ticket {n}")
        for n in range(40, 0, -1)
    )
    screen.list.show_reminders(RemindersView(many))
    screen.open()
    (scroller,) = (item for item in shown(screen.window) if item.inherits("QQuickFlickable"))
    assert scroller.property("contentY") == 0
    middle = QPointF(screen.window.width() / 2, screen.window.height() / 2)
    notch = QWheelEvent(
        middle,
        screen.window.mapToGlobal(middle),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QGuiApplication.sendEvent(screen.window, notch)
    qtbot.waitUntil(lambda: scroller.property("contentY") > 0)


# What keeps Jiffin from working fully


@pytest.mark.parametrize(
    ("engine", "message", "retry"),
    [
        (TrayList.Engine.RESTARTING, "Il modello si è fermato: lo sto riavviando.", False),
        (
            TrayList.Engine.FAILURES,
            (
                "Il modello si è fermato quattro volte in un'ora. Finché non riparte, i "
                "promemoria non avvisano."
            ),
            True,
        ),
        (
            TrayList.Engine.MODEL,
            "Il modello non si carica. Finché non riparte, i promemoria non avvisano.",
            True,
        ),
        (
            TrayList.Engine.GPU_MEMORY,
            (
                "La scheda video non ha abbastanza memoria per il modello. Chiudi un'app che "
                "la usa, poi riprova."
            ),
            True,
        ),
        (
            TrayList.Engine.MISMATCH,
            "Il modello è di un'altra versione di Jiffin: reinstalla l'app.",
            False,
        ),
    ],
)
def test_a_trouble_with_the_engine_shows_on_top(
    screen: Screen, engine: TrayList.Engine, message: str, retry: bool
) -> None:
    screen.list.show_engine(engine)
    screen.open()
    assert screen.lines()[:2] == ["Promemoria", message]
    if retry:
        screen.click(TEXTS.command.retry)
        assert screen.retries == 1
    else:
        with pytest.raises(StopIteration):
            screen.button(TEXTS.command.retry)
    screen.list.show_engine(TrayList.Engine.WORKING)
    assert message not in screen.lines()


def test_an_unreadable_address_shows_a_banner_naming_the_browsers(screen: Screen) -> None:
    screen.list.show_unreadable(frozenset({"chrome.exe", "brave.exe"}))
    screen.open()
    banner = "Brave e Chrome: non riesco a leggere l'indirizzo. Uso solo app e titolo."
    assert screen.lines()[:2] == ["Promemoria", banner]
    screen.list.show_unreadable(frozenset({"vivaldi.exe"}))
    assert screen.lines()[1] == "Vivaldi: non riesco a leggere l'indirizzo. Uso solo app e titolo."
    screen.list.show_unreadable(frozenset())
    assert screen.lines() == ["Promemoria", "Attivi", "Nessun promemoria attivo.", PAUSE]


def test_the_pause_from_the_tray_shows_first_until_it_ends_and_riprendi_ends_it(
    screen: Screen,
) -> None:
    """ADR-0024: the list opens at 10:00 in Rome."""
    stopped = (
        "Il modello si è fermato quattro volte in un'ora."
        " Finché non riparte, i promemoria non avvisano."
    )
    screen.list.show_engine(TrayList.Engine.FAILURES)
    screen.list.show_reminders(RemindersView((), at(1, 15, 30)))
    screen.open()
    assert screen.lines()[:3] == ["Promemoria", "In pausa fino alle 15:30.", stopped]
    screen.click(TEXTS.tray.resume)
    assert screen.resumes == 1
    screen.list.show_reminders(RemindersView((), at(2, 8, 0)))
    assert screen.lines()[1] == "In pausa fino a domani alle 08:00."
    screen.list.show_reminders(RemindersView(()))
    assert screen.lines()[:2] == ["Promemoria", stopped]


def test_a_pause_until_eight_is_no_longer_tomorrow_after_midnight(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    dwm: list[tuple[object, ...]],
    focus_stays: None,
) -> None:
    monkeypatch.setattr(tray_list, "REFRESH_MS", 50)
    screen = Screen(qtbot)
    screen.list.show_reminders(RemindersView((), at(2, 8, 0)))
    screen.open()
    assert screen.lines()[1] == "In pausa fino a domani alle 08:00."
    screen.clock.advance(at(2, 0, 30) - START)
    qtbot.waitUntil(lambda: screen.lines()[1] == "In pausa fino alle 08:00.")
    screen.list.close()


def test_the_model_on_its_way_shows_on_top_and_dettagli_opens_its_window(
    screen: Screen,
) -> None:
    screen.model(FirstRun.Stage.DOWNLOADING, SIZE // 3)
    screen.open()
    assert screen.lines()[:2] == [
        "Promemoria",
        "Scarico il modello: 0,8 GB di 2,4 GB. Finché non è pronto, i promemoria non avvisano.",
    ]
    assert any(item.inherits("QQuickProgressBar") for item in shown(screen.window))
    with pytest.raises(StopIteration):
        screen.button(TEXTS.command.retry)
    screen.click(TEXTS.first_run.details)
    assert not screen.window.isVisible()
    assert screen.first_run.property("waiting")
    assert screen.window_titled(TEXTS.first_run.welcome).isVisible()
    screen.first_run.close()


def test_a_problem_with_the_model_shows_with_riprova(screen: Screen) -> None:
    screen.model(FirstRun.Stage.NETWORK, SIZE // 3)
    screen.open()
    assert screen.lines()[1] == (
        "Il download si è fermato: controlla la connessione. Riprova riprende da dove era rimasto."
    )
    assert not any(item.inherits("QQuickProgressBar") for item in shown(screen.window))
    screen.click(TEXTS.command.retry)
    assert screen.fetches == 1
    retrying = screen.button(TEXTS.command.retrying)
    assert not retrying.isEnabled()
    screen.model(FirstRun.Stage.DOWNLOADING, SIZE // 2)
    assert screen.lines()[1].startswith("Scarico il modello: 1,2 GB di 2,4 GB")


@pytest.mark.parametrize("stage", [FirstRun.Stage.CHECKING, FirstRun.Stage.READY])
def test_the_check_and_a_ready_model_show_no_line(screen: Screen, stage: FirstRun.Stage) -> None:
    screen.model(stage, SIZE)
    screen.open()
    assert screen.lines() == ["Promemoria", "Attivi", "Nessun promemoria attivo.", PAUSE]


def test_the_list_goes_with_the_engine_and_no_binding_reads_it_gone(
    qtbot: QtBot, dwm: list[tuple[object, ...]]
) -> None:
    """On quitting, Python lets go of the interface in any order: the list stays until the
    engine goes, and then none of its window's bindings reads it gone (a warning fails)."""
    look = Look(lambda: DARK)
    engine = QQmlEngine()
    look.provide(engine)
    clock = SimulatedClock(0)
    first_run = FirstRun(
        engine, MODEL, lambda: None, Glass(look), Places(lambda places: None), clock
    )
    preferences = Preferences(
        engine,
        look,
        lambda material: None,
        lambda seconds: None,
        Glass(look),
        Places(lambda places: None),
    )
    trays = TrayList(
        engine,
        Commands(),
        Writer(),
        RemindHere(engine, Asked(), Stacked(), Glass(look), clock),
        lambda: None,
        lambda: None,
        first_run,
        preferences,
        Glass(look),
        clock,
    )
    trays.show_reminders(RemindersView((active(1, "quando apro Figma", "esportare le icone"),)))
    gone: list[str] = []
    trays.destroyed.connect(lambda: gone.append("list"))
    del trays
    gc.collect()
    assert gone == []
    del engine
    gc.collect()
    assert gone == ["list"]
