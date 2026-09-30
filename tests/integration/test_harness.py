"""The harness on the owner's machine, with the private sample and the real engine (ADR-0017).

Run with `uv run pytest -m integration`. The sample and the model come from the `NO_GIT` folder
beside the repository, and a test skips when what it needs is missing. Only numbers reach the
output.
"""

import json
from pathlib import Path

import pytest

from jiffin.harness import __main__ as harness
from jiffin.harness import folders, metrics, sample

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
