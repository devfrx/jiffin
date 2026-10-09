from collections.abc import Callable
from datetime import UTC, date, datetime, time

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.records import Alert, Revision, Snooze
from jiffin.ui.alert import AlertSlot


def at(day: int, hour: int) -> datetime:
    """A wall-clock time of October 2026, in UTC as the clock of these tests."""
    return datetime.combine(date(2026, 10, day), time(hour), tzinfo=UTC)


def ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


FRIDAY = at(2, 10)


class Answers:
    """The answers the slot gives, in order: (what, alert id[, snooze])."""

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


def alert(
    alert_id: int = 7,
    condition: str = "quando apro Figma",
    action: str = "esportare le icone",
    perennial: bool = False,
    rings: datetime = FRIDAY,
) -> Alert:
    """An alert as `core` makes it, its reminder written on Friday at 10:00."""
    reading = read(condition, FRIDAY)
    revision = Revision(
        alert_id,
        alert_id,
        1,
        condition,
        action,
        reading.remainder,
        schedule=reading.schedule,
        written_at=ms(FRIDAY),
        perennial=perennial,
        situations=reading.situations,
    )
    context = Context("figma.exe", "Icone - Figma", None)
    return Alert(alert_id, alert_id, revision, None, context, None, ms(rings), ms(rings))


class Scene:
    """A slot, the answers it gave, and what it told its window."""

    def __init__(self) -> None:
        self.answers = Answers()
        self.left: list[AlertSlot] = []
        self.clock = SimulatedClock(ms(FRIDAY))
        self.slot = AlertSlot(self.answers, self.clock, self.left.append)
        self.told: list[str] = []
        for signal in ("presented", "holding", "undone", "leaving", "changed"):
            getattr(self.slot, signal).connect(lambda signal=signal: self.told.append(signal))

    def qml(self, name: str) -> object:
        """A property of the slot, as its windows read it."""
        return self.slot.property(name)

    def present(self, shown: Alert | None = None) -> None:
        self.slot.present(shown or alert())
        self.told.clear()


@pytest.fixture
def scene() -> Scene:
    return Scene()


def test_a_slot_shows_the_users_words_with_a_capital_to_start(scene: Scene) -> None:
    scene.slot.present(alert(condition=" quando apro Figma", action="esportare le icone "))
    assert (scene.qml("line"), scene.qml("action")) == ("Quando apro Figma", "Esportare le icone")
    assert (scene.slot.alert_id, scene.slot.free) == (7, False)
    assert not scene.qml("menuOpen")
    assert not scene.qml("paused")
    assert not scene.qml("perennial")
    assert scene.told == ["changed", "presented"]


def test_the_line_has_the_condition_without_its_time_and_the_time_apart(scene: Scene) -> None:
    scene.present(alert(condition="quando apro Claude dopo le 23", perennial=True))
    assert scene.qml("line") == "Quando apro Claude · dalle 23:00 alle 04:00"
    assert scene.qml("perennial")


def test_the_line_has_the_situations_understood_after_the_words_the_judge_checks(
    scene: Scene,
) -> None:
    """ADR-0028: they are the condition too, and say why the alert came."""
    scene.present(alert(condition="quando sono a casa e apro Steam"))
    assert scene.qml("line") == "Quando apro Steam · a casa"


def test_an_alert_with_only_a_time_names_the_day_it_rings_for(scene: Scene) -> None:
    scene.clock.advance(ms(at(3, 9)) - scene.clock.now())
    scene.present(alert(condition="alle 15", rings=at(3, 9)))
    assert scene.qml("line") == "Ieri alle 15:00"


@pytest.mark.parametrize(
    ("click", "answer"),
    [
        (AlertSlot.close, ("close", 7)),
        (AlertSlot.expire, ("vanished", 7)),
    ],
)
def test_the_x_and_the_10_seconds_answer_once_and_the_window_leaves_at_once(
    scene: Scene, click: Callable[[AlertSlot], None], answer: tuple[object, ...]
) -> None:
    scene.present()
    click(scene.slot)
    click(scene.slot)  # a second click while the window leaves
    scene.slot.done()
    scene.slot.undo()
    scene.slot.release()
    assert scene.answers.given == [answer]
    assert scene.told == ["leaving"]
    assert scene.slot.alert_id == 7, "the alert is in the slot until its window has left"


@pytest.mark.parametrize(
    ("click", "name", "answer"),
    [
        (AlertSlot.done, "Fatto", ("done", 7)),
        (AlertSlot.snoozeNextTime, "Alla prossima volta", ("snooze", 7, Snooze.NEXT_TIME)),
        (AlertSlot.snoozeQuarterHour, "Tra 15 minuti", ("snooze", 7, Snooze.QUARTER_HOUR)),
        (AlertSlot.snoozeHour, "Tra un'ora", ("snooze", 7, Snooze.HOUR)),
        (AlertSlot.snoozeTomorrow, "Domani", ("snooze", 7, Snooze.TOMORROW)),
        (AlertSlot.notHere, "Non qui", ("not_here", 7)),
    ],
)
def test_an_answer_that_changes_something_waits_under_its_name_then_goes_once(
    scene: Scene, click: Callable[[AlertSlot], None], name: str, answer: tuple[object, ...]
) -> None:
    scene.present()
    click(scene.slot)
    assert (scene.qml("held"), scene.answers.given) == (name, [])
    assert scene.told == ["changed", "holding"]
    click(scene.slot)  # a second click while it waits
    scene.slot.done()
    scene.slot.close()  # the X is hidden, and the 10 s stopped
    scene.slot.expire()
    assert scene.answers.given == []
    scene.slot.release()  # the 5 s are up
    scene.slot.release()
    scene.slot.undo()  # too late, while the window leaves
    assert scene.answers.given == [answer]
    assert scene.told == ["changed", "holding", "leaving"]
    assert scene.qml("held") == name, "the name stays while the window leaves"


def test_undo_puts_the_alert_back_and_its_10_seconds_start_again(scene: Scene) -> None:
    scene.present()
    scene.slot.undo()  # nothing waits
    scene.slot.notHere()
    scene.slot.undo()
    scene.slot.release()
    assert (scene.qml("held"), scene.answers.given) == ("", [])
    assert scene.told == ["changed", "holding", "changed", "undone"]
    scene.slot.snoozeHour()
    scene.slot.release()
    assert scene.answers.given == [("snooze", 7, Snooze.HOUR)]


def test_the_slot_is_free_again_once_the_window_has_left(scene: Scene) -> None:
    scene.present()
    scene.slot.left()  # an exit that was not asked for
    scene.slot.done()
    scene.slot.left()  # nor while the answer waits
    assert scene.left == []
    scene.slot.release()
    scene.slot.left()
    assert scene.left == [scene.slot]
    assert (scene.slot.alert_id, scene.slot.free) == (None, True)
    scene.present(alert(8))
    assert (scene.slot.alert_id, scene.qml("held")) == (8, "")


def test_a_withdrawn_alert_leaves_without_an_answer(scene: Scene) -> None:
    scene.slot.withdraw()  # nothing in the slot
    scene.present()
    scene.slot.withdraw()
    scene.slot.withdraw()
    assert scene.answers.given == []
    assert scene.told == ["leaving"]


def test_a_withdrawn_alert_takes_its_waiting_answer_away(scene: Scene) -> None:
    # Its reminder was completed or deleted from the tray list meanwhile (ADR-0030).
    scene.present()
    scene.slot.done()
    scene.slot.withdraw()
    scene.slot.release()
    assert scene.answers.given == []
    assert scene.told == ["changed", "holding", "leaving"]


def test_the_10_seconds_pause_while_the_mouse_is_over_the_alert(scene: Scene) -> None:
    scene.present()
    scene.slot.hover(True)
    assert scene.qml("paused")
    scene.slot.hover(True)
    scene.slot.hover(False)
    assert not scene.qml("paused")
    assert scene.told == ["changed", "changed"]


def test_the_10_seconds_pause_while_the_menu_is_open(scene: Scene) -> None:
    scene.present()
    scene.slot.toggleMenu()
    assert (scene.slot.menu_open, scene.qml("menuOpen"), scene.qml("paused")) == (True, True, True)
    scene.slot.toggleMenu()  # a second click on Snooze
    assert (scene.qml("menuOpen"), scene.qml("paused")) == (False, False)
    scene.slot.toggleMenu()
    scene.slot.close_menu()  # a click outside
    scene.slot.close_menu()
    assert (scene.qml("menuOpen"), scene.qml("paused")) == (False, False)
    assert scene.told == ["changed"] * 4


@pytest.mark.parametrize(
    ("condition", "offered"),
    [
        ("quando apro Figma", True),
        ("alle 15", True),
        ("stasera", False),
    ],
    ids=["no time", "a moment that comes back", "tonight"],
)
def test_the_menu_offers_alla_prossima_volta_only_with_a_next_unit(
    scene: Scene, condition: str, offered: bool
) -> None:
    scene.clock.advance(ms(at(2, 19)) - scene.clock.now())
    scene.present(alert(condition=condition, rings=at(2, 19)))
    scene.slot.toggleMenu()
    assert scene.qml("nextTime") is offered


def test_the_menu_goes_at_once_when_an_answer_waits_or_the_alert_leaves(scene: Scene) -> None:
    scene.present()
    scene.slot.toggleMenu()
    scene.told.clear()
    scene.slot.snoozeHour()
    assert not scene.slot.menu_open
    assert scene.told == ["changed", "holding"]
    scene.slot.toggleMenu()  # a click while the answer waits
    scene.slot.close_menu()
    assert not scene.slot.menu_open
    scene.slot.undo()
    scene.slot.toggleMenu()
    scene.told.clear()
    scene.slot.close()
    assert not scene.slot.menu_open
    assert scene.told == ["changed", "leaving"]
    scene.slot.toggleMenu()  # a click while the window leaves
    scene.slot.close_menu()
    assert not scene.slot.menu_open
    assert scene.told == ["changed", "leaving"]


def test_an_empty_slot_has_no_menu(scene: Scene) -> None:
    scene.slot.toggleMenu()
    assert not scene.slot.menu_open
    assert scene.told == []


def test_a_new_alert_starts_with_the_menu_closed_and_running(scene: Scene) -> None:
    scene.present()
    scene.slot.hover(True)
    scene.slot.toggleMenu()
    scene.slot.close()
    scene.slot.left()
    scene.present(alert(8))
    assert (scene.qml("menuOpen"), scene.qml("paused")) == (False, False)


def test_after_undo_the_10_seconds_still_pause_under_the_mouse(scene: Scene) -> None:
    scene.present()
    scene.slot.hover(True)
    scene.slot.done()
    scene.slot.undo()
    assert scene.qml("paused")


def test_the_mouse_over_a_hidden_window_is_ignored(scene: Scene) -> None:
    scene.slot.hover(True)  # Qt sends an enter and a leave after hide()
    assert not scene.qml("paused")
    assert scene.told == []
