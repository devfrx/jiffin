"""The card of Remind here, "qui dovevi avvisarmi" (ADR-0029): Win+Shift+Q, or the row at the top
of the tray list, opens it on the last place Jiffin judged, with the active reminders in their
order there; a click on one is Remind here, and its alert comes at once.

A card at the top centre, where the alerts come, drawn like one: the overlay holds the alerts on
screen under it while it shows. Unlike an alert it takes the focus, since the user asked for it:
Up and Down move over the reminders, Enter or Space choose, and Esc, its X or a click elsewhere
close it; Windows then gives the focus back to the window before. The user opens it, so screen
capture sees it, as the tray list (ADR-0024).

`core` says what the card shows when asked, through the worker's queue: the card shows once the
answer comes, after the turn the worker is in.
"""

from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.records import Outcome
from jiffin.core.reminders import HereReminder, HereView
from jiffin.core.schedule import jiffin_day
from jiffin.core.units import ended
from jiffin.lang.texts import TEXTS
from jiffin.ui import catalog  # noqa: F401  # Catalog, which Texts.qml reads
from jiffin.ui.glass import Glass
from jiffin.ui.overlay import TOP
from jiffin.ui.rows import Row, Rows
from jiffin.ui.words import place, sentence, when

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
MARGIN = 12
"""From the card to the end of the work area, when it grows that far."""
QUIET = {
    Outcome.OUTSIDE_SITUATION: TEXTS.remind_here.outside_situation,
    Outcome.SILENCED: TEXTS.remind_here.silenced,
    Outcome.SNOOZED: TEXTS.remind_here.snoozed,
    Outcome.SAME_OCCASION: TEXTS.remind_here.same_occasion,
}
"""What else kept a reminder quiet in the place, after its condition; out of its time, the
period over says so apart."""


class Requests(Protocol):
    """What the card asks of `core.Reminders`, through the worker's queue."""

    def here(self) -> None:
        """What the card shows: the answer comes to the interface's `show_here`."""
        ...

    def remind_here(self, reminder_id: int, context: Context) -> None: ...


class Stack(Protocol):
    """The overlay, which holds the card over the alerts."""

    def above(self, window: QQuickWindow) -> None: ...
    def layout(self) -> None: ...


@QmlElement
@QmlUncreatable("The interface makes it.")
class RemindHere(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window; `show` takes what `core` answers."""

    changed = Signal()
    opened = Signal()
    """The card shows: no reminder is the keyboard's yet, and the list is at its top."""

    def __init__(
        self,
        engine: QQmlEngine,
        requests: Requests,
        overlay: Stack,
        glass: Glass,
        clock: Clock,
    ) -> None:
        # The engine owns this object, and deletes it only once the window's bindings are
        # dead, as the creation window's (#43).
        super().__init__(engine)
        self._requests = requests
        self._overlay = overlay
        self._glass = glass
        self._clock = clock
        self._view = HereView(None)
        self._opening = False
        """The card was asked for: it shows when `core` answers."""
        self._max_height = 0
        self._rows = Rows("reminderId", ("action", "line"), self)
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "RemindHereWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"remindHere": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no card of Remind here: {self._component.errorString()}")
        self._window = window
        glass.add(int(window.winId()))
        overlay.above(window)

    def open(self) -> None:
        """Win+Shift+Q, or the tray list's row: the card shows once `core` says what it holds."""
        self._opening = True
        self._requests.here()

    def ask(self) -> None:
        """The place again, for the tray list's row, without the card."""
        self._requests.here()

    @Slot(object)
    def show(self, view: HereView) -> None:
        self._view = view
        local = self._clock.local(self._clock.now())
        self._rows.replace([self._row(reminder, local) for reminder in view.reminders])
        self.changed.emit()
        if self._opening:
            self._opening = False
            self._present()

    @Property(str, notify=changed)
    def place(self) -> str:
        """The place's line, "Preventivi · mail.google.com"; empty with no place yet."""
        return "" if self._view.place is None else place(self._view.place)

    @Property(QObject, notify=changed)
    def reminders(self) -> Rows:
        """The active reminders, in their order in the place."""
        return self._rows

    @Property(int, notify=changed)
    def maxHeight(self) -> int:
        """As tall as the work area allows under the top of the alerts, with the margin."""
        return self._max_height

    @Slot(int)
    def pick(self, index: int) -> None:
        """A click on a reminder, or Enter on the one the keyboard is on, by its place in the
        list: Remind here, in the place the card shows."""
        view = self._view
        self.close()
        if view.place is not None and 0 <= index < len(view.reminders):
            self._requests.remind_here(view.reminders[index].reminder.id, view.place)

    @Slot()
    def close(self) -> None:
        """Esc, the X, a pick, or the focus going to another window: the alerts move up."""
        self._window.hide()

    def _present(self) -> None:
        area = QGuiApplication.primaryScreen().availableGeometry()
        self._max_height = area.height() - TOP - MARGIN
        self.changed.emit()
        self.opened.emit()
        self._overlay.layout()
        window = self._window
        window.show()
        self._glass.shown(int(window.winId()))
        # The keys, or the click on the tray list, let this app bring its window to the front.
        window.requestActivate()

    def _row(self, here: HereReminder, local: datetime) -> Row:
        """The reminder's action, then its condition without the time, or the time for one with
        only a time, and what else kept it quiet there."""
        revision = here.reminder.revision
        schedule = revision.schedule
        condition = (
            when(schedule, revision.perennial, jiffin_day(local))
            if schedule is not None and not revision.remainder
            else sentence(revision.remainder)
        )
        parts = (condition, _quiet(here, local))
        return {
            "reminderId": here.reminder.id,
            "action": sentence(revision.action),
            "line": TEXTS.format.parts.join(part for part in parts if part),
        }


def _quiet(here: HereReminder, local: datetime) -> str:
    if here.quiet is Outcome.OUTSIDE_TIME:
        over = ended(here.reminder.revision.schedule, local)
        return TEXTS.remind_here.period_over if over else TEXTS.remind_here.outside_time
    return "" if here.quiet is None else QUIET.get(here.quiet, "")
