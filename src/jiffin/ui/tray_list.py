"""The tray list: the pause from the tray, what keeps Jiffin from working fully, the alerts that
vanished unanswered, the active reminders and the return pause (#12, #43, #84, ADR-0010,
ADR-0024). The model file on its way is one of the first: its line shows the download or the
problem, and Details opens the first-run window.

A card on the alerts' material, at the bottom right of the screen over the tray. The tray icon
opens it, and it takes the focus; Esc, its X or a click elsewhere closes it. It drags, and opens
over the tray again (ADR-0023). While it is open, the unseen alerts it shows are seen, and those
new to it keep a dot until it closes. An unseen alert's Snooze opens the alert's menu, a window
of its own that never takes the focus: the list keeps it, and its keys move over the menu.
"""

from collections.abc import Callable
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import (
    Property,
    QElapsedTimer,
    QEnum,
    QObject,
    QPoint,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock
from jiffin.core.records import Alert, Revision, Snooze
from jiffin.core.reminders import MINUTE_MS, ActiveReminder, RemindersView
from jiffin.core.schedule import jiffin_day
from jiffin.core.units import ended, next_occasion
from jiffin.ui import catalog  # noqa: F401  # Catalog, which Texts.qml reads
from jiffin.ui.first_run import FirstRun
from jiffin.ui.glass import Glass
from jiffin.ui.preferences import Preferences
from jiffin.ui.rows import Row, Rows
from jiffin.ui.words import appeared, dated, sentence, when

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
MARGIN = 12
"""From the corner of the work area to the list, as Windows' own flyouts."""
REOPEN_MS = 500
"""A click on the tray icon first takes the focus from the open list, which closes: the click
itself, coming this soon after, does not open it again."""
REFRESH_MS = 10_000
"""How often the open list reads the clock again, for "torna tra 12 min"."""


class Commands(Protocol):
    """What the list asks of `core.Reminders`, through the worker's queue."""

    def done(self, alert_id: int) -> None: ...
    def snooze(self, alert_id: int, snooze: Snooze) -> None: ...
    def not_here(self, alert_id: int) -> None: ...
    def complete(self, reminder_id: int) -> None: ...
    def delete(self, reminder_id: int) -> None: ...
    def seen(self) -> None: ...


class Writer(Protocol):
    """The creation window, which New and Edit open."""

    def new(self) -> None: ...
    def edit(self, revision: Revision) -> None: ...


@QmlElement
@QmlUncreatable("The interface makes it.")
class TrayList(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window; the `show_` methods take what `core`, the
    context capture and the engine say."""

    @QEnum
    class Engine(Enum):
        """What the list says of the engine: app maps the supervisor's status to it (#44)."""

        WORKING = 0
        """Ready, asleep, starting, or not started yet."""
        RESTARTING = 1
        """Down after a failure: it starts again on its own."""
        FAILURES = 2
        """Stopped after four failures within an hour."""
        MODEL = 3
        """Stopped: the model cannot be loaded."""
        GPU_MEMORY = 4
        """Stopped, or asleep after a wake refused: the GPU is out of memory."""
        MISMATCH = 5
        """Stopped: the engine speaks another protocol version, which Retry cannot mend."""

    changed = Signal()
    opened = Signal()

    def __init__(
        self,
        engine: QQmlEngine,
        commands: Commands,
        writer: Writer,
        retry: Callable[[], None],
        resume: Callable[[], None],
        first_run: FirstRun,
        preferences: Preferences,
        glass: Glass,
        clock: Clock,
    ) -> None:
        # The engine owns this object, and deletes it only once the window's bindings are
        # dead, as the creation window's (#43).
        super().__init__(engine)
        self._commands = commands
        self._writer = writer
        self._retry = retry
        self._resume = resume
        self._first_run = first_run
        self._preferences = preferences
        self._glass = glass
        self._clock = clock
        self._alerts = AlertsView((), 0, ())
        self._reminders = RemindersView(())
        self._unreadable: list[str] = []
        self._engine = TrayList.Engine.WORKING
        self._paused = ("", False)
        """When the pause ends, "15:30", and whether that is tomorrow; "" while not paused."""
        self._fresh: set[int] = set()
        """The unseen alerts the open list shows for the first time: they keep their dot."""
        self._max_height = 0
        self._area_bottom = 0
        self._put_at: QPoint | None = None
        """Where the list was last put: an open list anywhere else, the user moved."""
        self._menu_for = 0
        """The unseen alert whose Snooze has its menu open; 0 for none."""
        self._next_time = True
        self._unseen = Rows("alertId", ("action", "line", "fresh"), self)
        self._active = Rows(
            "reminderId",
            (
                "action",
                "remainder",
                "when",
                "perennial",
                "endedOn",
                "returnsIn",
                "returnsAt",
                "returnsTomorrow",
                "silences",
            ),
            self,
        )
        self._closed = QElapsedTimer()
        self._refresh = QTimer(self, interval=REFRESH_MS)
        self._refresh.timeout.connect(self._fill)
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "TrayListWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties(
            {"trayList": self, "firstRun": first_run, "preferences": preferences}
        )
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no tray list window: {self._component.errorString()}")
        menu = window.property("menu")
        if not isinstance(menu, QQuickWindow):
            raise TypeError("no menu in the tray list window")
        self._window = window
        self._menu = menu
        window.heightChanged.connect(self._place)
        glass.add(int(window.winId()))
        glass.add(int(menu.winId()))

    def toggle(self) -> None:
        """The tray icon was clicked."""
        if self._window.isVisible():
            self.close()
        elif not (self._closed.isValid() and self._closed.elapsed() < REOPEN_MS):
            self._open()

    @Slot(object)
    def show_alerts(self, view: AlertsView) -> None:
        self._alerts = view
        if self._menu_for not in {alert.id for alert in view.unseen}:
            self.closeMenu()  # its alert has gone: answered elsewhere, or a newer one came
        if self._window.isVisible():
            self._see()
        self._fill()

    @Slot(object)
    def show_reminders(self, view: RemindersView) -> None:
        self._reminders = view
        self._fill()

    @Slot(object)
    def show_unreadable(self, apps: frozenset[str]) -> None:
        """The browsers whose address cannot be read, by app: "chrome.exe"."""
        self._unreadable = sorted(apps)
        self.changed.emit()

    @Slot(object)
    def show_engine(self, engine: "TrayList.Engine") -> None:
        if engine != self._engine:
            self._engine = engine
            self.changed.emit()

    @Property(QObject, notify=changed)
    def unseen(self) -> Rows:
        """The alerts that vanished unanswered, newest first."""
        return self._unseen

    @Property(QObject, notify=changed)
    def active(self) -> Rows:
        """The active reminders, newest first."""
        return self._active

    # A QStringList: a plain list reaches a QML list<string> parameter empty. Qt takes a type by
    # its name, which the stub does not know.
    @Property("QStringList", notify=changed)  # type: ignore[arg-type]
    def unreadable(self) -> list[str]:
        return self._unreadable

    @Property(int, notify=changed)
    def engine(self) -> int:
        return self._engine.value

    @Property(str, notify=changed)
    def pausedAt(self) -> str:
        """When the pause from the tray ends, "15:30"; empty while there is none (ADR-0024)."""
        return self._paused[0]

    @Property(bool, notify=changed)
    def pausedTomorrow(self) -> bool:
        return self._paused[1]

    @Property(int, notify=changed)
    def maxHeight(self) -> int:
        """As tall as the work area allows, with the margins."""
        return self._max_height

    @Property(int, notify=changed)
    def areaBottom(self) -> int:
        """Where the work area ends, on the screen: a menu that would go past it opens upwards."""
        return self._area_bottom

    @Property(int, notify=changed)
    def menuFor(self) -> int:
        """The unseen alert whose Snooze has its menu open; 0 for none."""
        return self._menu_for

    @Property(bool, notify=changed)
    def nextTime(self) -> bool:
        """Whether the open menu has Next time: the reminder has a next unit, asked of
        `core` when the menu opens (ADR-0021)."""
        return self._next_time

    @Slot()
    def new(self) -> None:
        self.close()
        self._writer.new()

    @Slot(int)
    def edit(self, reminder_id: int) -> None:
        active = self._find(reminder_id)
        if active is None:
            return
        self.close()
        self._writer.edit(active.reminder.revision)

    @Slot(int)
    def complete(self, reminder_id: int) -> None:
        self._commands.complete(reminder_id)

    @Slot(int)
    def delete(self, reminder_id: int) -> None:
        self._commands.delete(reminder_id)

    @Slot(int)
    def done(self, alert_id: int) -> None:
        self._commands.done(alert_id)

    @Slot(int)
    def toggleMenu(self, alert_id: int) -> None:
        """Snooze on an unseen alert: its menu opens, or closes on a second click."""
        if alert_id == self._menu_for:
            self.closeMenu()
            return
        alert = next((alert for alert in self._alerts.unseen if alert.id == alert_id), None)
        if alert is None:
            return
        self._menu_for = alert_id
        self._next_time = next_occasion(alert.revision, self._clock, self._clock.now())
        self.changed.emit()
        menu = self._menu
        menu.show()
        self._glass.shown(int(menu.winId()))

    @Slot()
    def closeMenu(self) -> None:
        """An answer, a second click on Snooze, a press anywhere in the list, Esc, the focus
        moving on, or the list closing."""
        if self._menu_for:
            self._menu_for = 0
            self._menu.hide()
            self.changed.emit()

    @Slot()
    def snoozeNextTime(self) -> None:
        self._answer(lambda alert_id: self._commands.snooze(alert_id, Snooze.NEXT_TIME))

    @Slot()
    def snoozeQuarterHour(self) -> None:
        self._answer(lambda alert_id: self._commands.snooze(alert_id, Snooze.QUARTER_HOUR))

    @Slot()
    def snoozeHour(self) -> None:
        self._answer(lambda alert_id: self._commands.snooze(alert_id, Snooze.HOUR))

    @Slot()
    def snoozeTomorrow(self) -> None:
        self._answer(lambda alert_id: self._commands.snooze(alert_id, Snooze.TOMORROW))

    @Slot()
    def notHere(self) -> None:
        self._answer(self._commands.not_here)

    @Slot()
    def settings(self) -> None:
        """Change, by the return pause: the settings, where it is set."""
        self.close()
        self._preferences.open()

    @Slot()
    def retry(self) -> None:
        self._retry()

    @Slot()
    def resume(self) -> None:
        """Resume, on the pause's line."""
        self._resume()

    @Slot()
    def retryModel(self) -> None:
        self._first_run.retry()

    @Slot()
    def details(self) -> None:
        """The model's line: its window, with the steps and the file by hand."""
        self.close()
        self._first_run.open()

    @Slot()
    def close(self) -> None:
        if not self._window.isVisible():
            return
        self.closeMenu()
        self._window.hide()
        self._refresh.stop()
        self._fresh = set()
        self._fill()

    @Slot()
    def deactivated(self) -> None:
        """The focus went to another window, maybe the taskbar's for a click on the tray icon:
        the list closes, and that click does not open it again."""
        if self._window.isVisible():
            self.close()
            self._closed.start()

    def _open(self) -> None:
        self._fresh = set()
        self._see()
        self._fill()
        area = QGuiApplication.primaryScreen().availableGeometry()
        self._max_height = area.height() - 2 * MARGIN
        self._area_bottom = area.y() + area.height()
        self.changed.emit()
        self.opened.emit()
        self._place()
        window = self._window
        window.show()
        self._glass.shown(int(window.winId()))
        # The click on the tray icon lets this app bring its window to the front.
        window.requestActivate()
        self._refresh.start()

    def _see(self) -> None:
        """The open list shows the unseen alerts: those it shows for the first time are seen."""
        new = {alert.id for alert in self._alerts.unseen if alert.seen_at is None} - self._fresh
        if new:
            self._fresh |= new
            self._commands.seen()

    def _fill(self) -> None:
        now = self._clock.now()
        local = self._clock.local(now)
        until = self._reminders.paused_until
        end = None if until is None else self._clock.local(until)
        paused = ("", False) if end is None else (f"{end:%H:%M}", end.date() > local.date())
        if paused != self._paused:
            self._paused = paused
            self.changed.emit()
        self._unseen.replace(
            [self._unseen_row(alert, local.date()) for alert in self._alerts.unseen]
        )
        self._active.replace(
            [self._active_row(active, now, local) for active in self._reminders.active]
        )

    def _unseen_row(self, alert: Alert, today: date) -> Row:
        at = self._clock.local(alert.created_at if alert.shown_at is None else alert.shown_at)
        return {
            "alertId": alert.id,
            "action": sentence(alert.revision.action),
            "line": appeared(alert.revision.remainder, at, today),
            "fresh": alert.id in self._fresh,
        }

    def _active_row(self, active: ActiveReminder, now: int, local: datetime) -> Row:
        """The condition without its time, and the time written for today's Jiffin day
        (ADR-0020); a period over says so (ADR-0021)."""
        reminder = active.reminder
        revision = reminder.revision
        schedule = revision.schedule
        day = jiffin_day(local)
        period = None if schedule is None else schedule.period
        until = reminder.snoozed_until
        minutes = 0 if until is None or until <= now else -(-(until - now) // MINUTE_MS)
        later = self._clock.local(until) if until is not None and minutes >= 60 else None
        return {
            "reminderId": reminder.id,
            "action": sentence(revision.action),
            "remainder": sentence(revision.remainder),
            "when": "" if schedule is None else when(schedule, revision.perennial, day),
            "perennial": revision.perennial,
            "endedOn": dated(period.last, day)
            if period is not None and ended(schedule, local)
            else "",
            "returnsIn": minutes if minutes < 60 else 0,
            "returnsAt": "" if later is None else f"{later:%H:%M}",
            "returnsTomorrow": later is not None and later.date() > local.date(),
            "silences": active.silences,
        }

    def _answer(self, answer: Callable[[int], None]) -> None:
        """An item of the open menu, for its alert; the menu closes."""
        alert_id = self._menu_for
        self.closeMenu()
        if alert_id:
            answer(alert_id)

    def _find(self, reminder_id: int) -> ActiveReminder | None:
        return next((a for a in self._reminders.active if a.reminder.id == reminder_id), None)

    def _place(self) -> None:
        """At the bottom right of the work area: a list that grows or shrinks keeps its bottom.
        One the user moved stays where they left it, with its top left corner, until it
        closes."""
        window = self._window
        if window.isVisible() and window.framePosition() != self._put_at:
            return
        area = QGuiApplication.primaryScreen().availableGeometry()
        frame = window.frameMargins()
        width = window.width() + frame.left() + frame.right()
        height = window.height() + frame.top() + frame.bottom()
        window.setFramePosition(
            QPoint(
                area.x() + area.width() - MARGIN - width,
                area.y() + area.height() - MARGIN - height,
            )
        )
        self._put_at = window.framePosition()
