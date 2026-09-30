from typing import Any

import pytest

from jiffin.protocol.errors import Error, ErrorCode, ProtocolError
from jiffin.protocol.jsonrpc import (
    ErrorResponse,
    Request,
    SuccessResponse,
    parse_request,
    parse_response,
)
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
    Score,
    ShutdownParams,
    Statement,
    Strict,
    Timings,
)

CALLS: list[tuple[Method[Any, Any], Strict, Strict | None]] = [
    (
        INITIALIZE,
        InitializeParams(
            protocol=PROTOCOL_VERSION,
            model_path="C:\\Users\\utente\\AppData\\Local\\Jiffin\\models\\rizzo-flow.gguf",
            settings=EngineSettings(
                context_per_question=2048, micro_batch=16, load_mode="direct_io", kv_cache="f16"
            ),
        ),
        InitializeResult(
            protocol=PROTOCOL_VERSION,
            engine_version="0.1.0",
            llama_cpp_build="b11081",
            gpu="NVIDIA GeForce RTX 4060 Laptop GPU",
            free_vram_bytes=4_831_838_208,
            model_type="spark2_5 4B Q4_K - Medium",
            prompt_versions=PromptVersions(judge=1, rewrite=2),
        ),
    ),
    (
        JUDGE,
        JudgeParams(
            context=Context(
                app="vivaldi", title="Progetto Rossi – changelog", address="github.com/rossi/app"
            ),
            statements=[
                Statement(id=3, text="The user is working on the Rossi project."),
                Statement(id=8, text="The user is on the bank's website."),
            ],
        ),
        JudgeResult(
            scores=[Score(id=3, d=4.25), Score(id=8, d=-7.5)], timings=Timings(total_seconds=0.498)
        ),
    ),
    (
        REWRITE,
        RewriteParams(condition="quando lavoro al progetto Rossi"),
        RewriteResult(
            statement="The user is working on the Rossi project.",
            prompt_version=2,
            timings=Timings(total_seconds=0.81),
        ),
    ),
    (SHUTDOWN, ShutdownParams(), None),
]
CALL_IDS = [method.name for method, _, _ in CALLS]


@pytest.mark.parametrize(("method", "params", "result"), CALLS, ids=CALL_IDS)
def test_requests_round_trip(method: Method[Any, Any], params: Strict, result: object) -> None:
    request = Request(id=41, method=method.name, params=params)
    assert parse_request(request.model_dump_json().encode()) == request


@pytest.mark.parametrize(("method", "params", "result"), CALLS, ids=CALL_IDS)
def test_results_round_trip(
    method: Method[Any, Any], params: Strict, result: Strict | None
) -> None:
    response = SuccessResponse(id=41, result=result)
    assert parse_response(response.model_dump_json().encode(), method.result) == response


@pytest.mark.parametrize("code", list(ErrorCode))
def test_errors_round_trip(code: ErrorCode) -> None:
    response = ErrorResponse(id=41, error=Error.of(code, "what went wrong", retry=True))
    assert parse_response(response.model_dump_json().encode(), JudgeResult) == response


def test_an_error_without_a_request_id_round_trips() -> None:
    response = ErrorResponse(id=None, error=Error.of(ErrorCode.PARSE_ERROR, "bad", retry=False))
    assert parse_response(response.model_dump_json().encode(), JudgeResult) == response


def test_the_shutdown_result_is_null() -> None:
    assert SuccessResponse(id=1, result=None).model_dump_json() == (
        '{"jsonrpc":"2.0","id":1,"result":null}'
    )


def test_params_may_be_left_out_when_there_are_none() -> None:
    request = parse_request(b'{"jsonrpc":"2.0","id":5,"method":"shutdown"}')
    assert request.params == ShutdownParams()


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b"", ErrorCode.PARSE_ERROR),
        (b'{"jsonrpc":"2.0",', ErrorCode.PARSE_ERROR),
        (
            b'{"jsonrpc":"2.0","id":1,"method":"rewrite","params":{"condition":"\xff"}}',
            ErrorCode.PARSE_ERROR,
        ),
        (b'\xef\xbb\xbf{"jsonrpc":"2.0","id":1,"method":"shutdown"}', ErrorCode.PARSE_ERROR),
        (b"[]", ErrorCode.INVALID_REQUEST),
        (b'[{"jsonrpc":"2.0","id":1,"method":"shutdown"}]', ErrorCode.INVALID_REQUEST),
        (b'{"id":1,"method":"shutdown"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"1.0","id":1,"method":"shutdown"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","method":"shutdown"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":"1","method":"shutdown"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":1.0,"method":"shutdown"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":1,"method":"shutdown","params":null}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":1,"method":"shutdown","params":"now"}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":1,"method":"shutdown","extra":0}', ErrorCode.INVALID_REQUEST),
    ],
)
def test_unreadable_requests_are_answered_without_an_id(line: bytes, code: ErrorCode) -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request(line)
    assert caught.value.error.code == code
    assert caught.value.request_id is None


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b'{"jsonrpc":"2.0","id":7,"method":"judgment","params":{}}', ErrorCode.METHOD_NOT_FOUND),
        (b'{"jsonrpc":"2.0","id":7,"method":"rewrite"}', ErrorCode.INVALID_PARAMS),
        (b'{"jsonrpc":"2.0","id":7,"method":"rewrite","params":{}}', ErrorCode.INVALID_PARAMS),
        (
            b'{"jsonrpc":"2.0","id":7,"method":"rewrite","params":["quando"]}',
            ErrorCode.INVALID_PARAMS,
        ),
        (
            b'{"jsonrpc":"2.0","id":7,"method":"shutdown","params":{"now":true}}',
            ErrorCode.INVALID_PARAMS,
        ),
    ],
)
def test_request_errors_carry_the_request_id(line: bytes, code: ErrorCode) -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_request(line)
    assert caught.value.error.code == code
    assert caught.value.request_id == 7


def test_protocol_errors_are_not_worth_retrying() -> None:
    error = ProtocolError(ErrorCode.INVALID_PARAMS, "condition: Field required", 7).error
    assert error == Error.of(ErrorCode.INVALID_PARAMS, "condition: Field required", retry=False)
    assert error.message == "Invalid params"


def test_error_details_leave_the_input_out() -> None:
    line = b'{"jsonrpc":"2.0","id":7,"method":"rewrite","params":{"condition":["progetto Rossi"]}}'
    with pytest.raises(ProtocolError) as caught:
        parse_request(line)
    assert caught.value.error.data.detail == "condition: Input should be a valid string"
    assert "Rossi" not in str(caught.value)


ERROR = '{"code":-32603,"message":"Internal error","data":{"detail":"x","retry":false}}'


@pytest.mark.parametrize(
    ("line", "code"),
    [
        (b'{"jsonrpc":"2.0","id":7,"result":', ErrorCode.PARSE_ERROR),
        (b'{"id":7,"result":{}}', ErrorCode.INVALID_REQUEST),
        (b'{"jsonrpc":"2.0","id":7}', ErrorCode.INVALID_REQUEST),
        (
            f'{{"jsonrpc":"2.0","id":7,"result":null,"error":{ERROR}}}'.encode(),
            ErrorCode.INVALID_REQUEST,
        ),
        (
            b'{"jsonrpc":"2.0","id":7,"error":{"code":-1,"message":"x","data":{"detail":"x","retry":false}}}',
            ErrorCode.INVALID_REQUEST,
        ),
        (
            b'{"jsonrpc":"2.0","id":7,"result":{"statement":"The user is at work."}}',
            ErrorCode.INVALID_REQUEST,
        ),
    ],
)
def test_unreadable_responses_are_refused(line: bytes, code: ErrorCode) -> None:
    with pytest.raises(ProtocolError) as caught:
        parse_response(line, RewriteResult)
    assert caught.value.error.code == code


def test_a_result_must_be_the_one_of_the_method() -> None:
    with pytest.raises(ProtocolError):
        parse_response(b'{"jsonrpc":"2.0","id":7,"result":{}}', SHUTDOWN.result)
