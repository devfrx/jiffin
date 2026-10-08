import gc
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext, qmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.records import Outcome, Reminder, Revision
from jiffin.core.reminders import HereReminder, HereView
from jiffin.lang.texts import TEXTS
from jiffin.ui import win32
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings
from jiffin.ui.overlay import TOP
from jiffin.ui.remind_here import MARGIN, RemindHere

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
ROME = timezone(timedelta(hours=2))
START = int(datetime(2026, 10, 8, 15, 0, tzinfo=ROME).timestamp() * 1000)
"""Thursday 8 October 2026, 15:00 in Rome."""
MAIL = Context("vivaldi.exe", "Preventivi", "mail.google.com/mail/u/0")
QUESTION = "Qui dovevi avvisarmi di…"


class Asked:
    """What the card asked of `core`: how many times what it shows, and each Remind here."""

    def __init__(self) -> None:
        self.times = 0
        self.reminded: list[tuple[int, Context]] = []

    def here(self) -> None:
        self.times += 1

    def remind_here(self, reminder_id: int, context: Context) -> None:
        self.reminded.append((reminder_id, context))


class Stacked:
    """What the card asked of the overlay, in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def above(self, window: QQuickWindow) -> None:
        self.calls.append("above")

    def layout(self) -> None:
        self.calls.append("layout")


def revision(reminder_id: int, condition: str, action: str, written_at: int) -> Revision:
    """As `core` makes one: its time read when written."""
    reading = read(condition, datetime.fromtimestamp(written_at / 1000, ROME))
    return Revision(
        reminder_id,
        reminder_id,
        1,
        condition,
        action,
        reading.remainder,
        schedule=reading.schedule,
        written_at=written_at,
    )


def here(
    reminder_id: int,
    condition: str,
    action: str,
    quiet: Outcome | None = None,
    written_at: int = START,
) -> HereReminder:
    written = revision(reminder_id, condition, action, written_at)
    return HereReminder(Reminder(reminder_id, written_at, written), quiet)


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def accessible(item: QQuickItem, name: str) -> object:
    """None for the items a control makes on its own, which QML never sees."""
    context = qmlContext(item)
    return None if context is None else QQmlProperty(item, f"Accessible.{name}", context).read()


def shown(window: QQuickWindow) -> list[QQuickItem]:
    # Layouts place what they show only when polished, before the next frame.
    for item in items(window.contentItem()):
        item.ensurePolished()
    return [item for item in items(window.contentItem()) if item.isVisible()]


class Screen:
    """The card on the offscreen screen, with what it asked of `core` and of the overlay."""

    def __init__(self, qtbot: QtBot) -> None:
        self._qtbot = qtbot
        self.look = Look(lambda: DARK)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.clock = SimulatedClock(START, ROME)
        self.asked = Asked()
        self.stack = Stacked()
        self.card = RemindHere(self.engine, self.asked, self.stack, Glass(self.look), self.clock)
        (window,) = (
            w
            for w in QGuiApplication.topLevelWindows()
            if qmlEngine(w) is self.engine and w.title() == TEXTS.remind_here.title
        )
        assert isinstance(window, QQuickWindow)
        self.window = window

    def open(self, view: HereView) -> None:
        """Win+Shift+Q, and `core`'s answer: the card is ready once it has the focus."""
        self.card.open()
        assert not self.window.isVisible()  # until `core` answers
        self.card.show(view)
        self._qtbot.waitUntil(self.window.isActive)

    def lines(self) -> list[str]:
        """What the card reads, top to bottom, without its icons."""
        found = []
        for item in shown(self.window):
            text = str(item.property("text")) if item.inherits("QQuickText") else ""
            if text and not "" <= text[0] <= "":
                corner = item.mapToScene(QPointF(0, 0))
                found.append((corner.y(), corner.x(), text))
        return [text for _, _, text in sorted(found)]

    def rows(self) -> list[QQuickItem]:
        """The reminders, as buttons, from the top."""
        found = [
            item
            for item in shown(self.window)
            if item.inherits("QQuickAbstractButton")
            and accessible(item, "name") != TEXTS.command.close
        ]
        return sorted(found, key=lambda item: item.mapToScene(QPointF(0, 0)).y())

    def click(self, item: QQuickItem) -> None:
        centre = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(
            self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre
        )

    def close_button(self) -> QQuickItem:
        return next(
            item
            for item in shown(self.window)
            if item.inherits("QQuickAbstractButton")
            and accessible(item, "name") == TEXTS.command.close
        )

    def press(self, key: Qt.Key) -> None:
        QTest.keyClick(self.window, key)

    def ringed(self) -> list[bool]:
        """Which reminders show WinUI's focus ring: the keyboard's."""
        return [
            any(
                child.inherits("QQuickRectangle")
                and child.isVisible()
                and (context := qmlContext(child)) is not None
                and QQmlProperty(child, "border.width", context).read() == 2
                for child in items(row)
            )
            for row in self.rows()
        ]


@pytest.fixture
def screen(qtbot: QtBot, dwm: list[tuple[object, ...]]) -> Iterator[Screen]:
    screen = Screen(qtbot)
    yield screen
    screen.card.close()


@pytest.fixture
def elsewhere(qtbot: QtBot) -> Iterator[QWindow]:
    """Another window, which a click or Alt+Tab activates."""
    other = QWindow()
    other.resize(100, 100)
    yield other
    other.destroy()


VIEW = HereView(
    MAIL,
    (
        here(3, "quando lavoro al progetto Rossi", "aggiornare il changelog", Outcome.SNOOZED),
        here(2, "quando apro la posta", "rispondere a Giulia"),
        here(1, "domani alle 15", "chiamare Giulia per il preventivo", Outcome.OUTSIDE_TIME),
    ),
)


def test_the_card_opens_once_core_answers_on_top_of_the_alerts_with_the_focus(
    screen: Screen,
) -> None:
    assert screen.stack.calls == ["above"]
    screen.card.open()
    assert screen.asked.times == 1
    assert not screen.window.isVisible()
    screen.card.show(VIEW)
    assert screen.window.isVisible()
    # Put in place, over the alerts, before it shows: the work area may have moved.
    assert screen.stack.calls == ["above", "layout"]


def test_the_card_is_drawn_like_an_alert_but_takes_the_focus(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    flags = screen.window.flags()
    for flag in (
        Qt.WindowType.Tool,
        Qt.WindowType.FramelessWindowHint,
        Qt.WindowType.WindowStaysOnTopHint,
    ):
        assert flags & flag
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert screen.window.width() == 540  # an alert's
    hwnd = int(screen.window.winId())
    assert ("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW) in dwm
    screen.open(VIEW)
    assert ("nudge", hwnd) in dwm


def test_the_card_writes_the_place_then_the_reminders_in_cores_order(screen: Screen) -> None:
    screen.open(VIEW)
    assert screen.lines() == [
        "Preventivi · mail.google.com",
        QUESTION,
        "Aggiornare il changelog",
        "Quando lavoro al progetto Rossi · Rimandato",
        "Rispondere a Giulia",
        "Quando apro la posta",
        "Chiamare Giulia per il preventivo",
        "Domani, venerdì 9 ottobre, alle 15:00 · Fuori orario",
    ]
    assert [accessible(row, "name") for row in screen.rows()] == [
        "Aggiornare il changelog",
        "Rispondere a Giulia",
        "Chiamare Giulia per il preventivo",
    ]


@pytest.mark.parametrize(
    ("condition", "days_ago", "quiet", "line"),
    [
        ("quando apro Steam", 0, None, "Quando apro Steam"),
        ("quando apro Steam", 0, Outcome.SILENCED, "Quando apro Steam · Taciuto qui"),
        ("quando apro Steam", 0, Outcome.SNOOZED, "Quando apro Steam · Rimandato"),
        ("quando apro Steam", 0, Outcome.SAME_OCCASION, "Quando apro Steam · Già suonato"),
        ("quando apro Steam dopo le 23", 0, Outcome.OUTSIDE_TIME,
         "Quando apro Steam · Fuori orario"),
        ("per tre giorni quando apro Steam", 5, Outcome.OUTSIDE_TIME,
         "Quando apro Steam · Periodo finito"),
        # The situations' words come with #153, as in the tray list.
        ("quando sono a casa e apro Steam", 0, Outcome.OUTSIDE_SITUATION,
         "Quando apro Steam · Fuori situazione"),
        ("alle 18", 0, Outcome.OUTSIDE_TIME, "Alle 18:00 · Fuori orario"),
    ],
)  # fmt: skip
def test_after_its_condition_a_reminder_says_what_else_kept_it_quiet_there(
    screen: Screen, condition: str, days_ago: int, quiet: Outcome | None, line: str
) -> None:
    """ADR-0029: never a number; a reminder with only a time shows its time instead."""
    written_at = START - days_ago * 24 * 60 * 60 * 1000
    screen.open(HereView(MAIL, (here(1, condition, "giocare", quiet, written_at),)))
    assert screen.lines()[2:] == ["Giocare", line]


def test_with_no_place_yet_the_card_says_so_and_lists_nothing(screen: Screen) -> None:
    screen.open(HereView(None))
    assert screen.lines() == [QUESTION, TEXTS.remind_here.no_place]
    assert screen.rows() == []
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Return)
    assert screen.asked.reminded == []


def test_with_a_place_and_no_active_reminder_the_card_says_so(screen: Screen) -> None:
    screen.open(HereView(MAIL))
    assert screen.lines() == ["Preventivi · mail.google.com", QUESTION, "Nessun promemoria attivo."]


def test_a_click_on_a_reminder_is_remind_here_in_the_place_shown_and_closes_the_card(
    screen: Screen,
) -> None:
    screen.open(VIEW)
    screen.click(screen.rows()[1])
    assert screen.asked.reminded == [(2, MAIL)]
    assert not screen.window.isVisible()


def test_up_and_down_go_round_the_reminders_and_enter_or_space_picks(screen: Screen) -> None:
    screen.open(VIEW)
    assert screen.ringed() == [False, False, False]  # none, as a menu opened by the mouse
    screen.press(Qt.Key.Key_Return)
    assert screen.asked.reminded == []
    screen.press(Qt.Key.Key_Up)
    assert screen.ringed() == [False, False, True]
    screen.press(Qt.Key.Key_Down)
    assert screen.ringed() == [True, False, False]
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Space)
    assert screen.asked.reminded == [(2, MAIL)]
    assert not screen.window.isVisible()
    screen.open(VIEW)
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Enter)
    assert screen.asked.reminded == [(2, MAIL), (3, MAIL)]


def test_esc_the_x_and_the_focus_going_elsewhere_close_the_card(
    qtbot: QtBot, screen: Screen, elsewhere: QWindow
) -> None:
    screen.open(VIEW)
    screen.press(Qt.Key.Key_Escape)
    assert not screen.window.isVisible()
    screen.open(VIEW)
    screen.click(screen.close_button())
    assert not screen.window.isVisible()
    screen.open(VIEW)
    elsewhere.show()
    elsewhere.requestActivate()
    qtbot.waitUntil(lambda: not screen.window.isVisible())
    assert screen.asked.reminded == []


def test_the_card_opens_again_with_no_reminder_marked(screen: Screen) -> None:
    screen.open(VIEW)
    screen.press(Qt.Key.Key_Down)
    screen.press(Qt.Key.Key_Escape)
    screen.open(VIEW)
    assert screen.ringed() == [False, False, False]


def test_an_answer_asked_for_the_tray_lists_row_updates_the_place_without_the_card(
    screen: Screen,
) -> None:
    screen.card.ask()
    assert screen.asked.times == 1
    screen.card.show(VIEW)
    assert not screen.window.isVisible()
    assert screen.card.property("place") == "Preventivi · mail.google.com"
    screen.card.show(HereView(None))
    assert screen.card.property("place") == ""


def test_once_shown_the_card_waits_for_the_next_opening_to_show_again(screen: Screen) -> None:
    screen.open(VIEW)
    screen.press(Qt.Key.Key_Escape)
    screen.card.ask()  # the tray list opens
    screen.card.show(VIEW)
    assert not screen.window.isVisible()


def test_a_long_list_grows_to_the_work_area_then_scrolls_to_the_reminder_the_keys_reach(
    qtbot: QtBot, screen: Screen
) -> None:
    many = tuple(
        here(n, f"quando apro il progetto {n}", f"chiudere il ticket {n}") for n in range(40, 0, -1)
    )
    screen.open(HereView(MAIL, many))
    area = QGuiApplication.primaryScreen().availableGeometry()
    qtbot.waitUntil(lambda: screen.window.height() == area.height() - TOP - MARGIN)
    screen.press(Qt.Key.Key_Up)
    last = screen.rows()[-1]
    assert accessible(last, "name") == "Chiudere il ticket 1"
    bottom = last.mapToScene(QPointF(0, last.height())).y()
    assert 0 < bottom <= screen.window.height()
    screen.press(Qt.Key.Key_Return)
    assert screen.asked.reminded == [(1, MAIL)]


def test_the_card_goes_with_the_engine_and_no_binding_reads_it_gone(
    dwm: list[tuple[object, ...]],
) -> None:
    """On quitting, Python lets go of the interface in any order: the card stays until the
    engine goes, and then none of its window's bindings reads it gone (a warning fails)."""
    look = Look(lambda: DARK)
    engine = QQmlEngine()
    look.provide(engine)
    card = RemindHere(engine, Asked(), Stacked(), Glass(look), SimulatedClock(START, ROME))
    card.show(VIEW)
    gone: list[str] = []
    card.destroyed.connect(lambda: gone.append("card"))
    del card
    gc.collect()
    assert gone == []
    del engine
    gc.collect()
    assert gone == ["card"]
