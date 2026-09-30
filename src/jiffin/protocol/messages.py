"""The methods of the engine protocol, with their parameters and results (ADR-0011)."""

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

PROTOCOL_VERSION = 1
"""Raised on every incompatible change: `initialize` fails when app and engine differ."""

Text = Annotated[str, StringConstraints(min_length=1)]


class Strict(BaseModel):
    """A part of a message: exact types, no extra fields, finite numbers, immutable."""

    # Titles, addresses and reminder texts must never reach an error message or a log
    # (ADR-0013), so validation errors leave the input out.
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False, hide_input_in_errors=True
    )


class EngineSettings(Strict):
    context_per_question: int = Field(gt=0)
    """Tokens of context for each question."""
    micro_batch: int = Field(gt=0)
    """Questions decoded together."""
    load_mode: Literal["direct_io", "mmap"]
    kv_cache: Literal["f16"]


class InitializeParams(Strict):
    protocol: int
    model_path: Text
    settings: EngineSettings


class PromptVersions(Strict):
    judge: int = Field(ge=1)
    rewrite: int = Field(ge=1)


class InitializeResult(Strict):
    protocol: int
    engine_version: Text
    llama_cpp_build: Text
    gpu: Text
    free_vram_bytes: int = Field(ge=0)
    """Free once the model is loaded."""
    model_type: Text
    prompt_versions: PromptVersions


class Context(Strict):
    """A normalized context (ADR-0004)."""

    app: Text
    title: str
    address: Text | None
    """None outside the supported browsers, or when the address bar cannot be read."""


class Statement(Strict):
    id: int
    text: Text


class JudgeParams(Strict):
    context: Context
    statements: list[Statement] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        _require_unique([statement.id for statement in self.statements])
        return self


class Timings(Strict):
    total_seconds: float = Field(ge=0)
    """From receiving the request to sending the result."""


class Score(Strict):
    id: int
    d: float
    """logit("yes") − logit("no") (ADR-0006)."""


class JudgeResult(Strict):
    scores: list[Score] = Field(min_length=1)
    timings: Timings

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        _require_unique([score.id for score in self.scores])
        return self


class RewriteParams(Strict):
    condition: Text
    """The reminder's condition as the user wrote it, in Italian: "quando apro Figma"."""


class RewriteResult(Strict):
    statement: Text
    """The condition as one English statement (ADR-0008)."""
    prompt_version: int = Field(ge=1)
    timings: Timings


class ShutdownParams(Strict):
    """No parameters. The result is null; then the app closes stdin and the engine exits."""


@dataclass(frozen=True)
class Method[P: Strict, R: Strict | None]:
    name: str
    params: type[P]
    result: type[R]


INITIALIZE = Method("initialize", InitializeParams, InitializeResult)
JUDGE = Method("judge", JudgeParams, JudgeResult)
REWRITE = Method("rewrite", RewriteParams, RewriteResult)
SHUTDOWN = Method("shutdown", ShutdownParams, type(None))

METHODS: dict[str, Method[Any, Any]] = {
    method.name: method for method in (INITIALIZE, JUDGE, REWRITE, SHUTDOWN)
}


def _require_unique(ids: list[int]) -> None:
    if len(set(ids)) != len(ids):
        raise ValueError("ids must be unique")
