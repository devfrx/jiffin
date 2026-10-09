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
from jiffin.client.supervisor import IDLE_MS, State, Status, StopReason
from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock, SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.records import Evaluation, Outcome, Record, Snooze
from jiffin.core.reminders import (
    HOUR_MS,
    RETURN_PAUSE_MS,
    HereView,
    Pause,
    Reminders,
    RemindersView,
)
from jiffin.core.situations import (
    CHANGE_MS,
    NO,
    PLUGGED,
    Situation,
    SituationObservation,
    SituationStretch,
)
from jiffin.harness.truth import unread
from jiffin.store.migrate import StoreError
from jiffin.store.store import RETENTION_MS, Json, Log, Store

FAKE_ENGINE = [sys.executable, str(Path(__file__).parents[1] / "client" / "fake_engine.py")]
START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
DAY_MS = 24 * 60 * 60 * 1000
SHA256 = "79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54"
FIGMA = Context("figma.exe", "Icone - Figma", None)
WAIT_S = 10.0
"""The longest a test waits for the worker."""
STARTING, READY, ASLEEP = Status(State.STARTING), Status(State.READY), Status(State.ASLEEP)


class Contexts:
    """The context port, played by the test: what it observes goes where the capture's would."""

    def __init__(self, observe: Callable[[Observation | SituationObservation], None]) -> None:
        self.observe = observe
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True


class RefusedContexts(Contexts):
    def start(self) -> None:
        raise OSError("SetWinEventHook refused the event 0x0003")


class Scene:
    """A worker on a database in a temporary folder, with what it said."""

    def __init__(
        self, folder: Path, clock: Clock, model: str, contexts: type[Contexts] = Contexts
    ) -> None:
        self._kind = contexts
        self.clock = clock
        self.database = folder / "jiffin.db"
        self.alerts: list[AlertsView] = []
        self.lists: list[RemindersView] = []
        self.statuses: list[Status] = []
        self.heres: list[HereView] = []
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
        self.core = QueuedCore(self.worker, self.heres.append)

    def _contexts(self, observe: Callable[[Observation | SituationObservation], None]) -> Contexts:
        self.contexts = self._kind(observe)
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

    def log(self) -> Log:
        """What the database keeps, once the worker has closed."""
        store = Store.open(self.database)
        try:
            return store.log()
        finally:
            store.close()

    def statement(self) -> str | None:
        with closing(sqlite3.connect(self.database)) as db:
            return cast(str | None, db.execute("SELECT statement FROM revision").fetchone()[0])

    def return_pause(self) -> int:
        """The return pause `core` holds now, in milliseconds."""
        seen: Future[int] = Future()
        self.worker.command(lambda core: seen.set_result(core.return_pause))
        return seen.result(WAIT_S)

    def deadline(self) -> int | None:
        """When `core` has something to do next."""
        seen: Future[int | None] = Future()
        self.worker.command(lambda core: seen.set_result(core.deadline))
        return seen.result(WAIT_S)


type MakeScene = Callable[..., Scene]


@pytest.fixture
def make_scene(tmp_path: Path) -> Iterator[MakeScene]:
    scenes: list[Scene] = []

    def make(
        clock: Clock | None = None, model: str = "model.gguf", contexts: type[Contexts] = Contexts
    ) -> Scene:
        scenes.append(Scene(tmp_path, clock or SimulatedClock(START), model, contexts))
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
    first.core.create("quando apro Figma", "esportare le icone", False)
    first.worker.close()
    second = make_scene()
    second.worker.start()
    second.settle()
    [active] = second.lists[-1].active
    assert active.reminder.revision.condition == "quando apro Figma"


def test_the_capture_starts_with_the_worker_and_the_engine_once_the_model_file_is_checked(
    scene: Scene,
) -> None:
    scene.settle()
    assert (scene.statuses, scene.contexts.started) == ([], True)
    scene.enter(FIGMA)  # something in front, or the engine falls asleep at once
    scene.worker.model_ready()
    scene.settle()
    assert scene.statuses == [STARTING, READY]


def test_a_reminder_with_only_a_time_rings_before_the_engine_starts(scene: Scene) -> None:
    """While the model downloads, say (ADR-0021)."""
    scene.core.create("oggi", "pagare la bolletta", False)
    scene.enter(FIGMA)
    scene.advance(DEBOUNCE_MS)
    scene.enter(None)
    scene.settle()
    [alert] = scene.alerts[-1].visible
    assert (alert.revision.condition, scene.statuses) == ("oggi", [])


def test_a_capture_that_cannot_start_is_logged_and_the_worker_goes_on(
    make_scene: MakeScene, caplog: pytest.LogCaptureFixture
) -> None:
    scene = make_scene(contexts=RefusedContexts)
    scene.worker.start()
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.settle()
    assert "the context capture cannot start" in caplog.text
    assert [active.reminder.revision.condition for active in scene.lists[-1].active] == [
        "quando apro Figma"
    ]


def test_a_reminder_written_before_the_engine_gets_its_statement_once_it_is_up(
    scene: Scene,
) -> None:
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.settle()
    assert scene.statement() is None
    scene.worker.model_ready()
    scene.settle()
    assert scene.statement() == "The user: quando apro Figma."


def test_the_card_of_remind_here_asks_core_through_the_queue_and_rings_what_it_picks(
    scene: Scene,
) -> None:
    scene.core.create("oggi", "pagare la bolletta", False)
    scene.enter(FIGMA)
    scene.advance(DEBOUNCE_MS)
    scene.core.here()
    scene.settle()
    [view] = scene.heres
    [here] = view.reminders
    # It rang at the first stable context, on its own: a pick rings it again, as asked.
    assert (view.place, here.quiet) == (FIGMA, Outcome.SAME_OCCASION)
    scene.core.remind_here(here.reminder.id, FIGMA)
    scene.settle()
    assert [alert.requested for alert in scene.alerts[-1].visible] == [False, True]


def test_the_contexts_reach_core(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.core.create("quando apro Figma", "esportare le icone", False)
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


def test_the_return_pause_is_read_at_the_start_and_a_new_one_is_in_force_at_once(
    make_scene: MakeScene,
) -> None:
    first = make_scene()
    assert first.worker.start().return_pause == RETURN_PAUSE_MS // 1000
    assert first.return_pause() == RETURN_PAUSE_MS
    first.worker.keep_return_pause(30)
    assert first.return_pause() == 30_000
    first.worker.close()
    second = make_scene()
    assert second.worker.start().return_pause == 30
    assert second.return_pause() == 30_000


@pytest.mark.parametrize(
    ("kept", "return_pause"),
    [(10, 10_000), (7200, 7_200_000), (9, RETURN_PAUSE_MS), (7201, RETURN_PAUSE_MS)]
    + [(kept, RETURN_PAUSE_MS) for kept in (120.5, "120", True, [120])],
)
def test_a_return_pause_out_of_the_range_or_of_another_shape_is_the_default(
    make_scene: MakeScene, kept: Json, return_pause: int
) -> None:
    """From a later version, after a downgrade."""
    scene = make_scene()
    with closing(Store.open(scene.database)) as store:
        store.set_setting("return_pause", kept)
    assert scene.worker.start().return_pause == return_pause // 1000
    assert scene.return_pause() == return_pause


def test_a_pause_is_kept_through_a_restart_until_riprendi(make_scene: MakeScene) -> None:
    first = make_scene()
    first.worker.start()
    first.worker.pause(Pause.HOUR)
    first.settle()
    assert first.lists[-1].paused_until == START + HOUR_MS
    first.worker.close()
    with closing(Store.open(first.database)) as store:
        assert store.setting("paused_until") == START + HOUR_MS
    second = make_scene()
    second.worker.start()
    second.settle()
    assert second.lists[-1].paused_until == START + HOUR_MS
    assert second.deadline() == START + HOUR_MS
    second.worker.resume()
    second.settle()
    assert second.lists[-1].paused_until is None
    second.worker.close()
    with closing(Store.open(second.database)) as store:
        assert store.setting("paused_until") is None


@pytest.mark.parametrize("kept", [START, START - 1, str(START + HOUR_MS), START + HOUR_MS + 0.5])
def test_a_pause_over_or_of_another_shape_is_no_pause(make_scene: MakeScene, kept: Json) -> None:
    scene = make_scene()
    with closing(Store.open(scene.database)) as store:
        store.set_setting("paused_until", kept)
    scene.worker.start()
    scene.settle()
    assert scene.lists == []
    assert scene.deadline() is None


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
    scene.core.create("quando apro Figma", "esportare le icone", False)
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


# The engine's light sleep (ADR-0027)


def test_the_engine_sleeps_while_nothing_is_in_front(scene: Scene) -> None:
    scene.enter(FIGMA)
    scene.worker.model_ready()
    scene.settle()
    scene.enter(None)
    scene.settle()
    assert scene.statuses == [STARTING, READY, ASLEEP]
    with closing(sqlite3.connect(scene.database)) as db:
        slept = db.execute("SELECT slept_at, reason, woken_at FROM engine_sleep").fetchall()
    assert slept == [(START, "nothing_in_front", None)]


def test_the_stretches_with_nothing_in_front_are_saved_for_the_harness(scene: Scene) -> None:
    scene.advance(1_000)
    scene.enter(FIGMA)
    scene.settle()
    scene.advance(60_000)
    scene.enter(None)
    scene.settle()
    with closing(sqlite3.connect(scene.database)) as db:
        stretches = db.execute("SELECT since, until FROM nothing_in_front ORDER BY since")
        assert stretches.fetchall() == [(START, START + 1_000), (START + 61_000, None)]


def test_a_context_wakes_the_engine_before_its_5_s_and_is_judged_once(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.settle()
    assert scene.statuses[-1] == ASLEEP
    scene.enter(FIGMA)
    scene.settle()
    assert scene.statuses[-1] == READY
    scene.advance(DEBOUNCE_MS)
    scene.settle()
    with closing(sqlite3.connect(scene.database)) as db:
        cached = [row[0] for row in db.execute("SELECT from_cache FROM candidate")]
    assert cached == [0]
    [alert] = scene.alerts[-1].visible
    assert alert.context == FIGMA


def test_a_wake_does_not_judge_the_stable_context_again(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.enter(FIGMA)
    scene.settle()
    scene.advance(DEBOUNCE_MS)
    scene.settle()
    scene.advance(IDLE_MS)
    scene.settle()
    assert scene.statuses[-1] == ASLEEP
    scene.core.create("quando apro Teams", "rispondere a Mario", False)  # its statement wakes it
    scene.settle()
    assert scene.statuses[-1] == READY
    assert scene.count("evaluation") == 1


def test_the_engine_sleeps_5_minutes_after_the_last_judgement(scene: Scene) -> None:
    scene.worker.model_ready()
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.enter(FIGMA)
    scene.settle()
    scene.advance(DEBOUNCE_MS)
    scene.settle()
    scene.advance(IDLE_MS - 1)
    scene.settle()
    assert scene.statuses[-1] == READY
    scene.advance(1)
    scene.settle()
    assert scene.statuses[-1] == ASLEEP


def test_core_catches_up_once_the_engine_wakes_after_a_wake_refused(
    make_scene: MakeScene,
) -> None:
    scene = make_scene(model="no memory at the first wake")
    scene.worker.start()
    scene.worker.model_ready()
    scene.settle()
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.settle()
    assert scene.statuses[-1] == Status(State.ASLEEP, StopReason.GPU_MEMORY)
    assert scene.statement() is None
    scene.worker.restart_engine()
    scene.settle()
    assert scene.statement() == "The user: quando apro Figma."


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


def test_closing_ends_every_situation_at_once_where_the_harness_finds_the_close(
    scene: Scene,
) -> None:
    for situation, value in (
        (Situation.AWAY, NO),
        (Situation.CALL, "discord.exe"),
        (Situation.POWER, PLUGGED),
    ):
        scene.contexts.observe(SituationObservation(START, situation, frozenset({value})))
    scene.enter(FIGMA)
    scene.advance(CHANGE_MS)
    scene.settle()
    scene.advance(60_000)
    scene.worker.close()
    closed_at = START + CHANGE_MS + 60_000
    situations = scene.log().situations
    assert situations == (
        SituationStretch(Situation.AWAY, NO, START, closed_at),
        SituationStretch(Situation.CALL, "discord.exe", START, closed_at),
        SituationStretch(Situation.POWER, PLUGGED, START, closed_at),
    )
    assert unread(situations) == {closed_at}  # no end of the call there (#155)


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
        ("snooze", (7, Snooze.NEXT_TIME)),
        ("close", (7,)),
        ("vanished", (7,)),
        ("seen", ()),
        ("create", ("quando apro Figma", "esportare le icone", True)),
        ("edit", (3, "quando apro Figma", "esportare le icone", True)),
        ("complete", (3,)),
        ("reopen", (3,)),
        ("delete", (3,)),
        ("remind_here", (3, FIGMA)),
        ("withdraw", (3, FIGMA)),
        ("withdraw_all", (3,)),
    ],
)
def test_each_command_of_the_interface_reaches_core_as_given(
    name: str, arguments: tuple[object, ...]
) -> None:
    recorded = Recorded()
    getattr(QueuedCore(cast(Worker, recorded), lambda view: None), name)(*arguments)
    assert recorded.made == [(name, *arguments)]


def test_before_any_place_the_card_gets_no_place_and_no_reminder(scene: Scene) -> None:
    scene.core.create("quando apro Figma", "esportare le icone", False)
    scene.core.here()
    scene.settle()
    assert scene.heres == [HereView(None)]


def test_the_worker_is_its_own_thread(scene: Scene) -> None:
    seen: Future[threading.Thread] = Future()
    scene.worker.command(lambda core: seen.set_result(threading.current_thread()))
    assert seen.result(WAIT_S).name == "worker"
