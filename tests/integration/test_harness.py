"""The harness on the owner's machine, with the private sample and the real engine (ADR-0017).

Run with `uv run pytest -m integration`. The sample and the model come from the `NO_GIT` folder
beside the repository, and a test skips when what it needs is missing. Only numbers reach the
output.
"""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from jiffin.core.clock import SystemClock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.harness import __main__ as harness
from jiffin.harness import capture, folders, metrics, replay, sample, snapshot
from jiffin.harness import day as days

pytestmark = pytest.mark.integration

MODEL = folders.NO_GIT / "rizzo-flow" / "models" / "rizzo-flow"
MEASURED = folders.NO_GIT / "sibyl-misura" / "risultati" / "riscrittura-rizzo-q4-v2.jsonl"


def test_the_metrics_give_the_prototypes_numbers_on_its_measurement() -> None:
    """The d the prototype measured with the v2 statements, and its table (devfrx/sibyl#26)."""
    if not (folders.SAMPLE.is_file() and MEASURED.is_file()):
        pytest.skip(f"the private sample is not in {folders.NO_GIT}")
    labelled = sample.load(folders.SAMPLE)
    measured = {
        (row["ctx"], row["rem"]): row["d"]
        for row in map(json.loads, MEASURED.read_text(encoding="utf-8").splitlines())
        if row["ordine"] == "sa" and row["ctx"] != "__vuoto__"
    }
    d = [
        [measured[(context, reminder)] for reminder in labelled.reminder_ids]
        for context in labelled.context_ids
    ]
    relevant = labelled.relevant
    assert round(metrics.auroc(metrics.flat(d), metrics.flat(relevant)), 3) == 0.986
    recalls = [
        round(metrics.best_within(d, relevant, budget).recall, 2) for budget in sample.BUDGETS
    ]
    assert recalls == [0.75, 0.81, 0.89]
    at = metrics.at_threshold(d, relevant, 0.97)
    assert (round(at.recall, 2), round(at.false_alarms, 3)) == (0.86, 0.142)


def test_the_sample_through_the_engine(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    if not (folders.SAMPLE.is_file() and MODEL.is_dir()):
        pytest.skip(f"the private sample or the model is not in {folders.NO_GIT}")
    assert harness.main(["sample", "--data", str(tmp_path), "--models", str(MODEL)]) == 0
    print(capsys.readouterr().out)
    (saved,) = tmp_path.glob("sample-*.json")
    d = json.loads(saved.read_text(encoding="utf-8"))["d"]
    assert [len(row) for row in d] == [9] * 106


CAPTURE = folders.NO_GIT / "sibyl-campione" / "dati" / "contesti-2026-09-28.jsonl"


class Quiet:
    """A model that finds nothing true: how many evaluations a day makes does not depend on d."""

    def build(self) -> EngineBuild:
        return EngineBuild(1, "0.1.0", "none", "none", 1, 2)

    def rewrite(self, condition: str) -> str:
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        return dict.fromkeys(statements, -6.0)


def test_the_day_of_2026_09_28_replays_to_its_evaluations(tmp_path: Path) -> None:
    """The ticket's check (#46): the captured day, converted and replayed with the 20 s debounce.

    Ticket #11 counted 37 contexts evaluated; the app evaluates 36. The 37th was a Vivaldi window
    whose privacy the capture could not tell, which the app ignores since #41.
    """
    if not (CAPTURE.is_file() and folders.SAMPLE.is_file()):
        pytest.skip(f"the capture of 2026-09-28 is not in {folders.NO_GIT}")
    copy = tmp_path / "log-20260928-capture.db"
    capture.convert(capture.read(CAPTURE), sample.reminders(folders.SAMPLE), Quiet(), copy)
    log = snapshot.read(copy)
    day = days.select(log, None, SystemClock())
    replayed = replay.Replay(log, day).run()
    contexts = {evaluation.context for evaluation in replayed.evaluations}
    print(f"\n{len(replayed.evaluations)} evaluations of {len(contexts)} contexts")
    assert day.day.isoformat() == "2026-09-28"
    assert (len(replayed.evaluations), len(contexts)) == (116, 36)
    assert (len(day.evaluations), len({e.context for e in day.evaluations})) == (116, 36)
