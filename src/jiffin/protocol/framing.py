"""One message per line, in UTF-8, on binary pipes (ADR-0011)."""

from typing import IO, Any

from jiffin.protocol.errors import ErrorCode, ProtocolError
from jiffin.protocol.jsonrpc import ErrorResponse, Request, SuccessResponse

MAX_LINE_BYTES = 1 << 20
"""Far above any real message: a longer line is refused, not buffered."""


def read_line(stream: IO[bytes]) -> bytes | None:
    """Return the next line without its newline, or None once the stream has ended.

    A line that is too long is skipped up to its newline, so that reading can go on.
    """
    line = stream.readline(MAX_LINE_BYTES + 1)
    if line.endswith(b"\n"):
        return line[:-1]
    if not line:
        return None
    if len(line) <= MAX_LINE_BYTES:
        raise ProtocolError(ErrorCode.PARSE_ERROR, "the stream ended inside a message")
    while (rest := stream.readline(MAX_LINE_BYTES)) and not rest.endswith(b"\n"):
        pass
    raise ProtocolError(ErrorCode.PARSE_ERROR, f"a message is longer than {MAX_LINE_BYTES} bytes")


def write_message(
    stream: IO[bytes], message: Request[Any] | SuccessResponse[Any] | ErrorResponse
) -> None:
    """Write one message and flush it.

    Raise ValueError, writing nothing, for a message the other side could not read: too long,
    or with text that is not valid Unicode.
    """
    line = message.model_dump_json().encode()
    if len(line) > MAX_LINE_BYTES:
        raise ValueError(f"a message is longer than {MAX_LINE_BYTES} bytes")
    stream.write(line + b"\n")
    stream.flush()
