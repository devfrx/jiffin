"""The worker thread: it owns `core`, the store and the engine's supervisor, and takes one event at
a time from its queue: the contexts, the interface's commands, the model file, and the deadlines
(ADR-0012). `core` has no locks, and the database has one connection, on this thread.

The other threads put commands on the queue: functions the worker runs. After each one it
handles whatever deadline has come, the engine's restart or sleep, the debounce, a snooze or
the daily cleanup, tells the engine what `core` needs of it now (ADR-0027), and saves what
`core` changed.
"""

import logging
import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from jiffin.client.supervisor import State, Status, Supervisor
from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock
from jiffin.core.context import Observation
from jiffin.core.records import Snooze
from jiffin.core.reminders import (
    LONGEST_RETURN_PAUSE_MS,
    RETURN_PAUSE_MS,
    SHORTEST_RETURN_PAUSE_MS,
    Pause,
    Reminders,
    RemindersView,
)
from jiffin.core.situations import Situation, SituationObservation
from jiffin.store.store import Json, Store

log = logging.getLogger(__name__)

CLEANUP_EVERY_MS = 24 * 60 * 60 * 1000
"""The cleanup runs at the start, then once a day (ADR-0013)."""
LONGEST_WAIT_S = 3600.0
"""The worker reads the clock at least once an hour, so that a clock set back, by hand or after
a flat CMOS battery, cannot hold its deadlines back for longer."""
MATERIAL = "material"
"""The setting that keeps the material of the alerts and the tray list, as its letter."""
PLACES = "places"
"""The setting that keeps where the user left the windows, by name: `{"creation": [x, y]}`
(ADR-0023)."""
RETURN_PAUSE = "return_pause"
"""The setting that keeps the return pause, in seconds (ADR-0021)."""
PAUSED_UNTIL = "paused_until"
"""The setting that keeps when the pause from the tray ends, in UTC milliseconds; null once
Resume ends it (ADR-0024)."""

type Command = Callable[[], object]
"""What it returns is dropped."""


@dataclass(frozen=True, slots=True)
class Kept:
    """What the settings keep for the interface, to put on before any window shows."""

    material: str | None
    """The material's letter, if one was chosen."""
    places: dict[str, tuple[int, int]]
    return_pause: int
    """In seconds: the one kept, or the default."""


class Source(Protocol):
    """The adapter of the context port: `platform.capture.Capture` in the app."""

    def start(self) -> None: ...
    def close(self) -> None: ...


def _wake() -> None:
    """No command: the worker woke for a deadline, or for an engine whose output ended."""


def _places(kept: Json) -> dict[str, tuple[int, int]]:
    """The places as `keep_places` kept them; anything else, from a later version after a
    downgrade, is left out: that window opens at the centre."""
    if not isinstance(kept, dict):
        return {}
    return {
        name: (place[0], place[1])
        for name, place in kept.items()
        if isinstance(place, list)
        and len(place) == 2
        and isinstance(place[0], int)
        and isinstance(place[1], int)
    }


def _return_pause(kept: Json) -> int:
    """The return pause as `keep_return_pause` kept it, in milliseconds; the default when there
    is none, or when it is not whole seconds within the range of the settings."""
    if isinstance(kept, int) and SHORTEST_RETURN_PAUSE_MS <= kept * 1000 <= LONGEST_RETURN_PAUSE_MS:
        return kept * 1000
    return RETURN_PAUSE_MS


def _paused_until(kept: Json, now: int) -> int | None:
    """The end of the pause as `pause` kept it, while it is still ahead; None once it is over,
    when there is none, or when it is not an instant."""
    if isinstance(kept, int) and kept > now:
        return kept
    return None


class Worker:
    """Make it on the interface thread. `start` opens the database on the worker thread, which
    then runs until `close`; any other method may be called from any thread, and only puts a
    command on the queue.

    `on_alerts` and `on_reminders` are `core`'s, and `on_engine` gets the supervisor's status: all
    three are called on the worker thread, and should only pass on what they get. `capture` makes
    the context source, given where its observations go; it starts with the worker, before the
    engine, so that a reminder with only a time rings while the model downloads (ADR-0021).
    """

    _store: Store
    _core: Reminders
    """Both made on the worker thread, before it runs any command."""

    def __init__(
        self,
        clock: Clock,
        database: Path,
        model: Path,
        model_sha256: str,
        on_alerts: Callable[[AlertsView], None],
        on_reminders: Callable[[RemindersView], None],
        on_engine: Callable[[Status], None],
        capture: Callable[[Callable[[Observation | SituationObservation], None]], Source],
        *,
        engine: Sequence[str] | None = None,
    ) -> None:
        self._clock = clock
        self._database = database
        self._on_alerts = on_alerts
        self._on_reminders = on_reminders
        self._on_engine = on_engine
        self._queue: queue.SimpleQueue[Command | None] = queue.SimpleQueue()
        """None closes the worker."""
        self._engine = Status(State.OFF)
        """The supervisor's last status."""
        self._supervisor = Supervisor(
            model, model_sha256, clock, self._status, self._exited, command=engine
        )
        self._capture = capture(self.observe)
        self._cleanup_at = 0
        self._opened: Future[Kept] = Future()
        # A daemon, so that an interface thread that fails cannot leave the process running.
        self._thread = threading.Thread(target=self._run, name="worker", daemon=True)

    def start(self) -> Kept:
        """Open the database, migrated and cleaned up, and go on from what it holds; return what
        the settings keep for the interface. Raise what opening raised: without its database the
        app cannot go on."""
        self._thread.start()
        return self._opened.result()

    def close(self) -> None:
        """The context capture ends, the engine shuts down, and the database closes with a last
        checkpoint (ADR-0011, ADR-0013). From the interface thread, once Qt has quit."""
        if self._thread.is_alive():
            self._queue.put(None)
            self._thread.join()

    # Commands, from any thread

    def command(self, command: Callable[[Reminders], object]) -> None:
        """Run `command` on `core`."""
        self._queue.put(lambda: command(self._core))

    def observe(self, observation: Observation | SituationObservation) -> None:
        """What the context capture saw: the window in front, or a situation."""
        self.command(lambda core: core.observe(observation))

    def model_ready(self) -> None:
        """The model file is checked: the engine starts."""
        self._queue.put(self._supervisor.start)

    def restart_engine(self) -> None:
        """Retry, on the engine's trouble."""
        self._queue.put(self._supervisor.start)

    def keep_material(self, material: str) -> None:
        self._queue.put(lambda: self._store.set_setting(MATERIAL, material))

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        kept: dict[str, Json] = {name: [x, y] for name, (x, y) in places.items()}
        self._queue.put(lambda: self._store.set_setting(PLACES, kept))

    def keep_return_pause(self, seconds: int) -> None:
        """The return pause chosen in the settings: kept for the next start, and in force at
        once (ADR-0021)."""

        def keep() -> None:
            self._store.set_setting(RETURN_PAUSE, seconds)
            self._core.return_pause = seconds * 1000

        self._queue.put(keep)

    def pause(self, pause: Pause) -> None:
        """Pause, from the tray: in force at once, and kept until it ends, through a restart
        (ADR-0024)."""
        self._queue.put(lambda: self._store.set_setting(PAUSED_UNTIL, self._core.pause(pause)))

    def resume(self) -> None:
        """Resume, from the tray or its list."""

        def resume() -> None:
            self._core.resume()
            self._store.set_setting(PAUSED_UNTIL, None)

        self._queue.put(resume)

    # On the worker thread

    def _run(self) -> None:
        try:
            kept = self._open()
        except BaseException as error:  # noqa: BLE001  # start() raises it on the interface thread
            self._opened.set_exception(error)
            return
        self._opened.set_result(kept)
        try:
            self._capture.start()
        except Exception:
            log.exception("the context capture cannot start")
        command: Command | None = _wake  # the first turn shows what the database held
        while command is not None:
            self._turn(command)
            try:
                command = self._queue.get(timeout=self._wait())
            except queue.Empty:
                command = _wake
        self._shut()

    def _open(self) -> Kept:
        self._store = Store.open(self._database)
        try:
            now = self._clock.now()
            self._store.cleanup(now)
            self._cleanup_at = now + CLEANUP_EVERY_MS
            return_pause = _return_pause(self._store.setting(RETURN_PAUSE))
            self._core = Reminders(
                self._supervisor,
                self._clock,
                self._on_alerts,
                self._on_reminders,
                self._store.load(),
                return_pause=return_pause,
                paused_until=_paused_until(self._store.setting(PAUSED_UNTIL), now),
            )
            material = self._store.setting(MATERIAL)
            places = self._store.setting(PLACES)
        except BaseException:
            self._store.close()
            raise
        return Kept(
            material if isinstance(material, str) else None, _places(places), return_pause // 1000
        )

    def _turn(self, command: Command) -> None:
        """One command, then whatever deadline has come, and what `core` needs of the engine
        now; then what `core` changed is saved. A failure is logged, and the worker goes on with
        the next command."""
        try:
            command()
            self._due()
            self._supervisor.need(self._core.need)
        except Exception:
            log.exception("the worker failed")
        self._save()

    def _save(self) -> None:
        records = [*self._core.take_records(), *self._supervisor.take_records()]
        if records:
            try:
                self._store.save(records)
            except Exception:
                log.exception("%d records could not be saved", len(records))

    def _due(self) -> None:
        self._supervisor.poll()
        self._core.poll()
        now = self._clock.now()
        if now >= self._cleanup_at:
            self._store.cleanup(now)
            self._cleanup_at = now + CLEANUP_EVERY_MS

    def _wait(self) -> float:
        """Seconds until the first deadline."""
        deadlines = [self._cleanup_at]
        for deadline in (self._core.deadline, self._supervisor.deadline):
            if deadline is not None:
                deadlines.append(deadline)
        return min(max(0, min(deadlines) - self._clock.now()) / 1000, LONGEST_WAIT_S)

    def _status(self, status: Status) -> None:
        """Called inside the supervisor, which it must not call back: `core` catches up on the
        engine's return in a command of its own (ADR-0011). A wake is no return, since nothing
        failed while the engine slept; but a wake after one the GPU's memory refused is
        (ADR-0027)."""
        self._on_engine(status)
        woken = self._engine == Status(State.ASLEEP)
        self._engine = status
        if status.state is State.READY and not woken:
            self.command(Reminders.model_ready)

    def _exited(self) -> None:
        """An engine's output ended, on its stdout thread: `poll` notices it, if it was idle."""
        self._queue.put(_wake)

    def _shut(self) -> None:
        try:
            self._capture.close()
            # Nothing is in front any more, and no situation is read: the context in front and
            # the stretches of the situations leave with the app, all at one time, as the
            # harness finds the app's close (ADR-0021, ADR-0028).
            at = self._clock.now()
            self._core.observe(Observation(at, None))
            for situation in Situation:
                self._core.observe(SituationObservation(at, situation, None))
            self._save()
            self._supervisor.close()
        finally:
            self._store.close()


class QueuedCore:
    """`core.Reminders` as the interface sees it: each command goes on the worker's queue, and the
    interface does not wait for it (ADR-0012)."""

    def __init__(self, worker: Worker) -> None:
        self._worker = worker

    def done(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.done(alert_id))

    def not_here(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.not_here(alert_id))

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._worker.command(lambda core: core.snooze(alert_id, snooze))

    def close(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.close(alert_id))

    def vanished(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.vanished(alert_id))

    def seen(self) -> None:
        self._worker.command(lambda core: core.seen())

    def create(self, condition: str, action: str, perennial: bool) -> None:
        self._worker.command(lambda core: core.create(condition, action, perennial))

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None:
        self._worker.command(lambda core: core.edit(reminder_id, condition, action, perennial))

    def complete(self, reminder_id: int) -> None:
        self._worker.command(lambda core: core.complete(reminder_id))

    def delete(self, reminder_id: int) -> None:
        self._worker.command(lambda core: core.delete(reminder_id))
