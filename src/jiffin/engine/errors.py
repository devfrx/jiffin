"""The failures the engine reports to the app, each with its protocol code (ADR-0011).

The message is the error's detail: it names files, sizes and ids, never the text of a context
or of a statement.
"""

from typing import ClassVar

from jiffin.protocol.errors import Error, ErrorCode


class EngineError(Exception):
    code: ClassVar[ErrorCode]
    retry: ClassVar[bool] = False
    """Whether sending the same request again may succeed."""

    def error(self) -> Error:
        return Error.of(self.code, str(self), retry=self.retry)


class MethodNotFound(EngineError):
    code = ErrorCode.METHOD_NOT_FOUND


class NotInitialized(EngineError):
    code = ErrorCode.NOT_INITIALIZED


class ProtocolMismatch(EngineError):
    code = ErrorCode.PROTOCOL_MISMATCH


class ModelNotLoadable(EngineError):
    code = ErrorCode.MODEL_NOT_LOADABLE


class GpuOutOfMemory(EngineError):
    code = ErrorCode.GPU_OUT_OF_MEMORY
    # The memory may be free again once another program releases it.
    retry = True


class TextTooLong(EngineError):
    code = ErrorCode.TEXT_TOO_LONG
