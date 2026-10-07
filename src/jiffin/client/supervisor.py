"""The engine as `core` sees it: the model port, with the engine's start and restarts (ADR-0011).

The worker thread owns the supervisor and calls all its methods (ADR-0012). A call blocks
until the engine answers, fails, or runs out of time. A failed engine starts again 1 s, 10 s
and 60 s later, and the fourth failure within an hour stops it: the supervisor exposes when as
`deadline`, on the same clock as the deadlines of `core`, and whoever drives the worker calls
`poll` once the clock reaches it.
"""

import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from jiffin.client.process import EngineProcess, Failure, Refusal
from jiffin.core.clock import Clock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, ModelError
from jiffin.protocol.errors import ErrorCode
from jiffin.protocol.messages import (
    INITIALIZE,
    JUDGE,
    PROTOCOL_VERSION,
    REWRITE,
    EngineSettings,
    InitializeParams,
    JudgeParams,
    Method,
    RewriteParams,
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


class State(Enum):
    OFF = auto()
    """Not started yet, or closed."""
    STARTING = auto()
    READY = auto()
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
    """Why the engine stopped, in STOPPED."""


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
    """The adapter of the model port: it starts the engine, talks to it, and restarts it.

    `model` is the model file, already checked against `model_sha256`, which every build
    records. `on_status` is called on the worker thread, from inside the supervisor, whenever
    the status changes: it must not call the supervisor back. `on_exit` is called from another
    thread when the output of an engine ends, so that the worker calls `poll`.
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

    @property
    def status(self) -> Status:
        return self._status

    @property
    def deadline(self) -> int | None:
        """When `poll` starts the engine again."""
        return self._restart_at

    # Lifecycle

    def start(self) -> None:
        """Start the engine now, with no failures counted: when the app starts, and Retry."""
        if self._status.state not in (State.STARTING, State.READY):
            self._failures.clear()
            self._launch()

    def poll(self) -> None:
        """Notice an engine whose output ended while idle, and start one when it is time."""
        process = self._process
        if process is not None and process.ended and self._status.state is State.READY:
            self._fail("its output ended")
        if self._restart_at is not None and self._clock.now() >= self._restart_at:
            self._launch()

    def close(self) -> None:
        """Shut the engine down, when the app quits."""
        self._restart_at = None
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
        """Ask the engine; any answer but a result is a ModelError."""
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
        params = InitializeParams(
            protocol=PROTOCOL_VERSION, model_path=str(self._model), settings=SETTINGS
        )
        try:
            result = process.call(INITIALIZE, params, self._timeouts.initialize)
        except Refusal as refusal:
            reason = _STOPPING.get(refusal.error.code)
            if reason is None:
                self._fail(f"initialize: {refusal}")
            else:
                self._stop(reason, f"initialize: {refusal}")
            return
        except Failure as failure:
            self._fail(f"initialize: {failure}")
            return
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
        self._set(Status(State.READY))

    def _fail(self, detail: str) -> None:
        """End the failed engine; start it again later, or stop at the fourth failure."""
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
