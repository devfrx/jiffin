"""The engine process: JSON-RPC 2.0 on stdio, one request at a time, in order (ADR-0011)."""

import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import IO, Any, Protocol

from jiffin.engine import llama_release, prompts
from jiffin.engine.backend_llama import LlamaBackend
from jiffin.engine.errors import EngineError, MethodNotFound, NotInitialized, ProtocolMismatch
from jiffin.protocol.errors import Error, ErrorCode, ProtocolError
from jiffin.protocol.framing import read_line, write_message
from jiffin.protocol.jsonrpc import ErrorResponse, SuccessResponse, parse_request
from jiffin.protocol.messages import (
    PROTOCOL_VERSION,
    Context,
    EngineSettings,
    InitializeParams,
    InitializeResult,
    JudgeParams,
    JudgeResult,
    PromptVersions,
    Score,
    ShutdownParams,
    Statement,
    Strict,
    Timings,
)

log = logging.getLogger(__name__)

type Response = SuccessResponse[Any] | ErrorResponse


class Backend(Protocol):
    """A loaded model, as the server uses it."""

    @property
    def gpu(self) -> str: ...

    @property
    def model_type(self) -> str: ...

    def free_vram_bytes(self) -> int: ...

    def judge(self, context: Context, statements: Sequence[Statement]) -> dict[int, float]: ...

    def close(self) -> None: ...


class Engine:
    """What lives between requests: no model until `initialize`, and none after `shutdown`."""

    def __init__(self, load: Callable[[Path, EngineSettings], Backend] = LlamaBackend.load) -> None:
        self._load = load
        self._backend: Backend | None = None

    def answer(self, line: bytes, received: float) -> Response:
        """The response to one line; `received` is when it arrived, on the perf_counter clock."""
        try:
            request = parse_request(line)
        except ProtocolError as error:
            return ErrorResponse(id=error.request_id, error=error.error)
        try:
            result = self._call(request.params, received)
        except EngineError as error:
            return ErrorResponse(id=request.id, error=error.error())
        except Exception as error:
            log.exception("%s failed", request.method)
            detail = f"{type(error).__name__}: {error}"
            return ErrorResponse(
                id=request.id, error=Error.of(ErrorCode.INTERNAL_ERROR, detail, retry=False)
            )
        return SuccessResponse(id=request.id, result=result)

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None

    def _call(self, params: Strict, received: float) -> Strict | None:
        if isinstance(params, InitializeParams):
            return self._initialize(params)
        if isinstance(params, JudgeParams):
            return self._judge(params, received)
        if isinstance(params, ShutdownParams):
            self.close()
            return None
        raise MethodNotFound("rewrite is not available in this engine yet")

    def _initialize(self, params: InitializeParams) -> InitializeResult:
        if params.protocol != PROTOCOL_VERSION:
            raise ProtocolMismatch(
                f"the app speaks protocol {params.protocol}, the engine {PROTOCOL_VERSION}"
            )
        self.close()
        started = time.perf_counter()
        backend = self._load(Path(params.model_path), params.settings)
        self._backend = backend
        log.info("model loaded on %s in %.1f s", backend.gpu, time.perf_counter() - started)
        return InitializeResult(
            protocol=PROTOCOL_VERSION,
            engine_version=version("jiffin"),
            llama_cpp_build=llama_release.RELEASE,
            gpu=backend.gpu,
            free_vram_bytes=backend.free_vram_bytes(),
            model_type=backend.model_type,
            prompt_versions=PromptVersions(
                judge=prompts.JUDGE_VERSION, rewrite=prompts.REWRITE_VERSION
            ),
        )

    def _judge(self, params: JudgeParams, received: float) -> JudgeResult:
        if self._backend is None:
            raise NotInitialized("judge needs a model: send initialize first")
        d = self._backend.judge(params.context, params.statements)
        return JudgeResult(
            scores=[Score(id=statement.id, d=d[statement.id]) for statement in params.statements],
            timings=Timings(total_seconds=time.perf_counter() - received),
        )


def serve(requests: IO[bytes], responses: IO[bytes], engine: Engine) -> None:
    """Answer every request in order, until the input ends."""
    while True:
        try:
            line = read_line(requests)
        except ProtocolError as error:
            _send(responses, ErrorResponse(id=None, error=error.error))
            continue
        if line is None:
            return
        _send(responses, engine.answer(line, time.perf_counter()))


def _send(responses: IO[bytes], response: Response) -> None:
    try:
        write_message(responses, response)
    except ValueError as error:  # a response the app could not read: say so instead
        failure = Error.of(ErrorCode.INTERNAL_ERROR, str(error), retry=False)
        write_message(responses, ErrorResponse(id=response.id, error=failure))


def take_stdout() -> IO[bytes]:
    """Keep the real stdout for the protocol, and point descriptor 1 at stderr.

    Whatever else prints, Python or a DLL, then lands in the log instead of breaking the
    protocol. On Windows the C runtime also moves the process's standard output handle.
    """
    sys.stdout.flush()
    private = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(private, "wb")


def main() -> None:
    """Serve the app on stdin and stdout until stdin closes."""
    responses = take_stdout()
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    engine = Engine()
    try:
        serve(sys.stdin.buffer, responses, engine)
    finally:
        engine.close()
