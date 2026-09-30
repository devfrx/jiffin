"""The client with the real model: its file against the pin (ADR-0006), and the real engine
under the client's supervision, on the GPU (ADR-0011).

These tests run only on the owner's machine, with `uv run pytest -m integration`; they skip
when the model is not in the `NO_GIT` folder beside the repository.
"""

import time
from dataclasses import replace
from pathlib import Path

import pytest

from jiffin.client import model_file
from jiffin.client.model_file import Phase, Progress
from jiffin.client.supervisor import TIMEOUTS, State, Status, Supervisor
from jiffin.core.clock import SystemClock
from jiffin.core.context import Context
from jiffin.core.model import ModelError

pytestmark = pytest.mark.integration

MODEL = (
    Path(__file__).resolve().parents[3]
    / "NO_GIT"
    / "rizzo-flow"
    / "models"
    / "rizzo-flow"
    / "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
)
MODEL_SHA256 = model_file.MODEL.sha256
CHANGELOG = Context(
    "vivaldi.exe",
    "CHANGELOG.md at main · rossi/gestionale",
    "github.com/rossi/gestionale/blob/main/CHANGELOG.md",
)
STATEMENTS = {
    7: "The user is reading the changelog of a project.",
    9: "The user is paying a bill.",
}


@pytest.fixture
def model() -> Path:
    if not MODEL.is_file():
        pytest.skip(f"the model is not in {MODEL}")
    return MODEL


def test_the_model_on_this_machine_is_the_pinned_one(model: Path) -> None:
    progress: list[Progress] = []
    assert model_file.ensure(model_file.MODEL, model.parent, progress.append) == model
    size = model_file.MODEL.size
    assert progress[-1] == Progress(Phase.CHECKING, size, size)


def test_the_engine_starts_judges_rewrites_and_shuts_down(model: Path) -> None:
    statuses: list[Status] = []
    supervisor = Supervisor(model, MODEL_SHA256, SystemClock(), statuses.append, lambda: None)
    try:
        supervisor.start()
        build = supervisor.build()
        assert (build.llama_cpp_build, build.model_sha256) == ("b11081", MODEL_SHA256)
        assert supervisor.judge(CHANGELOG, STATEMENTS).keys() == STATEMENTS.keys()
        assert supervisor.rewrite("se sono su Amazon").startswith("The user ")
    finally:
        supervisor.close()
    assert statuses == [Status(State.STARTING), Status(State.READY), Status(State.OFF)]


def test_an_engine_that_does_not_answer_in_time_is_ended_and_comes_back(model: Path) -> None:
    clock = SystemClock()
    supervisor = Supervisor(
        model,
        MODEL_SHA256,
        clock,
        lambda status: None,
        lambda: None,
        timeouts=replace(TIMEOUTS, judge=0.001),
    )
    try:
        supervisor.start()
        with pytest.raises(ModelError):
            supervisor.judge(CHANGELOG, STATEMENTS)
        assert supervisor.status == Status(State.RESTARTING)
        assert supervisor.deadline is not None
        time.sleep(max(0, supervisor.deadline - clock.now()) / 1000)
        supervisor.poll()
        assert supervisor.status == Status(State.READY)
        assert supervisor.rewrite("se sono su Amazon").startswith("The user ")
    finally:
        supervisor.close()
