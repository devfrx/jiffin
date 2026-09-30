"""The errors of the engine protocol: JSON-RPC's own codes and five more (ADR-0011)."""

from enum import IntEnum
from typing import Self

from jiffin.protocol.messages import Strict, Text


class ErrorCode(IntEnum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    NOT_INITIALIZED = -32001
    PROTOCOL_MISMATCH = -32002
    MODEL_NOT_LOADABLE = -32003
    GPU_OUT_OF_MEMORY = -32004
    TEXT_TOO_LONG = -32005


_MESSAGES = {
    ErrorCode.PARSE_ERROR: "Parse error",
    ErrorCode.INVALID_REQUEST: "Invalid Request",
    ErrorCode.METHOD_NOT_FOUND: "Method not found",
    ErrorCode.INVALID_PARAMS: "Invalid params",
    ErrorCode.INTERNAL_ERROR: "Internal error",
    ErrorCode.NOT_INITIALIZED: "Not initialized",
    ErrorCode.PROTOCOL_MISMATCH: "Protocol mismatch",
    ErrorCode.MODEL_NOT_LOADABLE: "Model cannot be loaded",
    ErrorCode.GPU_OUT_OF_MEMORY: "GPU out of memory",
    ErrorCode.TEXT_TOO_LONG: "Text too long for the context",
}


class ErrorData(Strict):
    detail: Text
    retry: bool
    """Whether sending the same request again may succeed."""


class Error(Strict):
    code: ErrorCode
    message: Text
    data: ErrorData

    @classmethod
    def of(cls, code: ErrorCode, detail: str, *, retry: bool) -> Self:
        return cls(code=code, message=_MESSAGES[code], data=ErrorData(detail=detail, retry=retry))


class ProtocolError(Exception):
    """A line that is not a valid message. The engine answers with `error` and reads on."""

    def __init__(self, code: ErrorCode, detail: str, request_id: int | None = None) -> None:
        super().__init__(f"{_MESSAGES[code]}: {detail}")
        self.error = Error.of(code, detail, retry=False)
        self.request_id = request_id
