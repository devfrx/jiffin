import io

import pytest

from jiffin.protocol.errors import ErrorCode, ProtocolError
from jiffin.protocol.framing import MAX_LINE_BYTES, read_line, write_message
from jiffin.protocol.jsonrpc import Request
from jiffin.protocol.messages import (
    Context,
    JudgeParams,
    RewriteParams,
    ShutdownParams,
    Statement,
)


def test_messages_are_read_back_one_per_line() -> None:
    stream = io.BytesIO()
    first = Request(id=1, method="rewrite", params=RewriteParams(condition="quando apro Figma"))
    second = Request(id=2, method="shutdown", params=ShutdownParams())
    write_message(stream, first)
    write_message(stream, second)
    stream.seek(0)
    assert read_line(stream) == first.model_dump_json().encode()
    assert read_line(stream) == second.model_dump_json().encode()
    assert read_line(stream) is None


def test_a_message_is_one_line_of_utf8() -> None:
    stream = io.BytesIO()
    condition = "quando scrivo il perché\ndel progetto"
    write_message(
        stream, Request(id=1, method="rewrite", params=RewriteParams(condition=condition))
    )
    line = stream.getvalue()
    assert line.count(b"\n") == 1
    assert line.endswith(b"\n")
    assert "perché".encode() in line


def test_every_message_is_flushed() -> None:
    class Pipe(io.BytesIO):
        flushed = 0

        def flush(self) -> None:
            self.flushed += 1

    pipe = Pipe()
    write_message(pipe, Request(id=1, method="shutdown", params=ShutdownParams()))
    assert pipe.flushed == 1


# Windows titles are UTF-16 and may end halfway through an emoji: a lone surrogate.
@pytest.mark.parametrize(
    "title", ["x" * MAX_LINE_BYTES, "Progetto Rossi \ud83d"], ids=["too long", "broken unicode"]
)
def test_unreadable_messages_are_not_written(title: str) -> None:
    stream = io.BytesIO()
    params = JudgeParams(
        context=Context(app="code", title=title, address=None),
        statements=[Statement(id=1, text="The user is working on the Rossi project.")],
    )
    with pytest.raises(ValueError):
        write_message(stream, Request(id=1, method="judge", params=params))
    assert stream.getvalue() == b""


def test_a_line_of_the_maximum_length_is_read() -> None:
    line = b"x" * MAX_LINE_BYTES
    assert read_line(io.BytesIO(line + b"\n")) == line


def test_a_longer_line_is_skipped_and_reading_goes_on() -> None:
    stream = io.BytesIO(b"x" * (MAX_LINE_BYTES + 1) + b"\n" + b"next\n")
    with pytest.raises(ProtocolError) as caught:
        read_line(stream)
    assert caught.value.error.code == ErrorCode.PARSE_ERROR
    assert read_line(stream) == b"next"


def test_a_longer_line_at_the_end_of_the_stream() -> None:
    stream = io.BytesIO(b"x" * (2 * MAX_LINE_BYTES + 5))
    with pytest.raises(ProtocolError):
        read_line(stream)
    assert read_line(stream) is None


def test_a_stream_ending_inside_a_message() -> None:
    stream = io.BytesIO(b'{"jsonrpc":"2.0","id":1,')
    with pytest.raises(ProtocolError, match="ended inside a message"):
        read_line(stream)
    assert read_line(stream) is None
