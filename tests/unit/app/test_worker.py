"""The worker thread with the client's fake engine, on a database in a temporary folder; the
contexts are played by the test (ADR-0012)."""

import sqlite3
import sys
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from jiffin.app.worker import QueuedCore, Worker
from jiffin.client.supervisor import State, Status
from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock, SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.records import Evaluation, Record, Snooze
from jiffin.core.reminders import Reminders, RemindersView
from jiffin.store.migrate import StoreError
from jiffin.store.store import RETENTION_MS, Store

FAKE_ENGINE = [sys.executable, str(Path(__file__).parents[1] / "client" / "fake_engine.py")]
START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
DAY_MS = 24 * 60 * 60 * 1000
SHA256 = "79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54"
FIGMA = Context("figma.exe", "Icone - Figma", None)
WAIT_S = 10.0
"""The longest a test waits for the worker."""
STARTING, READY = Status(State.STARTING), Status(State.READY)


class Contexts:
    """The context port, played by the test: what it observes goes where the capture's would."""

    def __init__(self, observe: Callable[[Observation], None]) -> None:
        self.observe = observe
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


class Scene:
    """A worker on a database in a temporary folder, with what it said."""

    def __init__(self, folder: Path, clock: Clock, model: str) -> None:
        self.clock = clock
        self.database = folder / "jiffin.db"
        self.alerts: list[AlertsView] = []
        self.lists: list[RemindersView] = []
        self.statuses: list[Status] = []
        self.worker = Worker(
            clock,
            self.database,
            Path(model),
            SHA256,
            self.alerts.append,
            self.lists.append,
            self.statuses.append,
            self._contexts,
            engine=FAKE_ENGINE,
        )
        self.core = QueuedCore(self.worker)

    def _contexts(self, observe: Callable[[Observation], None]) -> Contexts:
        self.contexts = Contexts(observe)
        return self.contexts

    def enter(self, context: Context | None) -> None:
        """Bring a context to the foreground, as the capture would observe it."""
        self.contexts.observe(Observation(self.clock.now(), context))

    def advance(self, milliseconds: int) -> None:
        assert isinstance(self.clock, SimulatedClock)
        self.clock.advance(milliseconds)

    def settle(self) -> None:
        """Wait until the worker has run every command put so far, and the commands they put,
        with the deadlines that had come, and saved what changed."""
        self._run_one()
        self._run_one()

    def _run_one(self) -> None:
        done: Future[None] = Future()
        self.worker.command(lambda core: done.set_result(None))
        done.result(WAIT_S)

    def save(self, *records: Record) -> None:
        """Records saved through a second connection, as if by an earlier run."""
        store = Store.open(self.database)
        store.save(records)
        store.close()

    def count(self, table: str) -> int:
        """Rows in a table, read through a second connection."""
        with closing(sqlite3.connect(self.database)) as db:
            return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])

    def statement(self) -> str | None:
        with closing(sqlite3.connect(self.database)) as db:
            return cast(str | None, db.execute("SELECT statement FROM revision").fetchone()[0])


type MakeScene = Callable[..., Scene]


@pytest.fixture
def make_scene(tmp_path: Path) -> Iterator[MakeScene]:
    scenes: list[Scene] = []

    def make(clock: Clock | None = None, model: str = "model.gguf") -> Scene:
        scenes.append(Scene(tmp_path, clock or SimulatedClock(START), model))
        return scenes[-1]

    yield make
    for scene in scenes:
        scene.worker.close()


@pytest.fixture
def scene(make_scene: MakeScene) -> Scene:
    """A worker with its database open, before the model file is checked."""
    started = make_scene()
    started.worker.start()
    return started


def wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        assert time.monotonic() < deadline, "the worker did not get there in time"
        time.sleep(0.01)


def test_what_the_database_holds_shows_at_the_start(make_scene: MakeScene) -> None:
    first = make_scene()
    first.worker.start()
    first.core.create("quando apro Figma", "esportare le icone")
    first.worker.close()
    second = make_scene()
    second.worker.start()
    second.settle()
    [active] = second.lists[-1].active
    assert active.reminder.revision.condition == "quando apro Figma"


def test_the_engine_starts_once_the_model_file_is_checked_then_the_capture(scene: Scene) -> None:
    scene.settle()
    assert (scene.statuses, scene.contexts.started) == ([], False)
    scene.worker.model_ready()
    scene.settle()
    assert (scene.statuses, scene.contexts.started) == ([STARTING, READY], True)


def test_a_reminder_written_before_the_engine_gets_its_statement_once_it_is_up(
    scene: Scene,
) -> None:
    scene.core.create("quando apro Figma", "esportare le icone")
    scene.settle()
    assert scene.statement() is None
    scene.worker.model_ready()
    scene.settle()
    assert scene.statement() == "The user: quando apro Figma."


def test_the_contexts_reach_core(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.core.create("quando apro Figma", "esportare le icone")
    scene.enter(FIGMA)
    scene.advance(DEBOUNCE_MS)
    scene.enter(None)
    scene.settle()
    [alert] = scene.alerts[-1].visible
    assert (alert.context, alert.revision.condition) == (FIGMA, "quando apro Figma")
    assert scene.count("alert") == 1


def test_the_cleanup_runs_at_the_start_then_once_a_day(make_scene: MakeScene) -> None:
    scene = make_scene()
    expired = Evaluation(1, START - RETENTION_MS - 1, FIGMA, START, 0.97, None, ())
    scene.save(expired)
    scene.worker.start()
    scene.settle()
    assert scene.count("evaluation") == 0
    scene.save(replace(expired, id=2))
    scene.advance(DAY_MS - 1)
    scene.settle()
    assert scene.count("evaluation") == 1
    scene.advance(1)
    scene.settle()
    assert scene.count("evaluation") == 0


def test_the_material_is_kept_for_the_next_start(make_scene: MakeScene) -> None:
    first = make_scene()
    assert first.worker.start().material is None
    first.worker.keep_material("c")
    first.worker.close()
    assert make_scene().worker.start().material == "c"


def test_the_windows_places_are_kept_for_the_next_start(make_scene: MakeScene) -> None:
    first = make_scene()
    assert first.worker.start().places == {}
    first.worker.keep_places({"creation": (30, 40)})
    first.worker.keep_places({"creation": (30, 40), "settings": (-1200, 300)})
    first.worker.close()
    assert make_scene().worker.start().places == {"creation": (30, 40), "settings": (-1200, 300)}


def test_places_of_another_shape_are_left_out(make_scene: MakeScene) -> None:
    """From a later version, after a downgrade: those windows open at the centre."""
    scene = make_scene()
    with closing(Store.open(scene.database)) as store:
        store.set_setting(
            "places",
            {"creation": [30, 40], "settings": [1, 2, 3], "first_run": [1, "a"], "x": "a"},
        )
    assert scene.worker.start().places == {"creation": (30, 40)}
    scene.worker.close()
    with closing(Store.open(scene.database)) as store:
        store.set_setting("places", [30, 40])
    assert make_scene().worker.start().places == {}


def test_a_database_from_a_later_version_is_refused(make_scene: MakeScene) -> None:
    scene = make_scene()
    with closing(sqlite3.connect(scene.database)) as db:
        db.execute("PRAGMA user_version = 99")
    with pytest.raises(StoreError, match="version 99"):
        scene.worker.start()


def test_a_command_that_fails_is_logged_and_the_worker_goes_on(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.worker.command(lambda core: 1 / 0)
    scene.core.create("quando apro Figma", "esportare le icone")
    scene.settle()
    assert "the worker failed" in caplog.text
    assert scene.count("reminder") == 1


def test_the_worker_wakes_on_its_own_when_the_engine_starts_again(make_scene: MakeScene) -> None:
    # The engine answers `initialize`, then exits while idle, and the supervisor starts it again
    # one second later.
    scene = make_scene(SystemClock(), model="exit later")
    scene.worker.start()
    scene.worker.model_ready()
    wait_until(lambda: scene.statuses.count(READY) == 2)
    assert scene.statuses[:5] == [STARTING, READY, Status(State.RESTARTING), STARTING, READY]


def test_closing_tells_when_the_context_in_front_left(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.enter(FIGMA)
    scene.advance(DEBOUNCE_MS)
    scene.settle()
    scene.advance(60_000)
    scene.worker.close()
    with closing(sqlite3.connect(scene.database)) as db:
        until = {row[0] for row in db.execute("SELECT context_until FROM evaluation")}
    assert until == {START + DEBOUNCE_MS + 60_000}  # on every evaluation of that stretch


def test_closing_ends_the_capture_and_shuts_the_engine_down(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.settle()
    scene.worker.close()
    assert scene.contexts.closed
    assert scene.statuses[-1] == Status(State.OFF)
    assert not scene.database.with_name(f"{scene.database.name}-wal").exists()


class Recorded:
    """Takes `core`'s commands, and records them."""

    def __init__(self) -> None:
        self.made: list[tuple[object, ...]] = []

    def command(self, command: Callable[[Reminders], object]) -> None:
        command(cast(Reminders, self))

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *arguments: self.made.append((name, *arguments))


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("done", (7,)),
        ("not_here", (7,)),
        ("snooze", (7, Snooze.HOUR)),
        ("vanished", (7,)),
        ("seen", ()),
        ("create", ("quando apro Figma", "esportare le icone")),
        ("edit", (3, "quando apro Figma", "esportare le icone")),
        ("complete", (3,)),
        ("delete", (3,)),
    ],
)
def test_each_command_of_the_interface_reaches_core_as_given(
    name: str, arguments: tuple[object, ...]
) -> None:
    recorded = Recorded()
    getattr(QueuedCore(cast(Worker, recorded)), name)(*arguments)
    assert recorded.made == [(name, *arguments)]


def test_utile_is_alla_prossima_volta_until_the_alert_of_0_2(scene: Scene) -> None:
    recorded = Recorded()
    QueuedCore(cast(Worker, recorded)).useful(7)
    assert recorded.made == [("snooze", 7, Snooze.NEXT_TIME)]


def test_the_worker_is_its_own_thread(scene: Scene) -> None:
    seen: Future[threading.Thread] = Future()
    scene.worker.command(lambda core: seen.set_result(threading.current_thread()))
    assert seen.result(WAIT_S).name == "worker"
