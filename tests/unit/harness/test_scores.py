import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, Model
from jiffin.harness import scores
from jiffin.harness.errors import HarnessError

DAY = date(2026, 10, 5)
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
MAIL = Context("outlook.exe", "Posta in arrivo", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")


class Engine:
    """Writes "The user: …" and scores by the length of the statement, counting its answers."""

    def __init__(self, build: EngineBuild = BUILD) -> None:
        self._build = build
        self.asked: list[str] = []

    def build(self) -> EngineBuild:
        return self._build

    def rewrite(self, condition: str) -> str:
        self.asked.append(condition)
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        self.asked += statements.values()
        return {key: len(text) / 10 for key, text in statements.items()}


def no_engine() -> Model:
    raise AssertionError("the engine started")


def test_the_engine_answers_only_what_is_not_kept(tmp_path: Path) -> None:
    path = scores.path_for(tmp_path, DAY)
    engine = Engine()
    kept = scores.Kept(path, lambda: engine)
    statement = kept.rewrite("quando leggo la posta")
    assert kept.judge(MAIL, {1: statement}) == {1: 3.2}
    assert kept.judge(MAIL, {2: statement, 3: "The user: pays."}) == {2: 3.2, 3: 1.5}
    assert kept.rewrite("quando leggo la posta") == statement
    assert engine.asked == ["quando leggo la posta", statement, "The user: pays."]
    kept.save()

    again = scores.Kept(path, no_engine)
    assert again.build() == BUILD
    assert again.rewrite("quando leggo la posta") == statement
    assert again.judge(MAIL, {7: statement}) == {7: 3.2}


def test_the_engine_starts_at_the_first_score_missing(tmp_path: Path) -> None:
    path = scores.path_for(tmp_path, DAY)
    first = scores.Kept(path, Engine)
    first.judge(MAIL, {1: "The user: reads."})
    first.save()
    engine = Engine()
    kept = scores.Kept(path, lambda: engine)
    assert kept.judge(MAIL, {1: "The user: reads."}) == {1: 1.6}
    assert engine.asked == []
    assert kept.judge(BANK, {1: "The user: reads."}) == {1: 1.6}  # another context
    assert engine.asked == ["The user: reads."]


def test_the_scores_of_another_build_are_refused(tmp_path: Path) -> None:
    path = scores.path_for(tmp_path, DAY)
    first = scores.Kept(path, Engine)
    first.judge(MAIL, {1: "The user: reads."})
    first.save()
    rebuilt = scores.Kept(path, lambda: Engine(replace(BUILD, judge_prompt=2)))
    with pytest.raises(HarnessError, match="scores-2026-10-05.json keeps the scores of another"):
        rebuilt.judge(BANK, {1: "The user: reads."})


def test_nothing_is_written_when_the_engine_added_nothing(tmp_path: Path) -> None:
    path = scores.path_for(tmp_path, DAY)
    scores.Kept(path, no_engine).save()
    assert not path.exists()


def test_the_files_of_106s_script_are_read(tmp_path: Path) -> None:
    """`.handoff/archive/106/replay20.py` kept the same record, without a format."""
    path = scores.path_for(tmp_path, DAY)
    record = {
        "build": {
            "protocol": 1,
            "engine_version": "0.1.0",
            "llama_cpp_build": "b11081",
            "model_sha256": "79de5cb8",
            "judge_prompt": 1,
            "rewrite_prompt": 2,
        },
        "statements": {"se sono sul sito della banca": "The user is on a bank's site."},
        "scores": [
            ["vivaldi.exe", "Banca Rossi", "bancarossi.it", "The user is on a bank's site.", 2.25]
        ],
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    kept = scores.Kept(path, no_engine)
    assert kept.build() == BUILD
    statement = kept.rewrite("se sono sul sito della banca")
    assert kept.judge(BANK, {5: statement}) == {5: 2.25}


def test_a_file_that_keeps_no_scores_is_refused(tmp_path: Path) -> None:
    path = scores.path_for(tmp_path, DAY)
    path.write_text('{"build": {}}', encoding="utf-8")
    with pytest.raises(HarnessError, match="holds no kept scores"):
        scores.Kept(path, no_engine)
