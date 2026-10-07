"""The model port: the judge and the rewriter, as `core` sees them (ADR-0012)."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from jiffin.core.context import Context


@dataclass(frozen=True, slots=True)
class EngineBuild:
    """What the scores depend on: part of the cache key, and recorded with them (ADR-0013)."""

    protocol: int
    engine_version: str
    llama_cpp_build: str
    model_sha256: str
    judge_prompt: int
    rewrite_prompt: int


class ModelError(Exception):
    """The model could not answer: no engine, or one that failed or took too long."""


class Need(Enum):
    """When `core` will ask the model next, as far as it knows: the client lets the engine sleep
    by it, which `core` does not know of (ADR-0027)."""

    SOON = auto()
    """A context waits for its 5 s, and some of its judgements are not in the cache or a
    statement must be written first."""
    NOT_NOW = auto()
    """A context is in front, and nothing it waits for needs the model."""
    NOTHING_IN_FRONT = auto()
    """Nothing is in front for the reminders: no context, or the pause from the tray."""


class Model(Protocol):
    def build(self) -> EngineBuild:
        """The build that answers `judge` and `rewrite`; ModelError when none has started."""
        ...

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        """Return d for every statement, by id."""
        ...

    def rewrite(self, condition: str) -> str:
        """Return the condition as one English statement (ADR-0008)."""
        ...
