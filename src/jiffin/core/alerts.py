"""Where the open alerts are: on screen, waiting for a place, or vanished unanswered."""

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace

from jiffin.core.records import Alert

MAX_VISIBLE = 3


@dataclass(frozen=True, slots=True)
class AlertsView:
    """What the interface shows of the alerts."""

    visible: tuple[Alert, ...]
    """On screen, oldest first."""
    waiting: int
    """Alerts waiting for a place on screen."""
    unseen: tuple[Alert, ...]
    """Vanished unanswered, newest first: the top of the tray list."""

    @property
    def dot(self) -> bool:
        """The tray dot: an alert waits, or vanished and has not been seen in the list yet."""
        return self.waiting > 0 or any(alert.seen_at is None for alert in self.unseen)


class Alerts:
    """The alerts not answered yet. Methods return the alerts whose record has changed."""

    def __init__(self, unseen: Iterable[Alert] = ()) -> None:
        self._visible: list[Alert] = []
        self._waiting: deque[Alert] = deque()
        self._unseen: list[Alert] = list(unseen)

    def view(self) -> AlertsView:
        return AlertsView(tuple(self._visible), len(self._waiting), tuple(self._unseen))

    def find(self, alert_id: int) -> Alert | None:
        return next((alert for alert in self._open() if alert.id == alert_id), None)

    def of(self, reminder_id: int) -> list[Alert]:
        return [alert for alert in self._open() if alert.reminder_id == reminder_id]

    def add(self, alert: Alert, now: int) -> Alert:
        """Put a new alert on screen, or behind the others when the screen is full."""
        self._waiting.append(alert)
        shown = self._fill(now)
        return shown[0] if shown else alert

    def vanish(self, alert_id: int, now: int) -> list[Alert]:
        """An alert left the screen unanswered, and goes on top of the tray list."""
        alert = next((alert for alert in self._visible if alert.id == alert_id), None)
        if alert is None:
            return []
        self._visible.remove(alert)
        vanished = replace(alert, vanished_at=now)
        self._unseen.insert(0, vanished)
        return [vanished, *self._fill(now)]

    def close(self, alert_id: int, now: int) -> list[Alert]:
        """An alert is answered, or its reminder is gone: it leaves wherever it is."""
        self._visible = [alert for alert in self._visible if alert.id != alert_id]
        self._waiting = deque(alert for alert in self._waiting if alert.id != alert_id)
        self._unseen = [alert for alert in self._unseen if alert.id != alert_id]
        return self._fill(now)

    def see(self, now: int) -> list[Alert]:
        """The tray list shows the unseen alerts: those it shows for the first time are seen now."""
        seen = {
            alert.id: replace(alert, seen_at=now) for alert in self._unseen if alert.seen_at is None
        }
        self._unseen = [seen.get(alert.id, alert) for alert in self._unseen]
        return list(seen.values())

    def _open(self) -> Iterator[Alert]:
        yield from self._visible
        yield from self._waiting
        yield from self._unseen

    def _fill(self, now: int) -> list[Alert]:
        shown = []
        while self._waiting and len(self._visible) < MAX_VISIBLE:
            alert = replace(self._waiting.popleft(), shown_at=now)
            self._visible.append(alert)
            shown.append(alert)
        return shown
