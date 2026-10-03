from collections.abc import Callable

import pytest

from jiffin.core.records import Snooze
from jiffin.ui.alert import AlertSlot


class Answers:
    """The answers the slot gives, in order: (what, alert id[, snooze])."""

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


class Scene:
    """A slot, the answers it gave, and what it told its window."""

    def __init__(self) -> None:
        self.answers = Answers()
        self.left: list[AlertSlot] = []
        self.slot = AlertSlot(self.answers, self.left.append)
        self.told: list[str] = []
        for signal in ("presented", "leaving", "changed"):
            getattr(self.slot, signal).connect(lambda signal=signal: self.told.append(signal))

    def qml(self, name: str) -> object:
        """A property of the slot, as its window reads it."""
        return self.slot.property(name)

    def present(self, alert_id: int = 7) -> None:
        self.slot.present(alert_id, "quando apro Figma", "esportare le icone")
        self.told.clear()


@pytest.fixture
def scene() -> Scene:
    return Scene()


def test_a_slot_shows_the_users_words_with_a_capital_to_start(scene: Scene) -> None:
    scene.slot.present(7, " quando apro Figma", "esportare le icone ")
    assert (scene.qml("condition"), scene.qml("action")) == (
        "Quando apro Figma",
        "Esportare le icone",
    )
    assert (scene.slot.alert_id, scene.slot.free) == (7, False)
    assert scene.qml("panel") == AlertSlot.Panel.BUTTONS.value
    assert not scene.qml("paused")
    assert scene.told == ["changed", "presented"]


@pytest.mark.parametrize(
    ("click", "answer"),
    [
        (AlertSlot.done, ("done", 7)),
        (AlertSlot.useful, ("useful", 7)),
        (AlertSlot.notHere, ("not_here", 7)),
        (AlertSlot.snoozeQuarterHour, ("snooze", 7, Snooze.QUARTER_HOUR)),
        (AlertSlot.snoozeHour, ("snooze", 7, Snooze.HOUR)),
        (AlertSlot.snoozeTomorrow, ("snooze", 7, Snooze.TOMORROW)),
        (AlertSlot.expire, ("vanished", 7)),
    ],
)
def test_an_answer_is_given_once_and_the_window_leaves(
    scene: Scene, click: Callable[[AlertSlot], None], answer: tuple[object, ...]
) -> None:
    scene.present()
    click(scene.slot)
    click(scene.slot)  # a second click while the window leaves
    scene.slot.done()
    assert scene.answers.given == [answer]
    assert scene.told == ["leaving"]
    assert scene.slot.alert_id == 7, "the alert is in the slot until its window has left"


def test_the_slot_is_free_again_once_the_window_has_left(scene: Scene) -> None:
    scene.present()
    scene.slot.left()  # an exit that was not asked for
    assert scene.left == []
    scene.slot.done()
    scene.slot.left()
    assert scene.left == [scene.slot]
    assert (scene.slot.alert_id, scene.slot.free) == (None, True)
    scene.present(8)
    assert scene.slot.alert_id == 8


def test_a_withdrawn_alert_leaves_without_an_answer(scene: Scene) -> None:
    scene.slot.withdraw()  # nothing in the slot
    scene.present()
    scene.slot.withdraw()
    scene.slot.withdraw()
    assert scene.answers.given == []
    assert scene.told == ["leaving"]


def test_the_10_seconds_pause_while_the_mouse_is_over_the_alert(scene: Scene) -> None:
    scene.present()
    scene.slot.hover(True)
    assert scene.qml("paused")
    scene.slot.hover(True)
    scene.slot.hover(False)
    assert not scene.qml("paused")
    assert scene.told == ["changed", "changed"]


def test_the_10_seconds_pause_while_a_panel_is_open(scene: Scene) -> None:
    scene.present()
    scene.slot.openSnooze()
    assert (scene.qml("panel"), scene.qml("paused")) == (AlertSlot.Panel.SNOOZE.value, True)
    scene.slot.openSnooze()
    scene.slot.back()
    assert (scene.qml("panel"), scene.qml("paused")) == (AlertSlot.Panel.BUTTONS.value, False)
    scene.slot.openMore()
    assert (scene.qml("panel"), scene.qml("paused")) == (AlertSlot.Panel.MORE.value, True)
    assert scene.told == ["changed", "changed", "changed"]


def test_a_new_alert_starts_on_the_buttons_and_running(scene: Scene) -> None:
    scene.present()
    scene.slot.hover(True)
    scene.slot.openMore()
    scene.slot.done()
    scene.slot.left()
    scene.present(8)
    assert (scene.qml("panel"), scene.qml("paused")) == (AlertSlot.Panel.BUTTONS.value, False)


def test_the_mouse_over_a_hidden_window_is_ignored(scene: Scene) -> None:
    scene.slot.hover(True)  # Qt sends an enter and a leave after hide()
    assert not scene.qml("paused")
    assert scene.told == []


def test_the_panel_stays_while_the_window_leaves(scene: Scene) -> None:
    scene.present()
    scene.slot.openSnooze()
    scene.slot.snoozeHour()
    scene.slot.back()
    assert scene.qml("panel") == AlertSlot.Panel.SNOOZE.value
