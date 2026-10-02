"""The model file's own thread, with `model_file.ensure` played by the test (#39, #44)."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from jiffin.app.model import ModelFetch
from jiffin.client import model_file
from jiffin.client.model_file import ModelFileError, Phase, PinnedFile, Problem, Progress
from jiffin.ui.first_run import FirstRun, ModelState

FILE = PinnedFile("model.gguf", "https://example.org/model.gguf", 2_000, "0" * 64)
FOLDER = Path("models")
WAIT_S = 10.0
"""The longest a test waits for the thread."""
NETWORK = ModelFileError(Problem.NETWORK, "the server cannot be reached")


class Ensure:
    """`model_file.ensure`, one outcome per call: an error, or the file downloaded and checked."""

    def __init__(self, *outcomes: ModelFileError | None) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.going = 0
        """Calls under way at once."""
        self.most = 0
        self.entered = threading.Event()
        """A call has begun."""
        self.gate = threading.Event()
        """Set by the test to let a call go on; it starts set."""
        self.gate.set()

    def __call__(
        self, file: PinnedFile, directory: Path, on_progress: Callable[[Progress], None]
    ) -> Path:
        assert (file, directory) == (FILE, FOLDER)
        self.calls += 1
        self.going += 1
        self.most = max(self.most, self.going)
        self.entered.set()
        try:
            assert self.gate.wait(WAIT_S)
            outcome = self._outcomes.pop(0)
            if outcome is not None:
                raise outcome
            on_progress(Progress(Phase.DOWNLOADING, 1_000, 2_000))
            on_progress(Progress(Phase.CHECKING, 2_000, 2_000))
            return directory / file.name
        finally:
            self.going -= 1


class Said:
    """What the thread said, in order; the test waits for it."""

    def __init__(self) -> None:
        self.states: list[ModelState] = []
        self.ready = 0
        self._changed = threading.Condition()

    def state(self, state: ModelState) -> None:
        with self._changed:
            self.states.append(state)
            self._changed.notify_all()

    def on_ready(self) -> None:
        with self._changed:
            self.ready += 1
            self._changed.notify_all()

    def stages(self) -> list[FirstRun.Stage]:
        with self._changed:
            return [state.stage for state in self.states]

    def wait_for(self, stage: FirstRun.Stage, times: int = 1) -> None:
        with self._changed:
            assert self._changed.wait_for(
                lambda: [state.stage for state in self.states].count(stage) >= times, WAIT_S
            ), f"no {stage.name} after {self.states}"


type Fetch = Callable[..., tuple[ModelFetch, Ensure, Said]]


@pytest.fixture
def fetch(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fetch]:
    ensures: list[Ensure] = []

    def make(
        *outcomes: ModelFileError | None, retry_seconds: float = 60
    ) -> tuple[ModelFetch, Ensure, Said]:
        ensure, said = Ensure(*outcomes), Said()
        monkeypatch.setattr(model_file, "ensure", ensure)
        ensures.append(ensure)
        fetch = ModelFetch(FILE, FOLDER, said.state, said.on_ready, retry_seconds=retry_seconds)
        return fetch, ensure, said

    yield make
    for ensure in ensures:  # no thread is left waiting
        ensure.gate.set()


def test_the_download_and_the_check_reach_the_window_then_ready(fetch: Fetch) -> None:
    fetching, _, said = fetch(None)
    fetching.fetch()
    said.wait_for(FirstRun.Stage.READY)
    assert said.states == [
        ModelState(FirstRun.Stage.DOWNLOADING, 1_000, 2_000),
        ModelState(FirstRun.Stage.CHECKING, 2_000, 2_000),
        ModelState(FirstRun.Stage.READY),
    ]
    assert said.ready == 1


@pytest.mark.parametrize(
    ("problem", "stage"),
    [
        (Problem.NETWORK, FirstRun.Stage.NETWORK),
        (Problem.SPACE, FirstRun.Stage.SPACE),
        (Problem.DISK, FirstRun.Stage.DISK),
        (Problem.MISMATCH, FirstRun.Stage.MISMATCH),
    ],
)
def test_each_problem_reaches_the_window(
    fetch: Fetch, problem: Problem, stage: FirstRun.Stage
) -> None:
    fetching, _, said = fetch(ModelFileError(problem, "a problem", missing=1_234))
    fetching.fetch()
    said.wait_for(stage)
    assert said.states == [ModelState(stage, missing=1_234)]
    assert said.ready == 0


def test_a_network_problem_is_tried_again_on_its_own(fetch: Fetch) -> None:
    fetching, ensure, said = fetch(NETWORK, NETWORK, None, retry_seconds=0.01)
    fetching.fetch()
    said.wait_for(FirstRun.Stage.READY)
    assert said.stages()[:2] == [FirstRun.Stage.NETWORK, FirstRun.Stage.NETWORK]
    assert (ensure.calls, said.ready) == (3, 1)


def test_riprova_does_not_wait_for_the_network_to_be_tried_again(fetch: Fetch) -> None:
    fetching, _, said = fetch(NETWORK, None)
    fetching.fetch()
    said.wait_for(FirstRun.Stage.NETWORK)
    fetching.fetch()
    said.wait_for(FirstRun.Stage.READY)


def test_the_other_problems_wait_for_riprova(fetch: Fetch) -> None:
    fetching, ensure, said = fetch(
        ModelFileError(Problem.MISMATCH, "another file"), None, retry_seconds=0.01
    )
    fetching.fetch()
    said.wait_for(FirstRun.Stage.MISMATCH)
    threading.Event().wait(0.2)
    assert ensure.calls == 1
    fetching.fetch()
    said.wait_for(FirstRun.Stage.READY)


def test_one_call_at_a_time_and_riprova_during_one_makes_one_more(fetch: Fetch) -> None:
    fetching, ensure, said = fetch(NETWORK, None)
    ensure.gate.clear()
    fetching.fetch()
    assert ensure.entered.wait(WAIT_S)
    fetching.fetch()
    fetching.fetch()
    ensure.gate.set()
    said.wait_for(FirstRun.Stage.READY)
    assert (ensure.calls, ensure.most) == (2, 1)


def test_a_thread_that_fails_lets_riprova_start_another(
    fetch: Fetch, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetching, _, said = fetch(None)
    failed = threading.Event()
    monkeypatch.setattr(threading, "excepthook", lambda hook: failed.set())

    def broken(file: PinnedFile, directory: Path, on_progress: Callable[[Progress], None]) -> Path:
        raise RuntimeError("a bug")

    with monkeypatch.context() as patch:
        patch.setattr(model_file, "ensure", broken)
        fetching.fetch()
        assert failed.wait(WAIT_S)
    fetching.fetch()
    said.wait_for(FirstRun.Stage.READY)
