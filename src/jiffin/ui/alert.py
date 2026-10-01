"""One place for an alert on screen: what its window shows, and what the user answers there.

An alert enters, waits 10 s for an answer, and leaves: answered, vanished when the 10 s are up,
or withdrawn when `core` no longer shows it. The 10 s pause while the mouse is over the alert or
while one of its panels is open (#12). Its window never takes the focus (ADR-0009).
"""

from collections.abc import Callable
from enum import Enum, auto
from typing import Protocol

from PySide6.QtCore import Property, QEnum, QObject, Signal, Slot
from PySide6.QtQml import QmlElement, QmlUncreatable

from jiffin.core.reminders import Snooze
from jiffin.ui.words import sentence

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1


class Answers(Protocol):
    """Where the answers go: `core.Reminders`' own methods, through the worker's queue."""

    def done(self, alert_id: int) -> None: ...
    def useful(self, alert_id: int) -> None: ...
    def not_here(self, alert_id: int) -> None: ...
    def snooze(self, alert_id: int, snooze: Snooze) -> None: ...
    def vanished(self, alert_id: int) -> None: ...


class _State(Enum):
    EMPTY = auto()
    SHOWN = auto()
    LEAVING = auto()


@QmlElement
@QmlUncreatable("The overlay makes the slots.")
class AlertSlot(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    @QEnum
    class Panel(Enum):
        BUTTONS = 0
        """Fatto, Rimanda and "…"."""
        SNOOZE = 1
        """Indietro, 15 min, 1 ora and Domani."""
        MORE = 2
        """Indietro, Utile and Non qui."""

    changed = Signal()
    presented = Signal()
    """A new alert: the window enters and the 10 s start."""
    leaving = Signal()
    """The window leaves, then calls `left`."""

    def __init__(self, answers: Answers, on_left: Callable[["AlertSlot"], None]) -> None:
        super().__init__()
        self._answers = answers
        self._on_left = on_left
        self._state = _State.EMPTY
        self._alert_id = 0
        self._condition = ""
        self._action = ""
        self._panel = AlertSlot.Panel.BUTTONS
        self._hovered = False

    @property
    def alert_id(self) -> int | None:
        """The alert in the slot, until its window has left."""
        return None if self._state == _State.EMPTY else self._alert_id

    @property
    def free(self) -> bool:
        return self._state == _State.EMPTY

    def present(self, alert_id: int, condition: str, action: str) -> None:
        assert self.free, "an alert is still in this slot"
        self._state = _State.SHOWN
        self._alert_id = alert_id
        self._condition = sentence(condition)
        self._action = sentence(action)
        self._panel = AlertSlot.Panel.BUTTONS
        self._hovered = False
        self.changed.emit()
        self.presented.emit()

    def withdraw(self) -> None:
        """`core` no longer shows the alert: it leaves without an answer."""
        if self._state == _State.SHOWN:
            self._leave()

    @Property(str, notify=changed)
    def condition(self) -> str:
        """The user's "Quando…", so it is clear why the alert came (ADR-0010)."""
        return self._condition

    @Property(str, notify=changed)
    def action(self) -> str:
        return self._action

    @Property(int, notify=changed)
    def panel(self) -> int:
        return self._panel.value

    @Property(bool, notify=changed)
    def paused(self) -> bool:
        return self._hovered or self._panel != AlertSlot.Panel.BUTTONS

    @Slot(bool)
    def hover(self, hovered: bool) -> None:
        # Qt sends an enter and a leave after hide(): a hidden window has no mouse over it.
        if self._state == _State.EMPTY or hovered == self._hovered:
            return
        self._hovered = hovered
        self.changed.emit()

    @Slot()
    def openSnooze(self) -> None:
        self._open(AlertSlot.Panel.SNOOZE)

    @Slot()
    def openMore(self) -> None:
        self._open(AlertSlot.Panel.MORE)

    @Slot()
    def back(self) -> None:
        self._open(AlertSlot.Panel.BUTTONS)

    @Slot()
    def done(self) -> None:
        self._answer(self._answers.done)

    @Slot()
    def useful(self) -> None:
        self._answer(self._answers.useful)

    @Slot()
    def notHere(self) -> None:
        self._answer(self._answers.not_here)

    @Slot()
    def snoozeQuarterHour(self) -> None:
        self._answer(lambda alert_id: self._answers.snooze(alert_id, Snooze.QUARTER_HOUR))

    @Slot()
    def snoozeHour(self) -> None:
        self._answer(lambda alert_id: self._answers.snooze(alert_id, Snooze.HOUR))

    @Slot()
    def snoozeTomorrow(self) -> None:
        self._answer(lambda alert_id: self._answers.snooze(alert_id, Snooze.TOMORROW))

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

    def _open(self, panel: "AlertSlot.Panel") -> None:
        if self._state == _State.SHOWN and panel != self._panel:
            self._panel = panel
            self.changed.emit()

    def _answer(self, answer: Callable[[int], None]) -> None:
        if self._state != _State.SHOWN:  # a second click while it leaves
            return
        answer(self._alert_id)
        self._leave()

    def _leave(self) -> None:
        self._state = _State.LEAVING
        self.leaving.emit()
