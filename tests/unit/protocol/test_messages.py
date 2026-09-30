import pytest
from pydantic import ValidationError

from jiffin.protocol.messages import (
    Context,
    EngineSettings,
    JudgeParams,
    JudgeResult,
    Score,
    Statement,
    Timings,
)

CONTEXT = Context(app="code", title="changelog.md - rossi", address=None)


def test_statement_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="ids must be unique"):
        JudgeParams(
            context=CONTEXT,
            statements=[Statement(id=1, text="a"), Statement(id=1, text="b")],
        )


def test_score_ids_are_unique() -> None:
    with pytest.raises(ValidationError, match="ids must be unique"):
        JudgeResult(
            scores=[Score(id=1, d=1.0), Score(id=1, d=2.0)], timings=Timings(total_seconds=0.1)
        )


def test_a_judgement_needs_a_statement() -> None:
    with pytest.raises(ValidationError):
        JudgeParams(context=CONTEXT, statements=[])


@pytest.mark.parametrize("d", [float("nan"), float("inf"), float("-inf")])
def test_scores_are_finite(d: float) -> None:
    with pytest.raises(ValidationError):
        Score(id=1, d=d)


@pytest.mark.parametrize(
    "data",
    [
        {"id": "1", "text": "a"},
        {"id": True, "text": "a"},
        {"id": 1.0, "text": "a"},
        {"id": 1, "text": ""},
        {"id": 1, "text": "a", "extra": 0},
    ],
)
def test_statements_take_exact_types(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Statement.model_validate(data)


def test_a_context_may_have_no_address_but_not_an_empty_one() -> None:
    assert Context(app="code", title="", address=None).address is None
    with pytest.raises(ValidationError):
        Context(app="code", title="", address="")


@pytest.mark.parametrize(
    "change",
    [{"load_mode": "fast"}, {"kv_cache": "q8_0"}, {"micro_batch": 0}, {"context_per_question": 0}],
)
def test_engine_settings_take_known_values(change: dict[str, object]) -> None:
    settings = {"context_per_question": 2048, "micro_batch": 16, "load_mode": "direct_io"}
    with pytest.raises(ValidationError):
        EngineSettings.model_validate({**settings, "kv_cache": "f16", **change})


def test_validation_errors_leave_the_input_out() -> None:
    with pytest.raises(ValidationError) as caught:
        Context.model_validate({"app": "vivaldi", "title": ["Banca Rossi"], "address": None})
    assert "Banca Rossi" not in str(caught.value)
