"""The engine's statements and scores for a day, kept in the data folder: `replay --engine` and
`replay --reminders` judge the day once, and replay it at several thresholds from them
(ADR-0031).

The engine starts only for what is not kept yet: a statement by the remainder it rewrites, a
score by the context and the statement, as #106's script kept them
(`.handoff/archive/106/replay20.py`), whose files this reads. A file of another build of the
engine is refused: its scores would mix two judges.
"""

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import date
from pathlib import Path

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, Model
from jiffin.harness.errors import HarnessError

type Key = tuple[str, str, str | None, str]
"""A score's key: the context's app, title and address, and the statement."""


def path_for(folder: Path, day: date) -> Path:
    return folder / f"scores-{day.isoformat()}.json"


class Kept:
    """A model that answers from the kept statements and scores, and from the engine `start`
    gives for the rest, started at the first one missing."""

    def __init__(self, path: Path, start: Callable[[], Model]) -> None:
        self.path = path
        self._start = start
        self._engine: Model | None = None
        self._build: EngineBuild | None = None
        self._statements: dict[str, str] = {}
        self._d: dict[Key, float] = {}
        self._added = False
        if path.exists():
            self._load()

    def engine(self) -> Model:
        """The engine, started now if it is not yet: refused when its build is not the kept
        one."""
        if self._engine is None:
            engine = self._start()
            build = engine.build()
            if self._build is not None and build != self._build:
                raise HarnessError(
                    f"{self.path.name} keeps the scores of another build of the engine: "
                    "delete it to judge the day again"
                )
            self._engine, self._build = engine, build
        return self._engine

    def build(self) -> EngineBuild:
        return self.engine().build() if self._build is None else self._build

    def rewrite(self, condition: str) -> str:
        if condition not in self._statements:
            self._statements[condition] = self.engine().rewrite(condition)
            self._added = True
        return self._statements[condition]

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        missing = {i: text for i, text in statements.items() if _key(context, text) not in self._d}
        if missing:
            for i, d in self.engine().judge(context, missing).items():
                self._d[_key(context, missing[i])] = d
            self._added = True
        return {i: self._d[_key(context, text)] for i, text in statements.items()}

    def save(self) -> None:
        """Write what is kept, when the engine added anything."""
        if not self._added or self._build is None:
            return
        record = {
            "build": asdict(self._build),
            "statements": self._statements,
            "scores": [[*key, d] for key, d in sorted(self._d.items(), key=_order)],
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
        self._added = False

    def _load(self) -> None:
        try:
            kept = json.loads(self.path.read_text(encoding="utf-8"))
            self._build = EngineBuild(**kept["build"])
            self._statements = dict(kept["statements"])
            self._d = {
                (app, title, address, statement): float(d)
                for app, title, address, statement, d in kept["scores"]
            }
        except OSError as error:
            raise HarnessError(f"the kept scores cannot be read: {error.strerror}") from None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise HarnessError(f"{self.path.name} holds no kept scores: {error}") from None


def _key(context: Context, statement: str) -> Key:
    return context.app, context.title, context.address, statement


def _order(item: tuple[Key, float]) -> list[str]:
    return [part or "" for part in item[0]]
