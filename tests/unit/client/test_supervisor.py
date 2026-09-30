import sys
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from jiffin.client.supervisor import (
    TIMEOUTS,
    State,
    Status,
    StopReason,
    Supervisor,
    Timeouts,
    engine_command,
)
from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, ModelError

FAKE_ENGINE = [sys.executable, str(Path(__file__).with_name("fake_engine.py"))]
START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
HOUR_MS = 3_600_000
SHA256 = "79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54"
FIGMA = Context("figma", "Icone - Figma", None)
ICONS = "The user is designing icons."


class Scene:
    """A supervisor of the fake engine, on simulated time, with the statuses it reported."""

    def __init__(self, model: str, command: Sequence[str], timeouts: Timeouts) -> None:
        self.clock = SimulatedClock(START)
        self.statuses: list[Status] = []
        self.exited = threading.Event()
        self.supervisor = Supervisor(
            Path(model),
            SHA256,
            self.clock,
            on_status=self.statuses.append,
            on_exit=self.exited.set,
            command=command,
            timeouts=timeouts,
        )

    @property
    def status(self) -> Status:
        return self.supervisor.status

    @property
    def wait(self) -> int | None:
        """How long until the engine starts again."""
        deadline = self.supervisor.deadline
        return None if deadline is None else deadline - self.clock.now()

    def fail(self) -> None:
        """The engine exits in the middle of a call."""
        with pytest.raises(ModelError):
            self.supervisor.rewrite("exit")

    def restart(self) -> None:
        """Let the time of the restart come."""
        assert self.wait is not None
        self.clock.advance(self.wait)
        self.supervisor.poll()


type MakeScene = Callable[..., Scene]


@pytest.fixture
def make_scene() -> Iterator[MakeScene]:
    scenes: list[Scene] = []

    def make(
        model: str = "model.gguf",
        command: Sequence[str] = FAKE_ENGINE,
        timeouts: Timeouts = TIMEOUTS,
    ) -> Scene:
        scenes.append(Scene(model, command, timeouts))
        return scenes[-1]

    yield make
    for scene in scenes:
        scene.supervisor.close()


@pytest.fixture
def scene(make_scene: MakeScene) -> Scene:
    """A supervisor whose engine is up."""
    started = make_scene()
    started.supervisor.start()
    return started


def test_start_brings_the_engine_up_and_gives_its_build(make_scene: MakeScene) -> None:
    scene = make_scene()
    scene.supervisor.start()
    assert scene.statuses == [Status(State.STARTING), Status(State.READY)]
    assert scene.supervisor.build() == EngineBuild(
        1, "0.0.1", "b1", SHA256, judge_prompt=3, rewrite_prompt=4
    )


def test_there_is_no_build_before_an_engine_has_started(make_scene: MakeScene) -> None:
    with pytest.raises(ModelError):
        make_scene().supervisor.build()


def test_judge_and_rewrite_are_answered_by_the_engine(scene: Scene) -> None:
    statements = {4: ICONS, 2: "The user is writing code."}
    assert scene.supervisor.judge(FIGMA, statements) == {4: 17.0, 2: 15.0}
    assert scene.supervisor.rewrite("quando apro Figma") == "The user: quando apro Figma."


def test_a_failed_engine_starts_again_one_second_later(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.fail()
    assert scene.status == Status(State.RESTARTING)
    assert scene.wait == 1_000
    assert "è partito" in caplog.text  # its last stderr lines, in the app log
    scene.clock.advance(999)
    scene.supervisor.poll()
    assert scene.status == Status(State.RESTARTING)
    scene.clock.advance(1)
    scene.supervisor.poll()
    assert scene.status == Status(State.READY)
    assert scene.supervisor.rewrite("quando apro Figma") == "The user: quando apro Figma."


def test_the_last_build_stays_while_the_engine_is_down(scene: Scene) -> None:
    scene.fail()
    assert scene.supervisor.build().model_sha256 == SHA256


def test_an_engine_that_does_not_answer_in_time_is_ended(make_scene: MakeScene) -> None:
    scene = make_scene(timeouts=replace(TIMEOUTS, judge=0.5))
    scene.supervisor.start()
    with pytest.raises(ModelError):
        scene.supervisor.judge(FIGMA, {1: "hang"})
    assert scene.status == Status(State.RESTARTING)


def test_restarts_wait_1_10_and_60_seconds_and_the_fourth_failure_stops(scene: Scene) -> None:
    waits = []
    for _ in range(3):
        scene.fail()
        waits.append(scene.wait)
        scene.restart()
    scene.fail()
    assert waits == [1_000, 10_000, 60_000]
    assert scene.status == Status(State.STOPPED, StopReason.FAILURES)
    assert scene.wait is None


def test_failures_more_than_an_hour_old_do_not_count(scene: Scene) -> None:
    scene.fail()
    scene.restart()
    scene.clock.advance(HOUR_MS)
    scene.fail()
    assert scene.wait == 1_000


def test_start_after_a_stop_begins_again_with_no_failures(scene: Scene) -> None:
    for _ in range(3):
        scene.fail()
        scene.restart()
    scene.fail()
    scene.supervisor.start()
    assert scene.status == Status(State.READY)
    scene.fail()
    assert scene.wait == 1_000


@pytest.mark.parametrize(
    ("model", "command", "reason"),
    [
        ("no model", FAKE_ENGINE, StopReason.MODEL),
        ("no memory", FAKE_ENGINE, StopReason.GPU_MEMORY),
        ("model.gguf", [*FAKE_ENGINE, "2"], StopReason.MISMATCH),
    ],
)
def test_an_engine_that_refuses_to_start_stays_down_until_started_again(
    make_scene: MakeScene, model: str, command: list[str], reason: StopReason
) -> None:
    scene = make_scene(model, command)
    scene.supervisor.start()
    scene.clock.advance(HOUR_MS)
    scene.supervisor.poll()
    assert scene.status == Status(State.STOPPED, reason)
    assert scene.wait is None


@pytest.mark.parametrize("model", ["exit", "internal"])
def test_an_engine_that_fails_while_starting_starts_again(
    make_scene: MakeScene, model: str
) -> None:
    scene = make_scene(model)
    scene.supervisor.start()
    assert scene.status == Status(State.RESTARTING)
    assert scene.wait == 1_000


def test_an_engine_that_cannot_be_launched_is_tried_again(make_scene: MakeScene) -> None:
    scene = make_scene(command=["no-such-engine.exe"])
    scene.supervisor.start()
    assert scene.status == Status(State.RESTARTING)


def test_an_engine_that_ends_while_idle_starts_again(scene: Scene) -> None:
    scene.supervisor.rewrite("exit later")
    assert scene.exited.wait(timeout=10)
    scene.supervisor.poll()
    assert scene.status == Status(State.RESTARTING)
    assert scene.wait == 1_000


def test_a_call_to_an_engine_that_ended_unnoticed_starts_it_again(scene: Scene) -> None:
    scene.supervisor.rewrite("exit later")
    assert scene.exited.wait(timeout=10)
    with pytest.raises(ModelError):
        scene.supervisor.judge(FIGMA, {1: ICONS})
    assert scene.status == Status(State.RESTARTING)
    assert scene.wait == 1_000


def test_calls_while_the_engine_is_down_fail_at_once(scene: Scene) -> None:
    scene.fail()
    with pytest.raises(ModelError):
        scene.supervisor.judge(FIGMA, {1: ICONS})
    assert scene.status == Status(State.RESTARTING)
    assert scene.wait == 1_000


def test_an_error_answer_fails_only_its_call(scene: Scene) -> None:
    with pytest.raises(ModelError):
        scene.supervisor.judge(FIGMA, {1: "too long"})
    assert scene.status == Status(State.READY)
    assert scene.supervisor.judge(FIGMA, {1: ICONS}) == {1: 14.0}


# Windows titles are UTF-16 and may end halfway through an emoji: a lone surrogate.
def test_a_text_the_engine_cannot_read_fails_only_its_call(scene: Scene) -> None:
    with pytest.raises(ModelError):
        scene.supervisor.judge(Context("figma", "Icone \ud83d", None), {1: ICONS})
    assert scene.status == Status(State.READY)
    assert scene.supervisor.rewrite("quando apro Figma") == "The user: quando apro Figma."


def test_close_shuts_the_engine_down(scene: Scene) -> None:
    scene.supervisor.close()
    assert scene.status == Status(State.OFF)
    assert scene.exited.wait(timeout=10)


def test_close_cancels_a_restart(scene: Scene) -> None:
    scene.fail()
    scene.supervisor.close()
    assert scene.status == Status(State.OFF)
    assert scene.wait is None


def test_the_real_engine_without_its_model_stays_down_and_says_why(tmp_path: Path) -> None:
    statuses: list[Status] = []
    supervisor = Supervisor(
        tmp_path / "rizzo.gguf", SHA256, SimulatedClock(START), statuses.append, lambda: None
    )
    try:
        supervisor.start()
    finally:
        supervisor.close()
    assert statuses[-2:] == [Status(State.STOPPED, StopReason.MODEL), Status(State.OFF)]


def test_the_packaged_app_starts_the_engine_beside_it(monkeypatch: pytest.MonkeyPatch) -> None:
    installed = r"C:\Users\u\AppData\Local\devfrx.Jiffin\current"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", rf"{installed}\Jiffin.exe")
    assert engine_command() == [rf"{installed}\jiffin-engine.exe"]
