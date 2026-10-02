import contextlib
import errno
import hashlib
import random
import re
import shutil
import threading
from collections.abc import Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Self

import pytest

from jiffin.client import model_file
from jiffin.client.model_file import (
    CHUNK,
    ModelFileError,
    Phase,
    PinnedFile,
    Problem,
    Progress,
    ensure,
)

DATA = random.Random(39).randbytes(3 * CHUNK + 1000)
"""The fake model: three chunks and a bit."""
STEPS = [CHUNK, 2 * CHUNK, 3 * CHUNK, len(DATA)]
"""The progress after each chunk."""
CUT = CHUNK + CHUNK // 2
"""Where a cut transfer stops: in the middle of a chunk."""


class Source:
    """A local HTTP server with one file, which misbehaves on cue."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.honours_ranges = True
        """Without, it sends the whole file whatever the range."""
        self.shift = 0
        """How far from the start it was asked for its ranges begin."""
        self.cut: int | None = None
        """How many bytes of the body it sends before it closes the connection."""
        self.stalls = False
        """After those bytes, it goes silent until it closes, or for 10 s at most."""
        self.closed = threading.Event()
        """Set when it closes: a silent answer ends then."""
        self.error: HTTPStatus | None = None
        """What it answers instead of the file."""
        self.ranges: list[str | None] = []
        """The Range header of every request, None when it had none."""
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}/model.gguf"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.closed.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


def _handler(source: Source) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            header = self.headers.get("Range")
            source.ranges.append(header)
            if source.error is not None:
                self.send_error(source.error)
                return
            match = re.fullmatch(r"bytes=(\d+)-", header or "")
            start = int(match[1]) + source.shift if match and source.honours_ranges else 0
            size = len(source.data)
            if start:
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
            else:
                self.send_response(HTTPStatus.OK)
            body = source.data[start:]
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(ConnectionError):  # a client that stopped reading
                self.wfile.write(body[: source.cut])
            if source.stalls:
                source.closed.wait(10)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


@pytest.fixture
def source() -> Iterator[Source]:
    with Source(DATA) as source:
        yield source


def pin(url: str) -> PinnedFile:
    """The fake model, pinned at `url`."""
    return PinnedFile("model.gguf", url, len(DATA), hashlib.sha256(DATA).hexdigest())


def failure(file: PinnedFile, directory: Path) -> ModelFileError:
    with pytest.raises(ModelFileError) as caught:
        ensure(file, directory, lambda progress: None)
    return caught.value


def test_a_missing_file_is_downloaded_checked_and_named(tmp_path: Path, source: Source) -> None:
    progress: list[Progress] = []
    path = ensure(pin(source.url), tmp_path, progress.append)
    assert path == tmp_path / "model.gguf"
    assert path.read_bytes() == DATA
    assert [child.name for child in tmp_path.iterdir()] == ["model.gguf"]
    assert source.ranges == [None]
    assert progress == [Progress(Phase.DOWNLOADING, done, len(DATA)) for done in STEPS] + [
        Progress(Phase.CHECKING, done, len(DATA)) for done in STEPS
    ]


def test_a_cut_transfer_is_never_used_and_resumes_where_it_stopped(
    tmp_path: Path, source: Source
) -> None:
    source.cut = CUT
    assert failure(pin(source.url), tmp_path).problem is Problem.NETWORK
    assert [child.name for child in tmp_path.iterdir()] == ["model.gguf.part"]
    assert (tmp_path / "model.gguf.part").read_bytes() == DATA[:CUT]
    source.cut = None
    progress: list[Progress] = []
    assert ensure(pin(source.url), tmp_path, progress.append).read_bytes() == DATA
    assert source.ranges == [None, f"bytes={CUT}-"]
    assert progress[0] == Progress(Phase.DOWNLOADING, CUT + CHUNK, len(DATA))


def test_a_stalled_transfer_fails_in_time_and_keeps_what_arrived(
    tmp_path: Path, source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(model_file, "TIMEOUT_SECONDS", 0.2)
    source.cut = CUT
    source.stalls = True
    error = failure(pin(source.url), tmp_path)
    assert error.problem is Problem.NETWORK
    assert "timed out" in str(error)
    kept = (tmp_path / "model.gguf.part").read_bytes()
    assert CHUNK <= len(kept) <= CUT
    assert DATA.startswith(kept)
    source.stalls = False
    source.cut = None
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA
    assert source.ranges == [None, f"bytes={len(kept)}-"]


def test_a_server_that_ignores_the_range_sends_the_file_again(
    tmp_path: Path, source: Source
) -> None:
    (tmp_path / "model.gguf.part").write_bytes(DATA[:CUT])
    source.honours_ranges = False
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA
    assert source.ranges == [f"bytes={CUT}-"]


def test_a_download_whose_check_cannot_end_stays_a_part(tmp_path: Path, source: Source) -> None:
    def unplug(progress: Progress) -> None:
        if progress.phase is Phase.CHECKING:  # the disk fails in the middle of the check
            raise OSError(errno.EIO, "the disk stopped answering")

    with pytest.raises(ModelFileError) as caught:
        ensure(pin(source.url), tmp_path, unplug)
    assert caught.value.problem is Problem.DISK
    assert [child.name for child in tmp_path.iterdir()] == ["model.gguf.part"]
    assert (tmp_path / "model.gguf.part").read_bytes() == DATA
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA
    assert source.ranges == [None]


def test_a_download_with_another_sha256_is_deleted(tmp_path: Path) -> None:
    with Source(bytes(len(DATA))) as wrong:
        assert failure(pin(wrong.url), tmp_path).problem is Problem.MISMATCH
    assert list(tmp_path.iterdir()) == []


def test_an_answer_that_is_not_the_file_leaves_the_part_alone(tmp_path: Path) -> None:
    part = tmp_path / "model.gguf.part"
    part.write_bytes(DATA[:CUT])
    with Source(b"<html>Sign in to the Wi-Fi</html>") as portal:
        portal.honours_ranges = False
        assert failure(pin(portal.url), tmp_path).problem is Problem.NETWORK
    with Source(DATA + b"and more") as longer:
        assert failure(pin(longer.url), tmp_path).problem is Problem.NETWORK
    with Source(DATA) as shifted:
        shifted.shift = -1
        assert failure(pin(shifted.url), tmp_path).problem is Problem.NETWORK
    assert part.read_bytes() == DATA[:CUT]


@pytest.mark.parametrize("error", [HTTPStatus.NOT_FOUND, HTTPStatus.SERVICE_UNAVAILABLE])
def test_an_error_from_the_server_keeps_the_part(
    tmp_path: Path, source: Source, error: HTTPStatus
) -> None:
    part = tmp_path / "model.gguf.part"
    part.write_bytes(DATA[:CUT])
    source.error = error
    assert failure(pin(source.url), tmp_path).problem is Problem.NETWORK
    assert part.read_bytes() == DATA[:CUT]


def test_without_a_server_the_download_fails(tmp_path: Path) -> None:
    with Source(DATA) as source:
        url = source.url
    assert failure(pin(url), tmp_path).problem is Problem.NETWORK


def test_a_complete_part_is_checked_without_a_download(tmp_path: Path, source: Source) -> None:
    (tmp_path / "model.gguf.part").write_bytes(DATA)
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA
    assert source.ranges == []


def test_a_part_longer_than_the_file_starts_again(tmp_path: Path, source: Source) -> None:
    (tmp_path / "model.gguf.part").write_bytes(DATA + b"and more")
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA
    assert source.ranges == [None]


def test_the_right_file_put_in_place_by_hand_is_checked_and_used(
    tmp_path: Path, source: Source
) -> None:
    (tmp_path / "model.gguf").write_bytes(DATA)
    (tmp_path / "model.gguf.part").write_bytes(DATA[:CUT])  # a download given up on
    progress: list[Progress] = []
    assert ensure(pin(source.url), tmp_path, progress.append) == tmp_path / "model.gguf"
    assert progress == [Progress(Phase.CHECKING, done, len(DATA)) for done in STEPS]
    assert source.ranges == []
    assert [child.name for child in tmp_path.iterdir()] == ["model.gguf"]


@pytest.mark.parametrize("data", [DATA[:-1], bytes(len(DATA))], ids=["shorter", "other bytes"])
def test_a_wrong_file_put_in_place_by_hand_is_refused_and_kept(
    tmp_path: Path, source: Source, data: bytes
) -> None:
    (tmp_path / "model.gguf").write_bytes(data)
    assert failure(pin(source.url), tmp_path).problem is Problem.MISMATCH
    assert (tmp_path / "model.gguf").read_bytes() == data
    assert source.ranges == []


def test_a_download_needs_room_for_the_rest_and_a_reserve(
    tmp_path: Path, source: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "model.gguf.part").write_bytes(DATA[:CUT])
    usage = shutil.disk_usage(tmp_path)
    needed = len(DATA) - CUT + model_file.RESERVE
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage._replace(free=needed - 1000))
    error = failure(pin(source.url), tmp_path)
    assert (error.problem, error.missing) == (Problem.SPACE, 1000)
    assert source.ranges == []
    monkeypatch.setattr(shutil, "disk_usage", lambda path: usage._replace(free=needed))
    assert ensure(pin(source.url), tmp_path, lambda progress: None).read_bytes() == DATA


def test_a_folder_that_cannot_be_used_is_a_disk_problem_named_without_its_path(
    tmp_path: Path, source: Source
) -> None:
    folder = tmp_path / "private-folder"
    folder.touch()  # a file where the folder should be
    error = failure(pin(source.url), folder)
    assert error.problem is Problem.DISK
    assert "private-folder" not in str(error)
    assert source.ranges == []
