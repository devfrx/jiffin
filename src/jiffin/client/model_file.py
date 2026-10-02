"""The model file: checked before every use, and downloaded from its pinned source when missing.

The installer does not ship the model (ADR-0015): it comes from the revision ADR-0006 pins, into
the `models` folder beside the database (ADR-0013), which the app gives. A download goes to
`<name>.part` and resumes from there, and the file takes its own name only once its size and
sha256 match the pin: a partial, truncated or wrong download is never loaded. Offline, the user
puts the file in the folder by hand, and it gets the same check.
"""

import contextlib
import hashlib
import http.client
import logging
import os
import re
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum, auto
from http import HTTPStatus
from pathlib import Path

log = logging.getLogger(__name__)

CHUNK = 1 << 20
"""Bytes read at a time, and between two progress reports."""
TIMEOUT_SECONDS = 30
"""Without a byte for this long, the download fails; the next call resumes it."""
RESERVE = 1 << 30
"""Free space left on the disk after the download, for the database and Windows to write."""


@dataclass(frozen=True, slots=True)
class PinnedFile:
    """A file at a fixed revision of its source, known by its size and sha256."""

    name: str
    url: str
    size: int
    sha256: str


_REVISION = "55633c8cbd2b826bd3eefdeb05310450996649df"
_NAME = "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
MODEL = PinnedFile(
    name=_NAME,
    url=f"https://huggingface.co/rizzoaiacademy/rizzo-flow/resolve/{_REVISION}/{_NAME}",
    size=2_600_224_416,
    sha256="79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54",
)
"""The judge of ADR-0006, Rizzo Flow 4B in Q4_K_M, at its pinned revision."""


class Phase(Enum):
    DOWNLOADING = auto()
    CHECKING = auto()
    """Reading the whole file for its sha256: 3.7 s for the model on the owner's machine."""


@dataclass(frozen=True, slots=True)
class Progress:
    """How far the download or the check has gone, in bytes."""

    phase: Phase
    done: int
    total: int


class Problem(Enum):
    NETWORK = auto()
    """No connection, an error from the server, an answer that is not the file, or a transfer
    cut short. What arrived is kept, and the next call resumes from there."""
    SPACE = auto()
    """The disk has no room for the rest of the download and the reserve."""
    DISK = auto()
    """The file or its folder cannot be read or written."""
    MISMATCH = auto()
    """The file is not the pinned one: its size or its sha256 differ. A download is deleted; a
    file under its own name, put there by hand, stays for the user to replace."""


class ModelFileError(Exception):
    """The model file cannot be had, or is not the pinned one."""

    def __init__(self, problem: Problem, detail: str, missing: int = 0) -> None:
        super().__init__(detail)
        self.problem = problem
        self.missing = missing
        """For SPACE: the bytes to free on the disk, for the interface to name."""


def ensure(file: PinnedFile, directory: Path, on_progress: Callable[[Progress], None]) -> Path:
    """The file in `directory`, checked; downloaded first when it is not there.

    It blocks until the download and the check end: call it on a thread of its own, one call
    at a time. `on_progress` is called on that thread. Raise ModelFileError when the file
    cannot be had, or is not the pinned one.
    """
    target = directory / file.name
    part = target.with_name(target.name + ".part")
    if target.exists():
        _check(target, file, on_progress)
        # A download left halfway before the file was put in place by hand.
        with contextlib.suppress(OSError):
            part.unlink(missing_ok=True)
        return target
    _download(file, part, on_progress)
    try:
        _check(part, file, on_progress)
    except ModelFileError as error:
        if error.problem is Problem.MISMATCH:
            with _disk(f"{part.name} cannot be deleted"):
                part.unlink()
        raise
    with _disk(f"{part.name} cannot be renamed"):
        part.replace(target)
    log.info("model downloaded and checked")
    return target


def _download(file: PinnedFile, part: Path, on_progress: Callable[[Progress], None]) -> None:
    """Bring `part` to the size of the file, from what it already holds."""
    with _disk("the models folder cannot be used"):
        part.parent.mkdir(parents=True, exist_ok=True)
        offset = part.stat().st_size if part.exists() else 0
        if offset > file.size:
            part.unlink()
            offset = 0
        free = shutil.disk_usage(part.parent).free
    if offset == file.size:  # it ended before its check
        return
    needed = file.size - offset + RESERVE
    if free < needed:
        raise ModelFileError(
            Problem.SPACE, f"{needed:,} bytes are needed, {free:,} are free", needed - free
        )
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    log.info("model download starts at byte %d of %d", offset, file.size)
    try:
        response = urllib.request.urlopen(
            urllib.request.Request(file.url, headers=headers), timeout=TIMEOUT_SECONDS
        )
    except urllib.error.HTTPError as error:
        error.close()
        raise ModelFileError(
            Problem.NETWORK, f"the server answered {error.code} {error.reason}"
        ) from None
    except (OSError, http.client.HTTPException) as error:
        raise ModelFileError(Problem.NETWORK, f"the server cannot be reached: {error}") from None
    with response:
        done = offset = _start(response, offset, file.size)
        with _disk(f"{part.name} cannot be written"), part.open("ab" if offset else "wb") as out:
            for chunk in _body(response, file.size - offset):
                out.write(chunk)
                done += len(chunk)
                on_progress(Progress(Phase.DOWNLOADING, done, file.size))
    if done < file.size:
        raise ModelFileError(
            Problem.NETWORK, f"the download stopped at byte {done:,} of {file.size:,}"
        )


_CONTENT_RANGE = re.compile(r"bytes (\d+)-\d+/(\d+)")


def _start(response: http.client.HTTPResponse, offset: int, size: int) -> int:
    """Where the body of `response` starts in the file.

    A server may ignore the range and send the whole file again. Any other answer, such as the
    login page of a public Wi-Fi, is refused before a byte is written, so the part stays as it
    was.
    """
    if response.status == HTTPStatus.PARTIAL_CONTENT:
        match = _CONTENT_RANGE.fullmatch(response.headers.get("Content-Range", ""))
        if match and int(match[1]) == offset and int(match[2]) == size:
            return offset
    elif response.status == HTTPStatus.OK and response.length == size:
        return 0
    raise ModelFileError(
        Problem.NETWORK,
        f"the server sent something else: status {response.status}, "
        f"Content-Range {response.headers.get('Content-Range')}, "
        f"Content-Length {response.length}",
    )


def _body(response: http.client.HTTPResponse, length: int) -> Iterator[bytes]:
    """The body of `response`, up to `length` bytes, until the server stops sending."""
    while length:
        try:
            chunk = response.read(min(CHUNK, length))
        except (OSError, http.client.HTTPException) as error:
            raise ModelFileError(Problem.NETWORK, f"the download broke off: {error}") from None
        if not chunk:  # the connection closed early: http.client does not raise
            return
        length -= len(chunk)
        yield chunk


def _check(path: Path, file: PinnedFile, on_progress: Callable[[Progress], None]) -> None:
    """Raise ModelFileError unless `path` has the size and the sha256 of the file."""
    digest = hashlib.sha256()
    buffer = bytearray(CHUNK)
    view = memoryview(buffer)
    with _disk(f"{path.name} cannot be read"), path.open("rb", buffering=0) as stream:
        size = os.fstat(stream.fileno()).st_size
        if size != file.size:
            raise ModelFileError(
                Problem.MISMATCH, f"{path.name} has {size:,} bytes, not {file.size:,}"
            )
        done = 0
        while count := stream.readinto(buffer):
            digest.update(view[:count])
            done += count
            on_progress(Progress(Phase.CHECKING, done, size))
    if digest.hexdigest() != file.sha256:
        raise ModelFileError(
            Problem.MISMATCH, f"{path.name} has sha256 {digest.hexdigest()}, not {file.sha256}"
        )


@contextlib.contextmanager
def _disk(action: str) -> Iterator[None]:
    """Turn an OSError into a ModelFileError; its message names no folder."""
    try:
        yield
    except OSError as error:
        raise ModelFileError(Problem.DISK, f"{action}: {error.strerror or error}") from None
