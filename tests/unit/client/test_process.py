import ctypes
import subprocess
import sys
import threading
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path

import pytest

from jiffin.client.job import KILLED
from jiffin.client.process import EngineProcess, Failure, Refusal
from jiffin.protocol.errors import ErrorCode
from jiffin.protocol.framing import MAX_LINE_BYTES
from jiffin.protocol.messages import (
    INITIALIZE,
    JUDGE,
    REWRITE,
    Context,
    EngineSettings,
    InitializeParams,
    InitializeResult,
    JudgeParams,
    PromptVersions,
    RewriteParams,
    Statement,
)

FAKE_ENGINE = Path(__file__).with_name("fake_engine.py")
COMMAND = [sys.executable, str(FAKE_ENGINE)]
SETTINGS = EngineSettings(
    context_per_question=2048, micro_batch=16, load_mode="direct_io", kv_cache="f16"
)
FIGMA = Context(app="figma", title="Icone - Figma", address=None)


@pytest.fixture
def engine() -> Iterator[EngineProcess]:
    started = EngineProcess(COMMAND, on_exit=lambda: None)
    yield started
    started.kill()


def rewrite(condition: str) -> RewriteParams:
    return RewriteParams(condition=condition)


def test_a_call_returns_the_result_of_its_method(engine: EngineProcess) -> None:
    params = InitializeParams(protocol=1, model_path="model.gguf", settings=SETTINGS)
    assert engine.call(INITIALIZE, params, timeout=10) == InitializeResult(
        protocol=1,
        engine_version="0.0.1",
        llama_cpp_build="b1",
        gpu="Fake GPU",
        free_vram_bytes=1 << 30,
        model_type="fake",
        prompt_versions=PromptVersions(judge=3, rewrite=4),
    )
    statements = [
        Statement(id=4, text="The user is designing icons."),
        Statement(id=2, text="The user is writing code."),
    ]
    judged = engine.call(JUDGE, JudgeParams(context=FIGMA, statements=statements), timeout=10)
    assert [(score.id, score.d) for score in judged.scores] == [(4, 17.0), (2, 15.0)]


def test_an_error_answer_is_a_refusal_and_the_engine_goes_on(engine: EngineProcess) -> None:
    with pytest.raises(Refusal) as refused:
        engine.call(REWRITE, rewrite("too long"), timeout=10)
    assert refused.value.error.code == ErrorCode.TEXT_TOO_LONG
    statement = engine.call(REWRITE, rewrite("quando apro Figma"), timeout=10).statement
    assert statement == "The user: quando apro Figma."


@pytest.mark.parametrize("cue", ["exit", "half", "garbage", "another id"])
def test_an_engine_that_exits_or_writes_nonsense_fails(engine: EngineProcess, cue: str) -> None:
    with pytest.raises(Failure):
        engine.call(REWRITE, rewrite(cue), timeout=30)


def test_an_engine_that_does_not_answer_in_time_fails(engine: EngineProcess) -> None:
    engine.call(REWRITE, rewrite("quando apro Figma"), timeout=30)
    with pytest.raises(Failure):
        engine.call(REWRITE, rewrite("hang"), timeout=0.5)


def test_a_request_the_engine_could_not_read_is_not_sent(engine: EngineProcess) -> None:
    with pytest.raises(ValueError):
        engine.call(REWRITE, rewrite("x" * MAX_LINE_BYTES), timeout=10)
    statement = engine.call(REWRITE, rewrite("quando apro Figma"), timeout=10).statement
    assert statement == "The user: quando apro Figma."


def test_stop_shuts_the_engine_down(engine: EngineProcess) -> None:
    engine.call(REWRITE, rewrite("quando apro Figma"), timeout=10)
    assert engine.stop(timeout=10) == 0


def test_stop_kills_an_engine_that_no_longer_listens(engine: EngineProcess) -> None:
    engine.call(REWRITE, rewrite("deaf"), timeout=10)
    assert engine.stop(timeout=0.5) == KILLED


def test_the_end_of_the_output_is_reported() -> None:
    ended = threading.Event()
    engine = EngineProcess(COMMAND, on_exit=ended.set)
    try:
        engine.call(REWRITE, rewrite("exit later"), timeout=10)
        assert ended.wait(timeout=10)
        assert engine.ended
    finally:
        engine.kill()


def test_the_last_stderr_lines_are_kept_as_text(engine: EngineProcess) -> None:
    with pytest.raises(Failure):
        engine.call(REWRITE, rewrite("exit"), timeout=10)
    engine.kill()
    assert engine.stderr_tail()[1] == "è partito"


# An interpreter without uv's launcher, which runs the fake engine as its own child.
BASE_PYTHON = str(Path(sys.base_prefix) / "python.exe")
PARENT = "import subprocess, sys; sys.exit(subprocess.call([sys.executable, sys.argv[1]]))"


def test_kill_ends_every_process_the_engine_started() -> None:
    engine = EngineProcess([BASE_PYTHON, "-c", PARENT, str(FAKE_ENGINE)], on_exit=lambda: None)
    engine.call(REWRITE, rewrite("quando apro Figma"), timeout=30)
    with pytest.raises(Failure):
        engine.call(REWRITE, rewrite("hang"), timeout=0.5)
    engine.kill()
    assert ends(pid_of(engine.stderr_tail()))


# An app that starts the engine, leaves it hanging and crashes: only the Job Object remains.
APP = """
import os, sys, time
from jiffin.client.process import EngineProcess, Failure
from jiffin.protocol.messages import REWRITE, RewriteParams

engine = EngineProcess(sys.argv[1:], on_exit=lambda: None)
try:
    engine.call(REWRITE, RewriteParams(condition="hang"), timeout=0.5)
except Failure:
    pass
while not engine.stderr_tail():
    time.sleep(0.01)
print(engine.stderr_tail()[0], flush=True)
os._exit(1)
"""


def test_the_engine_dies_with_the_app() -> None:
    app = subprocess.run(
        [sys.executable, "-c", APP, *COMMAND],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert app.returncode == 1, app.stderr
    assert ends(pid_of([app.stdout.strip()]))


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
SYNCHRONIZE = 0x00100000
ERROR_INVALID_PARAMETER = 87  # what OpenProcess answers for a process that is gone


def ends(pid: int, within: float = 5.0) -> bool:
    """Whether the process has ended, or ends within `within` seconds."""
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == ERROR_INVALID_PARAMETER:
            return True
        raise ctypes.WinError(error)
    try:
        return bool(kernel32.WaitForSingleObject(handle, int(within * 1000)) == 0)
    finally:
        kernel32.CloseHandle(handle)


def pid_of(stderr: list[str]) -> int:
    """The process id the fake engine writes on its first line."""
    return int(stderr[0].removeprefix("pid "))
