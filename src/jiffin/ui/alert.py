"""One place for an alert on screen: what its window shows, and what the user answers there.

An alert enters, waits 10 s for an answer, and leaves: answered, vanished when the 10 s are up,
or withdrawn when `core` no longer shows it. Its commands are Done, Snooze, whose menu holds
the snoozes and Not here, and the X (#83, ADR-0023). The 10 s pause while the mouse is over the
alert or while the menu is open (#12). Its windows never take the focus (ADR-0009).

An answer that changes something, Done, a snooze or Not here, waits 5 s with Undo before it goes
to `core` (ADR-0030): the window shows its name and times the 5 s, then calls `release`. Undo
puts the alert back with its 10 s from the start; the X and the 10 s leave at once. A withdrawn
alert takes its waiting answer away; when the app quits, `release` sends it at once.
"""

from collections.abc import Callable
from enum import Enum, auto
from typing import Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtQml import QmlElement, QmlUncreatable

from jiffin.core.clock import Clock
from jiffin.core.records import Alert, Revision, Snooze
from jiffin.core.schedule import jiffin_day
from jiffin.core.units import instance_day, next_occasion
from jiffin.lang.texts import TEXTS
from jiffin.ui.words import alert_line, sentence

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1


class Answers(Protocol):
    """Where the answers go: `core.Reminders`' own methods, through the worker's queue."""

    def done(self, alert_id: int) -> None: ...
    def not_here(self, alert_id: int) -> None: ...
    def snooze(self, alert_id: int, snooze: Snooze) -> None: ...
    def close(self, alert_id: int) -> None: ...
    def vanished(self, alert_id: int) -> None: ...


class _State(Enum):
    EMPTY = auto()
    SHOWN = auto()
    HOLDING = auto()
    """An answer waits 5 s with Undo."""
    LEAVING = auto()


@QmlElement
@QmlUncreatable("The overlay makes the slots.")
class AlertSlot(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    changed = Signal()
    presented = Signal()
    """A new alert: the window enters and the 10 s start."""
    holding = Signal()
    """An answer waits: the 10 s stop, and the window times the 5 s, then calls `release`."""
    undone = Signal()
    """Undo: the 10 s start again from the beginning."""
    leaving = Signal()
    """The window leaves, then calls `left`."""

    def __init__(
        self, answers: Answers, clock: Clock, on_left: Callable[["AlertSlot"], None]
    ) -> None:
        super().__init__()
        self._answers = answers
        self._clock = clock
        self._on_left = on_left
        self._state = _State.EMPTY
        self._alert_id = 0
        self._revision: Revision | None = None
        self._line = ""
        self._action = ""
        self._menu = False
        self._next_time = True
        self._hovered = False
        self._held = ""
        """The waiting answer's name, until a new alert comes: it shows while the alert leaves."""
        self._waiting: Callable[[int], None] | None = None
        """The waiting answer, until it goes, is undone or is taken away."""

    @property
    def alert_id(self) -> int | None:
        """The alert in the slot, until its window has left."""
        return None if self._state == _State.EMPTY else self._alert_id

    @property
    def free(self) -> bool:
        return self._state == _State.EMPTY

    @property
    def menu_open(self) -> bool:
        """Snooze's menu is open, until an answer, a second click on Snooze, a click outside it
        and its alert, or the alert leaving."""
        return self._menu

    def present(self, alert: Alert) -> None:
        assert self.free, "an alert is still in this slot"
        revision = alert.revision
        today = jiffin_day(self._clock.local(self._clock.now()))
        day = instance_day(revision, self._clock, alert.created_at)
        self._state = _State.SHOWN
        self._alert_id = alert.id
        self._revision = revision
        self._line = alert_line(revision.remainder, revision.schedule, day, today)
        self._action = sentence(revision.action)
        self._hovered = False
        self._held = ""
        self.changed.emit()
        self.presented.emit()

    def withdraw(self) -> None:
        """`core` no longer shows the alert: it leaves without an answer, also one waiting, since
        its reminder was completed or deleted meanwhile (ADR-0030)."""
        if self._state in (_State.SHOWN, _State.HOLDING):
            self._waiting = None
            self._leave()

    def close_menu(self) -> None:
        """A click outside the menu and its alert, or another alert's menu opening."""
        if self._menu:
            self._menu = False
            self.changed.emit()

    @Property(str, notify=changed)
    def line(self) -> str:
        """The user's "Quando…" without its time, and the time understood (#84): it says why the
        alert came (ADR-0010)."""
        return self._line

    @Property(str, notify=changed)
    def action(self) -> str:
        return self._action

    @Property(bool, notify=changed)
    def perennial(self) -> bool:
        """ "Ogni volta": Done means "done this time", and the icon says it (#83)."""
        return self._revision is not None and self._revision.perennial

    @Property(str, notify=changed)
    def held(self) -> str:
        """The answer waiting with Undo, by its name: "Fatto", "Tra 15 minuti"; empty when
        none."""
        return self._held

    @Property(bool, notify=changed)
    def menuOpen(self) -> bool:
        return self._menu

    @Property(bool, notify=changed)
    def nextTime(self) -> bool:
        """Whether the menu has Next time: the reminder has a next unit, asked of
        `core` when the menu opens (ADR-0021)."""
        return self._next_time

    @Property(bool, notify=changed)
    def paused(self) -> bool:
        return self._hovered or self._menu

    @Slot(bool)
    def hover(self, hovered: bool) -> None:
        # Qt sends an enter and a leave after hide(): a hidden window has no mouse over it.
        if self._state == _State.EMPTY or hovered == self._hovered:
            return
        self._hovered = hovered
        self.changed.emit()

    @Slot()
    def toggleMenu(self) -> None:
        """Snooze: its menu opens, or closes on a second click."""
        if self._state != _State.SHOWN or self._revision is None:
            return
        if not self._menu:
            self._next_time = next_occasion(self._revision, self._clock, self._clock.now())
        self._menu = not self._menu
        self.changed.emit()

    @Slot()
    def done(self) -> None:
        self._hold(TEXTS.alert.done, self._answers.done)

    @Slot()
    def snoozeNextTime(self) -> None:
        self._hold(
            TEXTS.snooze.next_time,
            lambda alert_id: self._answers.snooze(alert_id, Snooze.NEXT_TIME),
        )

    @Slot()
    def snoozeQuarterHour(self) -> None:
        self._hold(
            TEXTS.snooze.quarter_hour,
            lambda alert_id: self._answers.snooze(alert_id, Snooze.QUARTER_HOUR),
        )

    @Slot()
    def snoozeHour(self) -> None:
        self._hold(TEXTS.snooze.hour, lambda alert_id: self._answers.snooze(alert_id, Snooze.HOUR))

    @Slot()
    def snoozeTomorrow(self) -> None:
        self._hold(
            TEXTS.snooze.tomorrow,
            lambda alert_id: self._answers.snooze(alert_id, Snooze.TOMORROW),
        )

    @Slot()
    def notHere(self) -> None:
        self._hold(TEXTS.alert.not_here, self._answers.not_here)

    @Slot()
    def undo(self) -> None:
        """Undo: the waiting answer does not go, and the alert is back as it was."""
        if self._state != _State.HOLDING:
            return
        self._state = _State.SHOWN
        self._held = ""
        self._waiting = None
        self.changed.emit()
        self.undone.emit()

    @Slot()
    def release(self) -> None:
        """The 5 s are up, or the app quits: the waiting answer goes to `core`, and the alert
        leaves."""
        answer = self._waiting
        if self._state != _State.HOLDING or answer is None:
            return
        self._waiting = None
        answer(self._alert_id)
        self._leave()

    @Slot()
    def close(self) -> None:
        """The X: the user saw the alert and gives no answer (ADR-0021), so it leaves at once."""
        self._answer(self._answers.close)

    @Slot()
    def expire(self) -> None:
        """The 10 s are up."""
        self._answer(self._answers.vanished)

    @Slot()
    def left(self) -> None:
        """The window has played its exit."""
        if self._state != _State.LEAVING:
            return
        self._state = _State.EMPTY
        self._hovered = False
        self._on_left(self)

    def _answer(self, answer: Callable[[int], None]) -> None:
        if self._state != _State.SHOWN:  # a second click while it waits or leaves
            return
        answer(self._alert_id)
        self._leave()

    def _hold(self, name: str, answer: Callable[[int], None]) -> None:
        """The answer waits 5 s with Undo, under its name; the menu goes at once."""
        if self._state != _State.SHOWN:
            return
        self._state = _State.HOLDING
        self._held = name
        self._waiting = answer
        self._menu = False
        self.changed.emit()
        self.holding.emit()

    def _leave(self) -> None:
        """The menu goes at once; the alert plays its exit."""
        self._state = _State.LEAVING
        if self._menu:
            self._menu = False
            self.changed.emit()
        self.leaving.emit()
