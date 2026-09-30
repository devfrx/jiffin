"""The JSON-RPC 2.0 messages of the engine protocol, and their strict reading (ADR-0011).

Every request has an id and gets one response: the protocol has no notifications and no
batches.
"""

from typing import Literal

from pydantic import Field, JsonValue, TypeAdapter, ValidationError

from jiffin.protocol.errors import Error, ErrorCode, ProtocolError
from jiffin.protocol.messages import METHODS, Strict


class Request[P: Strict](Strict):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int
    method: str
    params: P


class SuccessResponse[R: Strict | None](Strict):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int
    result: R


class ErrorResponse(Strict):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | None
    """None when the id of the request could not be read."""
    error: Error


# Lines are read into these first. Unlike the messages above, they require "jsonrpc", as
# JSON-RPC 2.0 does, and they leave params and results to the method.
class _RequestHead(Strict):
    jsonrpc: Literal["2.0"]
    id: int
    method: str
    params: dict[str, JsonValue] | list[JsonValue] = Field(default_factory=dict)


class _ResultHead(Strict):
    jsonrpc: Literal["2.0"]
    id: int
    result: JsonValue


class _ErrorHead(Strict):
    jsonrpc: Literal["2.0"]
    id: int | None
    error: Error


_RESPONSE_HEAD: TypeAdapter[_ResultHead | _ErrorHead] = TypeAdapter(_ResultHead | _ErrorHead)


def parse_request(line: bytes) -> Request[Strict]:
    """Read a request, or raise ProtocolError with the error the engine answers with."""
    try:
        head = _RequestHead.model_validate_json(line)
    except ValidationError as error:
        raise ProtocolError(_code(error, ErrorCode.INVALID_REQUEST), _describe(error)) from None
    method = METHODS.get(head.method)
    if method is None:
        raise ProtocolError(ErrorCode.METHOD_NOT_FOUND, f"no method {head.method!r}", head.id)
    try:
        params = method.params.model_validate(head.params)
    except ValidationError as error:
        raise ProtocolError(ErrorCode.INVALID_PARAMS, _describe(error), head.id) from None
    return Request(id=head.id, method=head.method, params=params)


def parse_response[R: Strict | None](
    line: bytes, result: type[R]
) -> SuccessResponse[R] | ErrorResponse:
    """Read the response to a request whose method returns `result`.

    Raise ProtocolError when the line is not such a response.
    """
    try:
        head = _RESPONSE_HEAD.validate_json(line)
    except ValidationError as error:
        raise ProtocolError(_code(error, ErrorCode.INVALID_REQUEST), _describe(error)) from None
    if isinstance(head, _ErrorHead):
        return ErrorResponse(id=head.id, error=head.error)
    try:
        value = TypeAdapter(result).validate_python(head.result)
    except ValidationError as error:
        raise ProtocolError(ErrorCode.INVALID_REQUEST, _describe(error), head.id) from None
    return SuccessResponse(id=head.id, result=value)


def _code(error: ValidationError, otherwise: ErrorCode) -> ErrorCode:
    invalid_json = any(detail["type"] == "json_invalid" for detail in error.errors())
    return ErrorCode.PARSE_ERROR if invalid_json else otherwise


def _describe(error: ValidationError) -> str:
    # Where and what, never the input: it may hold titles, addresses or reminder texts.
    return "; ".join(
        f"{'.'.join(map(str, detail['loc'])) or 'message'}: {detail['msg']}"
        for detail in error.errors(include_url=False, include_input=False)
    )
