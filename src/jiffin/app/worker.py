"""The worker thread: it owns `core`, the store and the engine's supervisor, and takes one event at
a time from its queue: the contexts, the interface's commands, the model file, and the deadlines
(ADR-0012). `core` has no locks, and the database has one connection, on this thread.

The other threads put commands on the queue: functions the worker runs. After each one it
handles whatever deadline has come, the engine's restart, the debounce, a snooze or the daily
cleanup, and saves what `core` changed.
"""

import logging
import queue
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from pathlib import Path
from typing import Protocol

from jiffin.client.supervisor import State, Status, Supervisor
from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock
from jiffin.core.context import Observation
from jiffin.core.records import Snooze
from jiffin.core.reminders import Reminders, RemindersView
from jiffin.store.store import Store

log = logging.getLogger(__name__)

CLEANUP_EVERY_MS = 24 * 60 * 60 * 1000
"""The cleanup runs at the start, then once a day (ADR-0013)."""
LONGEST_WAIT_S = 3600.0
"""The worker reads the clock at least once an hour, so that a clock set back, by hand or after
a flat CMOS battery, cannot hold its deadlines back for longer."""
MATERIAL = "material"
"""The setting that keeps the material of the alerts and the tray list, as its letter."""

type Command = Callable[[], object]
"""What it returns is dropped."""


class Source(Protocol):
    """The adapter of the context port: `platform.capture.Capture` in the app."""

    def start(self) -> None: ...
    def close(self) -> None: ...


def _wake() -> None:
    """No command: the worker woke for a deadline, or for an engine whose output ended."""


class Worker:
    """Make it on the interface thread. `start` opens the database on the worker thread, which
    then runs until `close`; any other method may be called from any thread, and only puts a
    command on the queue.

    `on_alerts` and `on_reminders` are `core`'s, and `on_engine` gets the supervisor's status: all
    three are called on the worker thread, and should only pass on what they get. `capture` makes
    the context source, given where its observations go; it starts after the engine's first start.
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
        capture: Callable[[Callable[[Observation], None]], Source],
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
        self._supervisor = Supervisor(
            model, model_sha256, clock, self._status, self._exited, command=engine
        )
        self._capture = capture(self.observe)
        self._capturing = False
        self._cleanup_at = 0
        self._opened: Future[str | None] = Future()
        # A daemon, so that an interface thread that fails cannot leave the process running.
        self._thread = threading.Thread(target=self._run, name="worker", daemon=True)

    def start(self) -> str | None:
        """Open the database, migrated and cleaned up, and go on from what it holds; return the
        material kept in the settings, if any. Raise what opening raised: without its database
        the app cannot go on."""
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

    def observe(self, observation: Observation) -> None:
        """What the context capture saw."""
        self.command(lambda core: core.observe(observation))

    def model_ready(self) -> None:
        """The model file is checked: the engine starts, and after its first start the context
        capture."""
        self._queue.put(self._start_engine)

    def restart_engine(self) -> None:
        """Riprova, on the engine's trouble."""
        self._queue.put(self._supervisor.start)

    def keep_material(self, material: str) -> None:
        self._queue.put(lambda: self._store.set_setting(MATERIAL, material))

    # On the worker thread

    def _run(self) -> None:
        try:
            material = self._open()
        except BaseException as error:  # noqa: BLE001  # start() raises it on the interface thread
            self._opened.set_exception(error)
            return
        self._opened.set_result(material)
        command: Command | None = _wake  # the first turn shows what the database held
        while command is not None:
            self._turn(command)
            try:
                command = self._queue.get(timeout=self._wait())
            except queue.Empty:
                command = _wake
        self._shut()

    def _open(self) -> str | None:
        self._store = Store.open(self._database)
        try:
            now = self._clock.now()
            self._store.cleanup(now)
            self._cleanup_at = now + CLEANUP_EVERY_MS
            self._core = Reminders(
                self._supervisor,
                self._clock,
                self._on_alerts,
                self._on_reminders,
                self._store.load(),
            )
            material = self._store.setting(MATERIAL)
        except BaseException:
            self._store.close()
            raise
        return material if isinstance(material, str) else None

    def _turn(self, command: Command) -> None:
        """One command, then whatever deadline has come; then what `core` changed is saved. A
        failure is logged, and the worker goes on with the next command."""
        try:
            command()
            self._due()
        except Exception:
            log.exception("the worker failed")
        self._save()

    def _save(self) -> None:
        records = self._core.take_records()
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

    def _start_engine(self) -> None:
        self._supervisor.start()
        if not self._capturing:
            self._capturing = True
            self._capture.start()

    def _status(self, status: Status) -> None:
        """Called inside the supervisor, which it must not call back: `core` catches up on the
        engine's return in a command of its own (ADR-0011)."""
        self._on_engine(status)
        if status.state is State.READY:
            self.command(Reminders.model_ready)

    def _exited(self) -> None:
        """An engine's output ended, on its stdout thread: `poll` notices it, if it was idle."""
        self._queue.put(_wake)

    def _shut(self) -> None:
        try:
            self._capture.close()
            # Nothing is in front any more: the context in front leaves with the app (ADR-0021).
            self._core.observe(Observation(self._clock.now(), None))
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

    def useful(self, alert_id: int) -> None:
        """Utile, until the alert of version 0.2 replaces it with its Rimanda menu (#102): its
        meaning is now "Alla prossima volta" (ADR-0021)."""
        self._worker.command(lambda core: core.snooze(alert_id, Snooze.NEXT_TIME))

    def not_here(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.not_here(alert_id))

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._worker.command(lambda core: core.snooze(alert_id, snooze))

    def vanished(self, alert_id: int) -> None:
        self._worker.command(lambda core: core.vanished(alert_id))

    def seen(self) -> None:
        self._worker.command(lambda core: core.seen())

    def create(self, condition: str, action: str) -> None:
        self._worker.command(lambda core: core.create(condition, action))

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        self._worker.command(lambda core: core.edit(reminder_id, condition, action))

    def complete(self, reminder_id: int) -> None:
        self._worker.command(lambda core: core.complete(reminder_id))

    def delete(self, reminder_id: int) -> None:
        self._worker.command(lambda core: core.delete(reminder_id))
