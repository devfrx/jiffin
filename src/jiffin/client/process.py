"""The engine process: in its own Job Object, spoken to over its pipes (ADR-0011, ADR-0012)."""

import itertools
import queue
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import IO

from jiffin.client.job import CREATE_SUSPENDED, Job
from jiffin.protocol.errors import Error, ProtocolError
from jiffin.protocol.framing import read_line, write_message
from jiffin.protocol.jsonrpc import ErrorResponse, Request, parse_response
from jiffin.protocol.messages import SHUTDOWN, Method, ShutdownParams, Strict

STDERR_LINES = 50
"""The last lines of the engine's stderr kept for the app log."""
_STDERR_CHUNK = 4096
_EXIT_SECONDS = 5.0
"""How long the processes and the pipe threads have to end once the job is closed."""


class Failure(Exception):
    """The engine failed: it exited, its output ended or cannot be read, or it did not answer."""


class Refusal(Exception):
    """The engine answered with an error, and goes on."""

    def __init__(self, error: Error) -> None:
        super().__init__(f"{error.message}: {error.data.detail}")
        self.error = error


class EngineProcess:
    """One engine process, with a thread reading its stdout and one draining its stderr.

    One call at a time, from one thread (ADR-0012). `on_exit` is called from the stdout thread
    once the output ends.
    """

    def __init__(self, command: Sequence[str], on_exit: Callable[[], None]) -> None:
        job = Job()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW,
            )
        except OSError:
            job.close()
            raise
        try:
            job.start(process.pid)
        except OSError:
            with process:
                process.kill()
            job.close()
            raise
        assert process.stdin is not None and process.stdout is not None
        assert process.stderr is not None
        self._job = job
        self._process = process
        self._stdin = process.stdin
        self._ids = itertools.count(1)
        self._answers: queue.Queue[bytes | ProtocolError | None] = queue.Queue()
        self._ended = threading.Event()
        self._stderr: deque[str] = deque(maxlen=STDERR_LINES)
        self._threads = [
            threading.Thread(
                target=self._read, args=(process.stdout, on_exit), name="engine stdout", daemon=True
            ),
            threading.Thread(
                target=self._drain, args=(process.stderr,), name="engine stderr", daemon=True
            ),
        ]
        for thread in self._threads:
            thread.start()

    @property
    def ended(self) -> bool:
        """Whether the engine's output has ended."""
        return self._ended.is_set()

    def call[P: Strict, R: Strict | None](
        self, method: Method[P, R], params: P, timeout: float
    ) -> R:
        """Send one request and wait up to `timeout` seconds for its answer.

        Raise Refusal when the engine answers with an error, Failure when it fails, and
        ValueError, sending nothing, for a request it could not read.
        """
        request = Request(id=next(self._ids), method=method.name, params=params)
        try:
            write_message(self._stdin, request)
        except OSError as error:
            raise Failure(f"its input is closed: {error}") from None
        try:
            line = self._answers.get(timeout=timeout)
        except queue.Empty:
            raise Failure(f"no answer to {method.name} within {timeout:g} s") from None
        if line is None:
            raise Failure("its output ended")
        if isinstance(line, ProtocolError):
            raise Failure(f"an unreadable answer: {line}")
        try:
            response = parse_response(line, method.result)
        except ProtocolError as error:
            raise Failure(f"an unreadable answer: {error}") from None
        answered = (request.id, None) if isinstance(response, ErrorResponse) else (request.id,)
        if response.id not in answered:
            raise Failure(f"an answer to request {response.id} instead of {request.id}")
        if isinstance(response, ErrorResponse):
            raise Refusal(response.error)
        return response.result

    def stop(self, timeout: float) -> int | None:
        """Shut the engine down, then close its input, as ADR-0011 says; return its exit code.

        The engine is killed when it does not answer, or does not exit, within `timeout`
        seconds each time.
        """
        try:
            self.call(SHUTDOWN, ShutdownParams(), timeout)
            self._stdin.close()
            code = self._process.wait(timeout)
        except (Failure, Refusal, OSError, subprocess.TimeoutExpired):
            return self.kill()
        self._release()
        return code

    def kill(self) -> int | None:
        """End the engine and whatever it started; return its exit code.

        None when it has not ended in time: a process can hang inside a driver call.
        """
        self._release()
        try:
            return self._process.wait(_EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            return None

    def stderr_tail(self) -> list[str]:
        """The last lines the engine wrote to stderr: complete once it has ended."""
        return list(self._stderr)

    def _release(self) -> None:
        self._job.close()
        try:
            self._stdin.close()
        except OSError:  # the rest of a message that could not be flushed
            pass
        for thread in self._threads:
            thread.join(_EXIT_SECONDS)

    def _read(self, stream: IO[bytes], on_exit: Callable[[], None]) -> None:
        with stream:
            while True:
                try:
                    line = read_line(stream)
                except ProtocolError as error:
                    self._answers.put(error)
                    continue
                self._answers.put(line)
                if line is None:
                    break
        self._ended.set()
        on_exit()

    def _drain(self, stream: IO[bytes]) -> None:
        with stream:
            for chunk in iter(lambda: stream.readline(_STDERR_CHUNK), b""):
                self._stderr.append(chunk.decode(errors="replace").rstrip())
