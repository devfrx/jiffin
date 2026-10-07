"""The engine as `core` sees it: the model port, with the engine's start, restarts and light
sleep (ADR-0011, ADR-0027).

The worker thread owns the supervisor and calls all its methods (ADR-0012). A call blocks
until the engine answers, fails, or runs out of time. A failed engine starts again 1 s, 10 s
and 60 s later, and the fourth failure within an hour stops it. The engine sleeps when nothing
is in front, or 5 minutes after `core` last asked it, and wakes when `core` will need it soon,
or when it is asked while asleep. The supervisor exposes when its next restart, sleep or wake
falls as `deadline`, on the same clock as the deadlines of `core`, and whoever drives the
worker calls `poll` once the clock reaches it.
"""

import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum, auto
from pathlib import Path

from jiffin.client.process import EngineProcess, Failure, Refusal
from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, ModelError, Need
from jiffin.core.records import EngineSleep, SleepReason, Waker
from jiffin.protocol.errors import ErrorCode
from jiffin.protocol.messages import (
    INITIALIZE,
    JUDGE,
    PROTOCOL_VERSION,
    REWRITE,
    SHUTDOWN,
    EngineSettings,
    InitializeParams,
    InitializeResult,
    JudgeParams,
    Method,
    RewriteParams,
    ShutdownParams,
    Statement,
    Strict,
)
from jiffin.protocol.messages import Context as ContextMessage

log = logging.getLogger(__name__)

SETTINGS = EngineSettings(
    context_per_question=2048, micro_batch=16, load_mode="direct_io", kv_cache="f16"
)
"""The engine settings of ADR-0011."""

RESTART_DELAYS_MS = (1_000, 10_000, 60_000)
"""The wait after the first, second and third failure within an hour; the fourth stops."""
FAILURE_WINDOW_MS = 3_600_000
IDLE_MS = 5 * 60_000
"""The engine sleeps 5 minutes after `core` last asked it for a judgement or a statement, as
Ollama frees a model by default (ADR-0027)."""
WAKE_RETRY_MS = 60_000
"""After a wake refused for the GPU's memory, the next one waits at least this long, but for
Retry (ADR-0027)."""


class State(Enum):
    OFF = auto()
    """Not started yet, or closed."""
    STARTING = auto()
    READY = auto()
    ASLEEP = auto()
    """A live process without a model, so that the GPU is free: `initialize` wakes it."""
    RESTARTING = auto()
    """Down after a failure: it starts again at `deadline`."""
    STOPPED = auto()
    """Down until `start`, for the reason in the status."""


class StopReason(Enum):
    FAILURES = auto()
    """The engine failed four times within an hour."""
    MODEL = auto()
    """`initialize`: the model cannot be loaded."""
    GPU_MEMORY = auto()
    """`initialize`: the GPU is out of memory."""
    MISMATCH = auto()
    """`initialize`: the engine speaks another protocol version."""


# The errors of `initialize` that starting again cannot mend: the tray says why (ADR-0011).
# Any other error counts as a failure.
_STOPPING = {
    ErrorCode.MODEL_NOT_LOADABLE: StopReason.MODEL,
    ErrorCode.GPU_OUT_OF_MEMORY: StopReason.GPU_MEMORY,
    ErrorCode.PROTOCOL_MISMATCH: StopReason.MISMATCH,
}


@dataclass(frozen=True, slots=True)
class Status:
    """What the tray shows of the engine."""

    state: State
    stop_reason: StopReason | None = None
    """Why the engine stopped, in STOPPED; GPU_MEMORY in ASLEEP once a wake was refused for the
    GPU's memory, until one succeeds."""


@dataclass(frozen=True, slots=True)
class Timeouts:
    """Seconds to wait for each answer."""

    initialize: float
    judge: float
    rewrite: float
    shutdown: float
    """For the answer to `shutdown`, then again for the engine to exit."""


TIMEOUTS = Timeouts(initialize=120, judge=15, rewrite=30, shutdown=10)
"""The starting values of ADR-0011, and ten seconds to shut down."""


def engine_command() -> list[str]:
    """`jiffin-engine.exe` beside the packaged app (ADR-0015), or the module in a checkout."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("jiffin-engine.exe"))]
    return [sys.executable, "-m", "jiffin.engine"]


class Supervisor:
    """The adapter of the model port: it starts the engine, talks to it, restarts it, and lets
    it sleep by what `core` says after each event (`need`).

    `model` is the model file, already checked against `model_sha256`, which every build
    records. `on_status` is called on the worker thread, from inside the supervisor, whenever
    the status changes: it must not call the supervisor back. `on_exit` is called from another
    thread when the output of an engine ends, so that the worker calls `poll`. Each sleep is
    recorded when it starts and again when it ends, for `take_records`.
    """

    def __init__(
        self,
        model: Path,
        model_sha256: str,
        clock: Clock,
        on_status: Callable[[Status], None],
        on_exit: Callable[[], None],
        *,
        command: Sequence[str] | None = None,
        timeouts: Timeouts = TIMEOUTS,
    ) -> None:
        self._model = model
        self._model_sha256 = model_sha256
        self._clock = clock
        self._on_status = on_status
        self._on_exit = on_exit
        self._command = list(engine_command() if command is None else command)
        self._timeouts = timeouts
        self._status = Status(State.OFF)
        self._process: EngineProcess | None = None
        self._build: EngineBuild | None = None
        self._failures: list[int] = []
        """When the engine failed, within the last hour."""
        self._restart_at: int | None = None
        self._need = Need.NOT_NOW
        """What `core` said last."""
        self._asked_at: int | None = None
        """When `core` last asked for a judgement or a statement; until then, when the first
        engine was ready. The 5 minutes run from it."""
        self._sleep: EngineSleep | None = None
        """The sleep under way, while ASLEEP."""
        self._refused_at: int | None = None
        """When the GPU's memory refused the last wake, until one succeeds."""
        self._records: list[EngineSleep] = []

    @property
    def status(self) -> Status:
        return self._status

    @property
    def deadline(self) -> int | None:
        """When `poll` starts the engine again, puts it to sleep 5 minutes after `core` last
        asked it, or tries a wake again for `core` a minute after the GPU's memory refused one.
        Nothing sleeps while `core` needs the model soon."""
        match self._status.state:
            case State.RESTARTING:
                return self._restart_at
            case State.READY if self._need is not Need.SOON and self._asked_at is not None:
                return self._asked_at + IDLE_MS
            case State.ASLEEP if self._need is Need.SOON and self._refused_at is not None:
                return self._refused_at + WAKE_RETRY_MS
        return None

    def take_records(self) -> list[EngineSleep]:
        """The sleeps started or ended since the last call, in order."""
        records, self._records = self._records, []
        return records

    # Lifecycle

    def start(self) -> None:
        """Start the engine now, with no failures counted: when the app starts, and Retry. An
        engine asleep wakes now, also within a minute of a wake refused."""
        if self._status.state is State.ASLEEP:
            self._wake(Waker.RETRY)
        elif self._status.state not in (State.STARTING, State.READY):
            self._failures.clear()
            self._launch()

    def need(self, need: Need) -> None:
        """What `core` says of the model after each event (ADR-0027): SOON wakes the engine,
        NOTHING_IN_FRONT puts it to sleep, and NOT_NOW lets it sleep once 5 minutes have passed
        since `core` last asked it."""
        self._need = need
        state = self._status.state
        if need is Need.SOON and state is State.ASLEEP and self._may_wake():
            self._wake(Waker.CONTEXT)
        elif need is Need.NOTHING_IN_FRONT and state is State.READY:
            self._fall_asleep(SleepReason.NOTHING_IN_FRONT)
        self.poll()

    def poll(self) -> None:
        """Notice an engine whose output ended while idle or asleep, and do what has come due:
        a restart, a sleep, or a wake tried again."""
        process = self._process
        if (
            process is not None
            and process.ended
            and self._status.state in (State.READY, State.ASLEEP)
        ):
            self._fail("its output ended")
        deadline = self.deadline
        if deadline is None or self._clock.now() < deadline:
            return
        match self._status.state:
            case State.RESTARTING:
                self._launch()
            case State.READY:
                self._fall_asleep(SleepReason.IDLE)
            case State.ASLEEP:
                self._wake(Waker.CONTEXT)

    def close(self) -> None:
        """Shut the engine down, when the app quits: asleep too, its sleep is never ended."""
        self._restart_at = None
        self._sleep = None
        process, self._process = self._process, None
        if process is not None:
            log.info("engine closed, exit code %s", process.stop(self._timeouts.shutdown))
        self._set(Status(State.OFF))

    # The model port

    def build(self) -> EngineBuild:
        """The build of the last engine that started: it stays while the engine is down."""
        if self._build is None:
            raise ModelError("no engine has started yet")
        return self._build

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        result = self._call(
            JUDGE,
            lambda: JudgeParams(
                context=ContextMessage(
                    app=context.app, title=context.title, address=context.address
                ),
                statements=[Statement(id=key, text=text) for key, text in statements.items()],
            ),
            self._timeouts.judge,
        )
        return {score.id: score.d for score in result.scores}

    def rewrite(self, condition: str) -> str:
        return self._call(
            REWRITE, lambda: RewriteParams(condition=condition), self._timeouts.rewrite
        ).statement

    # Helpers

    def _call[P: Strict, R: Strict | None](
        self, method: Method[P, R], params: Callable[[], P], timeout: float
    ) -> R:
        """Ask the engine, woken first if it sleeps; any answer but a result is a ModelError.
        Each call starts the 5 minutes again."""
        self._asked_at = self._clock.now()
        if self._status.state is State.ASLEEP:
            if not self._may_wake():
                raise ModelError(f"{method.name}: the engine sleeps, refused by the GPU's memory")
            self._wake(Waker.STATEMENT if method is REWRITE else Waker.JUDGEMENT)
        process = self._process
        if process is None or self._status.state is not State.READY:
            raise ModelError(f"{method.name}: the engine is not running")
        try:
            return process.call(method, params(), timeout)
        except ValueError as error:  # a text the engine could not read, not sent
            raise ModelError(f"{method.name}: {error}") from None
        except Refusal as refusal:
            raise ModelError(f"{method.name}: {refusal}") from None
        except Failure as failure:
            self._fail(f"{method.name}: {failure}")
            raise ModelError(f"{method.name}: the engine failed") from None

    def _launch(self) -> None:
        self._restart_at = None
        self._set(Status(State.STARTING))
        try:
            process = EngineProcess(self._command, self._on_exit)
        except OSError as error:
            self._fail(f"it cannot be started: {error}")
            return
        self._process = process
        try:
            result = self._initialize(process)
        except Refusal as refusal:
            self._refused(refusal)
            return
        except Failure as failure:
            self._fail(f"initialize: {failure}")
            return
        if self._asked_at is None:
            self._asked_at = self._clock.now()
        self._ready(result)

    def _fall_asleep(self, reason: SleepReason) -> None:
        """`shutdown`, keeping the process and its input: the model and its context go, and the
        GPU is free (ADR-0027)."""
        assert self._process is not None
        try:
            self._process.call(SHUTDOWN, ShutdownParams(), self._timeouts.shutdown)
        except (Refusal, Failure) as error:
            self._fail(f"shutdown: {error}")
            return
        self._sleep = EngineSleep(self._clock.now(), reason)
        self._records.append(self._sleep)
        self._set(Status(State.ASLEEP))

    def _wake(self, waker: Waker) -> None:
        """`initialize` again, which ends with the engine's warm-up judgement. A wake refused for
        the GPU's memory leaves the engine asleep, to try again not before a minute."""
        assert self._process is not None
        woken_at = self._clock.now()
        try:
            result = self._initialize(self._process)
        except Refusal as refusal:
            if refusal.error.code is ErrorCode.GPU_OUT_OF_MEMORY:
                self._refused_at = self._clock.now()
                log.warning("engine wake refused: %s; the next not before 60 s", refusal)
                self._set(Status(State.ASLEEP, StopReason.GPU_MEMORY))
                return
            self._end_sleep(woken_at, waker, None)
            self._refused(refusal)
            return
        except Failure as failure:
            self._end_sleep(woken_at, waker, None)
            self._fail(f"initialize: {failure}")
            return
        self._end_sleep(woken_at, waker, self._clock.now())
        self._ready(result)

    def _may_wake(self) -> bool:
        """Not within a minute of a wake refused for the GPU's memory."""
        refused_at = self._refused_at
        return refused_at is None or self._clock.now() - refused_at >= WAKE_RETRY_MS

    def _end_sleep(self, woken_at: int, woken_by: Waker | None, ready_at: int | None) -> None:
        sleep, self._sleep = self._sleep, None
        if sleep is not None:
            self._records.append(
                replace(sleep, woken_at=woken_at, woken_by=woken_by, ready_at=ready_at)
            )

    def _initialize(self, process: EngineProcess) -> InitializeResult:
        params = InitializeParams(
            protocol=PROTOCOL_VERSION, model_path=str(self._model), settings=SETTINGS
        )
        return process.call(INITIALIZE, params, self._timeouts.initialize)

    def _refused(self, refusal: Refusal) -> None:
        """`initialize` answered with an error: stop when starting again cannot mend it."""
        reason = _STOPPING.get(refusal.error.code)
        if reason is None:
            self._fail(f"initialize: {refusal}")
        else:
            self._stop(reason, f"initialize: {refusal}")

    def _ready(self, result: InitializeResult) -> None:
        self._build = EngineBuild(
            protocol=result.protocol,
            engine_version=result.engine_version,
            llama_cpp_build=result.llama_cpp_build,
            model_sha256=self._model_sha256,
            judge_prompt=result.prompt_versions.judge,
            rewrite_prompt=result.prompt_versions.rewrite,
        )
        log.info(
            "engine %s ready: llama.cpp %s on %s with %d MiB free, model %s",
            result.engine_version,
            result.llama_cpp_build,
            result.gpu,
            result.free_vram_bytes >> 20,
            result.model_type,
        )
        self._refused_at = None
        self._set(Status(State.READY))

    def _fail(self, detail: str) -> None:
        """End the failed engine, and its sleep if it slept; start it again later, or stop at
        the fourth failure."""
        self._end_sleep(self._clock.now(), None, None)
        process, self._process = self._process, None
        if process is None:
            log.warning("engine failed: %s", detail)
        else:
            log.warning("engine failed: %s; exit code %s", detail, process.kill())
            _log_stderr(process)
        now = self._clock.now()
        self._failures = [at for at in self._failures if now - at < FAILURE_WINDOW_MS]
        self._failures.append(now)
        if len(self._failures) > len(RESTART_DELAYS_MS):
            self._stop(StopReason.FAILURES, f"{len(self._failures)} failures within an hour")
            return
        delay = RESTART_DELAYS_MS[len(self._failures) - 1]
        self._restart_at = now + delay
        log.info("engine starts again in %d s", delay // 1000)
        self._set(Status(State.RESTARTING))

    def _stop(self, reason: StopReason, detail: str) -> None:
        process, self._process = self._process, None
        if process is not None:  # it has answered: it can shut down as usual
            process.stop(self._timeouts.shutdown)
            _log_stderr(process)
        log.warning("engine stopped: %s", detail)
        self._restart_at = None
        self._set(Status(State.STOPPED, reason))

    def _set(self, status: Status) -> None:
        if status != self._status:
            self._status = status
            self._on_status(status)


def _log_stderr(process: EngineProcess) -> None:
    # The engine writes no titles, addresses or reminder texts there: its messages name files,
    # sizes and ids (engine/errors.py), and the protocol never quotes its input.
    lines = process.stderr_tail()
    if lines:
        log.warning("engine stderr, last %d lines:\n%s", len(lines), "\n".join(lines))
