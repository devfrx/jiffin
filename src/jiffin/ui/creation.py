"""The creation window: a new reminder, or one being edited (#12, #43, #101).

A card like the alerts, with two boxes, "Quando" and "Ricordami di", the "Ogni volta" box, the
sentence they make, and Save and Cancel. The shortcut and the tray list open it; it shows at the
centre of the screen, or where the user left it (ADR-0023), and takes the focus, and saving or
cancelling hides it, as its X does. The texts go to `core` as written, with their spaces tidied:
the judge gets exactly the "Quando" box (#12).

The time and the situations of the condition are read at every key (ADR-0020, ADR-0028): the
lines under "Quando" show what Jiffin understood, each situation on its own, and name the words
it did not; a time already over turns Save off (#84, #90). Words of a recurrence tick "Ogni
volta" by themselves while the user has not touched it (#92). Edit keeps the saved time and
situations while the condition is unchanged, as `core` does.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.clock import Clock
from jiffin.core.meanings import read
from jiffin.core.records import Revision
from jiffin.core.schedule import Schedule, jiffin_day
from jiffin.core.situations import Term
from jiffin.ui import catalog  # noqa: F401  # Catalog, which Texts.qml reads
from jiffin.ui.glass import Glass
from jiffin.ui.places import Places
from jiffin.ui.words import passed, sentence, situation_lines, tidy, when

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
_ENDINGS = " .!?…;:,"
"""Left off the end of the action in the sentence, which ends with a full stop."""


class Changes(Protocol):
    """Where the changes go: `core.Reminders`' own methods, through the worker's queue."""

    def create(self, condition: str, action: str, perennial: bool) -> None: ...
    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None: ...


@QmlElement
@QmlUncreatable("The interface makes it.")
class Creation(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window."""

    changed = Signal()
    opened = Signal(str, str)
    """Another reminder to show, with its condition and action: the boxes take them, and the
    first one the focus."""

    def __init__(
        self, engine: QQmlEngine, changes: Changes, glass: Glass, places: Places, clock: Clock
    ) -> None:
        # The engine owns this object, and deletes it only once the window's bindings are
        # dead: whatever Python lets go of first on quitting, none of them reads it gone.
        super().__init__(engine)
        self._changes = changes
        self._glass = glass
        self._clock = clock
        self._saved: Revision | None = None
        """The revision being edited; None for a new reminder."""
        self._condition = ""
        self._action = ""
        self._perennial = False
        self._recurring = False
        """The condition has words that tick "Ogni volta" (#92)."""
        self._ticked = False
        """Those words ticked "Ogni volta": they untick it when they go, if it is untouched."""
        self._touched = False
        """The user ticked or unticked "Ogni volta": words no longer move it."""
        self._schedule: Schedule | None = None
        self._situations: tuple[Term, ...] = ()
        self._unclear: list[str] = []
        self._time_unclear = False
        self._past = False
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "CreationWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"creation": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no creation window: {self._component.errorString()}")
        self._window = window
        # It grows while the user types: it never moves for that, centred or not.
        self._place = places.follow("creation", window)
        glass.add(int(window.winId()))

    def new(self) -> None:
        """A blank reminder; one already being written stays as it is."""
        if not (self._window.isVisible() and self._saved is None):
            self._open(None, "", "")
        self._present()

    def edit(self, revision: Revision) -> None:
        """A reminder's current revision: its texts, its "Ogni volta" and its saved time."""
        saved = self._saved
        if not (
            self._window.isVisible()
            and saved is not None
            and saved.reminder_id == revision.reminder_id
        ):
            self._open(revision, revision.condition, revision.action)
        self._present()

    @Property(bool, notify=changed)
    def editing(self) -> bool:
        return self._saved is not None

    @Property(str, notify=changed)
    def conditionSentence(self) -> str:
        return sentence(tidy(self._condition))

    @Property(str, notify=changed)
    def actionWords(self) -> str:
        return tidy(self._action).rstrip(_ENDINGS)

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        """Both boxes are written."""
        return self._ready()

    @Property(str, notify=changed)
    def whenLine(self) -> str:
        """The time understood, written for today; empty without one."""
        if self._schedule is None:
            return ""
        return when(self._schedule, self._perennial, jiffin_day(self._now()))

    @Property("QVariantList", notify=changed)  # type: ignore[arg-type]
    def situations(self) -> list[dict[str, str]]:
        """The situations understood, each on its line with what its icon goes by; none without
        any."""
        return situation_lines(self._situations)

    # A QStringList, as the tray list's browsers: Qt takes a type by its name, which the stub does
    # not know.
    @Property("QStringList", notify=changed)  # type: ignore[arg-type]
    def unclearWords(self) -> list[str]:
        """The words not understood, as written: those of a time, and the reminder saves without
        a time; or those of situations only, and it saves without them."""
        return self._unclear

    @Property(bool, notify=changed)
    def timeUnclear(self) -> bool:
        """Words of the time are among those not understood: it rings at any time."""
        return self._time_unclear

    @Property(bool, notify=changed)
    def past(self) -> bool:
        """The time is over already: Save stays off."""
        return self._past

    @Property(str, notify=changed)
    def pastWhen(self) -> str:
        """The time over, short: "Oggi alle 09:00"."""
        if not self._past or self._schedule is None:
            return ""
        return passed(self._schedule, jiffin_day(self._now()))

    @Property(bool, notify=changed)
    def perennial(self) -> bool:
        """ "Ogni volta"."""
        return self._perennial

    @Slot(str)
    def setCondition(self, text: str) -> None:
        if text != self._condition:
            self._condition = text
            self._read()
            self.changed.emit()

    @Slot(str)
    def setAction(self, text: str) -> None:
        if text != self._action:
            self._action = text
            self.changed.emit()

    @Slot()
    def togglePerennial(self) -> None:
        self._perennial = not self._perennial
        self._touched = True
        self.changed.emit()

    @Slot()
    def save(self) -> None:
        if not self._ready():
            return
        # The clock moves while the window is open: a time may be over by now.
        self._read()
        if self._past:
            self.changed.emit()
            return
        condition, action = tidy(self._condition), tidy(self._action)
        if self._saved is None:
            self._changes.create(condition, action, self._perennial)
        else:
            self._changes.edit(self._saved.reminder_id, condition, action, self._perennial)
        self._window.hide()

    @Slot()
    def cancel(self) -> None:
        self._window.hide()

    def _ready(self) -> bool:
        return bool(tidy(self._condition)) and bool(tidy(self._action))

    def _now(self) -> datetime:
        return self._clock.local(self._clock.now())

    def _read(self, *, follow: bool = True) -> None:
        """What the condition says of its time and its situations, now. A saved condition keeps
        its saved time and situations while it is unchanged (ADR-0020), never over: only its
        words not understood are found again, those of situations whatever the day, since a
        situation's reading never hangs on it."""
        condition = tidy(self._condition)
        reading = read(condition, self._now())
        if follow:
            self._follow(reading.recurring)
        else:
            self._recurring = reading.recurring
        saved = self._saved
        unclear, time_unclear = reading.unclear, reading.time_unclear
        if saved is not None and condition == saved.condition:
            self._schedule, self._past = saved.schedule, False
            self._situations = saved.situations
            if saved.schedule is not None and time_unclear:
                unclear, time_unclear = (), False  # today does not read the time it kept
        else:
            self._schedule, self._past = reading.schedule, reading.past
            self._situations = reading.situations
        self._unclear = [condition[start:end] for start, end in unclear]
        self._time_unclear = time_unclear

    def _follow(self, recurring: bool) -> None:
        """ "Ogni volta" ticks itself when words of a recurrence appear, and goes when they go, as
        long as the user has not touched it (#92)."""
        if recurring != self._recurring and not self._touched:
            if recurring and not self._perennial:
                self._perennial = self._ticked = True
            elif not recurring and self._ticked:
                self._perennial = self._ticked = False
        self._recurring = recurring

    def _open(self, saved: Revision | None, condition: str, action: str) -> None:
        self._saved = saved
        self._condition, self._action = condition, action
        self._perennial = saved is not None and saved.perennial
        self._ticked = self._touched = False
        # The words there when the window opens never move the box: Edit shows it as it was.
        self._read(follow=False)
        self.changed.emit()
        self.opened.emit(condition, action)

    def _present(self) -> None:
        """An open window comes to the front where it is."""
        window = self._window
        if not window.isVisible():
            self._place.open()
        window.show()
        self._glass.shown(int(window.winId()))
        # On Windows, activating the window also brings it to the front.
        window.requestActivate()
