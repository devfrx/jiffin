import io
import subprocess
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import IO, Any

from jiffin.engine.errors import ModelNotLoadable
from jiffin.engine.server import Engine, serve
from jiffin.protocol.errors import ErrorCode
from jiffin.protocol.framing import MAX_LINE_BYTES, read_line, write_message
from jiffin.protocol.jsonrpc import ErrorResponse, Request, SuccessResponse, parse_response
from jiffin.protocol.messages import (
    INITIALIZE,
    JUDGE,
    PROTOCOL_VERSION,
    REWRITE,
    SHUTDOWN,
    Context,
    EngineSettings,
    InitializeParams,
    InitializeResult,
    JudgeParams,
    JudgeResult,
    Method,
    PromptVersions,
    RewriteParams,
    RewriteResult,
    ShutdownParams,
    Statement,
    Strict,
)

SETTINGS = EngineSettings(
    context_per_question=2048, micro_batch=16, load_mode="direct_io", kv_cache="f16"
)
CONTEXT = Context(app="vivaldi.exe", title="Banca Rossi", address="bancarossi.it")
STATEMENTS = [
    Statement(id=4, text="The user is on the bank's website."),
    Statement(id=2, text="The user is writing an email."),
]


class FakeBackend:
    gpu = "NVIDIA GeForce RTX 4060 Laptop GPU"

    def __init__(self, model_type: str = "spark2_5 ?B Q4_K - Medium") -> None:
        self.model_type = model_type
        self.closed = False

    def free_vram_bytes(self) -> int:
        return 4_154_458_112

    def judge(self, context: Context, statements: Sequence[Statement]) -> dict[int, float]:
        return {statement.id: statement.id / 2 for statement in statements}

    def rewrite(self, condition: str) -> str:
        assert condition == "quando apro Figma"
        return "The user has opened Figma."

    def close(self) -> None:
        self.closed = True


class Loader:
    def __init__(self, backend: FakeBackend | Exception | None = None) -> None:
        self.backend = backend or FakeBackend()
        self.calls: list[tuple[Path, EngineSettings]] = []

    def __call__(self, path: Path, settings: EngineSettings) -> FakeBackend:
        self.calls.append((path, settings))
        if isinstance(self.backend, Exception):
            raise self.backend
        return self.backend


def initialize(protocol: int = PROTOCOL_VERSION) -> InitializeParams:
    return InitializeParams(
        protocol=protocol, model_path="C:\\modelli\\rizzo.gguf", settings=SETTINGS
    )


def ask[R: Strict | None](
    engine: Engine, method: Method[Any, R], params: Strict, request_id: int = 1
) -> SuccessResponse[R] | ErrorResponse:
    line = Request(id=request_id, method=method.name, params=params).model_dump_json().encode()
    response = engine.answer(line, received=0.0)
    return parse_response(response.model_dump_json().encode(), method.result)


def error_of(response: SuccessResponse[Any] | ErrorResponse) -> ErrorCode:
    assert isinstance(response, ErrorResponse), response
    return response.error.code


def test_initialize_loads_the_model_and_reports_the_engine() -> None:
    loader = Loader()
    response = ask(Engine(loader), INITIALIZE, initialize())
    assert loader.calls == [(Path("C:\\modelli\\rizzo.gguf"), SETTINGS)]
    assert response == SuccessResponse(
        id=1,
        result=InitializeResult(
            protocol=PROTOCOL_VERSION,
            engine_version=version("jiffin"),
            llama_cpp_build="b11081",
            gpu="NVIDIA GeForce RTX 4060 Laptop GPU",
            free_vram_bytes=4_154_458_112,
            model_type="spark2_5 ?B Q4_K - Medium",
            prompt_versions=PromptVersions(judge=1, rewrite=2),
        ),
    )


def test_initialize_refuses_another_protocol_before_loading() -> None:
    loader = Loader()
    response = ask(Engine(loader), INITIALIZE, initialize(PROTOCOL_VERSION + 1))
    assert error_of(response) == ErrorCode.PROTOCOL_MISMATCH
    assert loader.calls == []


def test_a_model_that_cannot_be_loaded_is_reported_with_its_detail() -> None:
    loader = Loader(ModelNotLoadable("there is no model file at C:\\modelli\\rizzo.gguf"))
    response = ask(Engine(loader), INITIALIZE, initialize())
    assert isinstance(response, ErrorResponse)
    assert response.error.code == ErrorCode.MODEL_NOT_LOADABLE
    assert response.error.data.detail == "there is no model file at C:\\modelli\\rizzo.gguf"
    assert response.error.data.retry is False


def test_initialize_again_replaces_the_model() -> None:
    first, second = FakeBackend(), FakeBackend()
    loader = Loader(first)
    engine = Engine(loader)
    ask(engine, INITIALIZE, initialize())
    loader.backend = second
    ask(engine, INITIALIZE, initialize(), request_id=2)
    assert first.closed and not second.closed


def test_judge_needs_initialize_first() -> None:
    response = ask(Engine(Loader()), JUDGE, JudgeParams(context=CONTEXT, statements=STATEMENTS))
    assert error_of(response) == ErrorCode.NOT_INITIALIZED


def test_judge_returns_d_for_every_statement_in_order() -> None:
    engine = Engine(Loader())
    ask(engine, INITIALIZE, initialize())
    response = ask(engine, JUDGE, JudgeParams(context=CONTEXT, statements=STATEMENTS), 2)
    assert isinstance(response, SuccessResponse)
    assert isinstance(response.result, JudgeResult)
    assert [(score.id, score.d) for score in response.result.scores] == [(4, 2.0), (2, 1.0)]
    assert response.result.timings.total_seconds >= 0


def test_a_failure_inside_judge_is_an_internal_error_and_the_engine_goes_on() -> None:
    class Failing(FakeBackend):
        def judge(self, context: Context, statements: Sequence[Statement]) -> dict[int, float]:
            raise RuntimeError("llama_decode returned -3")

    engine = Engine(Loader(Failing()))
    ask(engine, INITIALIZE, initialize())
    response = ask(engine, JUDGE, JudgeParams(context=CONTEXT, statements=STATEMENTS), 2)
    assert isinstance(response, ErrorResponse)
    assert response.error.code == ErrorCode.INTERNAL_ERROR
    assert response.error.data.detail == "RuntimeError: llama_decode returned -3"
    again = ask(engine, JUDGE, JudgeParams(context=CONTEXT, statements=STATEMENTS), 3)
    assert error_of(again) == ErrorCode.INTERNAL_ERROR


def test_rewrite_returns_the_statement_and_its_prompt_version() -> None:
    engine = Engine(Loader())
    ask(engine, INITIALIZE, initialize())
    response = ask(engine, REWRITE, RewriteParams(condition="quando apro Figma"), 2)
    assert isinstance(response, SuccessResponse)
    assert isinstance(response.result, RewriteResult)
    assert response.result.statement == "The user has opened Figma."
    assert response.result.prompt_version == 2
    assert response.result.timings.total_seconds >= 0


def test_rewrite_needs_initialize_first() -> None:
    response = ask(Engine(Loader()), REWRITE, RewriteParams(condition="quando apro Figma"))
    assert error_of(response) == ErrorCode.NOT_INITIALIZED


def test_shutdown_releases_the_model() -> None:
    backend = FakeBackend()
    engine = Engine(Loader(backend))
    ask(engine, INITIALIZE, initialize())
    assert ask(engine, SHUTDOWN, ShutdownParams(), 2) == SuccessResponse(id=2, result=None)
    assert backend.closed
    response = ask(engine, JUDGE, JudgeParams(context=CONTEXT, statements=STATEMENTS), 3)
    assert error_of(response) == ErrorCode.NOT_INITIALIZED


def test_serve_answers_in_order_until_the_input_ends() -> None:
    requests = io.BytesIO()
    write_message(requests, Request(id=1, method="initialize", params=initialize()))
    requests.write(b"{not json\n")
    requests.write(b"x" * (MAX_LINE_BYTES + 1) + b"\n")
    write_message(requests, Request(id=2, method="shutdown", params=ShutdownParams()))
    requests.seek(0)
    responses = io.BytesIO()
    serve(requests, responses, Engine(Loader()))
    responses.seek(0)
    initialized = parse_response(next_line(responses), InitializeResult)
    not_json = parse_response(next_line(responses), type(None))
    too_long = parse_response(next_line(responses), type(None))
    shut_down = parse_response(next_line(responses), type(None))
    assert read_line(responses) is None
    assert isinstance(initialized, SuccessResponse)
    assert error_of(not_json) == ErrorCode.PARSE_ERROR
    assert error_of(too_long) == ErrorCode.PARSE_ERROR
    assert shut_down == SuccessResponse(id=2, result=None)


def test_a_response_too_long_to_send_becomes_an_error() -> None:
    requests = io.BytesIO()
    write_message(requests, Request(id=1, method="initialize", params=initialize()))
    requests.seek(0)
    responses = io.BytesIO()
    serve(requests, responses, Engine(Loader(FakeBackend(model_type="x" * MAX_LINE_BYTES))))
    responses.seek(0)
    response = parse_response(next_line(responses), InitializeResult)
    assert isinstance(response, ErrorResponse)
    assert response.id == 1
    assert response.error.code == ErrorCode.INTERNAL_ERROR


def test_the_engine_process_speaks_the_protocol_and_exits_when_stdin_closes(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "rizzo.gguf"
    process = subprocess.Popen(
        [sys.executable, "-m", "jiffin.engine"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    )
    assert process.stdin is not None and process.stdout is not None
    params = InitializeParams(protocol=PROTOCOL_VERSION, model_path=str(missing), settings=SETTINGS)
    write_message(process.stdin, Request(id=1, method="initialize", params=params))
    loaded = parse_response(next_line(process.stdout), InitializeResult)
    judge = JudgeParams(context=CONTEXT, statements=STATEMENTS)
    write_message(process.stdin, Request(id=2, method="judge", params=judge))
    judged = parse_response(next_line(process.stdout), JudgeResult)
    process.stdin.close()
    assert process.wait(timeout=60) == 0
    assert process.stdout.read() == b""
    assert isinstance(loaded, ErrorResponse)
    assert loaded.error.code == ErrorCode.MODEL_NOT_LOADABLE
    assert loaded.error.data.detail == f"there is no model file at {missing}"
    assert error_of(judged) == ErrorCode.NOT_INITIALIZED


STRAY_OUTPUT = """
import ctypes
import os

from jiffin.engine.server import take_stdout

protocol = take_stdout()
print("from print", flush=True)
os.write(1, b"from the C runtime\\n")
kernel32 = ctypes.windll.kernel32
kernel32.GetStdHandle.restype = ctypes.c_void_p
handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
written = ctypes.c_ulong()
kernel32.WriteFile(ctypes.c_void_p(handle), b"from Win32\\n", 11, ctypes.byref(written), None)
protocol.write(b"protocol\\n")
protocol.flush()
"""


def test_whatever_else_prints_goes_to_stderr_not_to_the_protocol() -> None:
    finished = subprocess.run(
        [sys.executable, "-c", STRAY_OUTPUT], capture_output=True, check=True, timeout=60
    )
    assert finished.stdout == b"protocol\n"
    stray = finished.stderr.splitlines()
    assert {b"from print", b"from the C runtime", b"from Win32"} <= set(stray)


LOUD_ENGINE = """
import logging

from jiffin.engine import server

class Loud(server.Engine):
    def __init__(self) -> None:
        super().__init__()
        logging.getLogger("jiffin.engine").warning("il modello di Niccolò")
        print("una stampa: è così", flush=True)

server.Engine = Loud
server.main()
"""


def test_the_engine_writes_its_stderr_in_utf8_whatever_the_code_page() -> None:
    finished = subprocess.run(
        [sys.executable, "-c", LOUD_ENGINE], input=b"", capture_output=True, check=True, timeout=60
    )
    assert "il modello di Niccolò".encode() in finished.stderr
    assert "una stampa: è così".encode() in finished.stderr


def next_line(stream: io.BytesIO | IO[bytes]) -> bytes:
    line = read_line(stream)
    assert line is not None
    return line
