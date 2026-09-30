import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild, ModelError
from jiffin.harness import __main__ as harness
from jiffin.harness import engine, sample
from jiffin.harness.errors import HarnessError
from jiffin.harness.metrics import Operating

BUILD = EngineBuild(1, "0.1.0", "b6500", "ab" * 32, 2, 2)
LATER = EngineBuild(1, "0.1.1", "b6600", "ab" * 32, 2, 2)
# An invented sample in the prototype's format. The reminders come out of order by number.
SAMPLE = {
    "contexts": [
        {
            "id": "c-code",
            "app": "code.exe",
            "title": "● changelog.md - rossi - Visual Studio Code",
            "address_bar": None,
        },
        {
            "id": "c-bank",
            "app": "vivaldi.exe",
            "title": "(2) Banca Rossi - Vivaldi",
            "address_bar": "https://www.bancarossi.it/conto?id=3",
            "address_bar_focused": False,
        },
        {
            "id": "c-typing",
            "app": "vivaldi.exe",
            "title": "Nuova scheda - Vivaldi",
            "address_bar": "banca ro",
            "address_bar_focused": True,
        },
        {"id": "c-mail", "app": "outlook.exe", "title": "Posta in arrivo", "address_bar": "x"},
    ],
    "reminders": [
        {
            "id": "r-rossi",
            "n": 3,
            "text": "quando lavoro al progetto Rossi ricordami di aggiornare il changelog",
        },
        {
            "id": "r-bank",
            "n": 1,
            "text": "se sono sul sito della banca, ricordami di pagare l'affitto",
        },
        {"id": "r-rest", "n": 8, "text": "quando non sto lavorando ricordami di fare una pausa"},
    ],
    "labels": {
        "c-code": {"r-rossi": True, "r-bank": False, "r-rest": False},
        "c-bank": {"r-rossi": False, "r-bank": True, "r-rest": True},
        "c-typing": {"r-rossi": False, "r-bank": False, "r-rest": True},
        "c-mail": {"r-rossi": False, "r-bank": False, "r-rest": False},
    },
}


class FakeModel:
    """Rewrites a condition by quoting it, and judges from a table of (title, statement)."""

    def __init__(self, d: Mapping[tuple[str, str], float], build: EngineBuild = BUILD) -> None:
        self._d = d
        self._build = build

    def build(self) -> EngineBuild:
        return self._build

    def rewrite(self, condition: str) -> str:
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        return {key: self._d.get((context.title, text), 0.0) for key, text in statements.items()}


@pytest.fixture
def labelled(tmp_path: Path) -> sample.Sample:
    path = tmp_path / "etichette.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    return sample.load(path)


def test_the_sample_is_read_as_the_app_sees_contexts(labelled: sample.Sample) -> None:
    assert labelled.contexts == (
        Context("code.exe", "changelog.md - rossi - Visual Studio Code", None),
        Context("vivaldi.exe", "Banca Rossi", "bancarossi.it/conto"),
        Context("vivaldi.exe", "Nuova scheda", None),  # typing in the bar: no address
        Context("outlook.exe", "Posta in arrivo", None),  # an address only in the browsers
    )


def test_reminders_come_in_order_of_number_with_their_condition(labelled: sample.Sample) -> None:
    assert labelled.reminder_ids == ("r-bank", "r-rossi", "r-rest")
    assert labelled.numbers == (1, 3, 8)
    assert labelled.conditions == (
        "se sono sul sito della banca",
        "quando lavoro al progetto Rossi",
        "quando non sto lavorando",
    )
    assert labelled.relevant[:2] == ((False, True, False), (True, False, True))


def test_a_sample_that_cannot_be_read_says_so(tmp_path: Path) -> None:
    with pytest.raises(HarnessError, match="--sample"):
        sample.load(tmp_path / "missing.json")


def test_a_reminder_without_ricordami_has_no_condition(tmp_path: Path) -> None:
    broken = SAMPLE | {"reminders": [{"id": "r", "n": 1, "text": "pagare l'affitto"}]}
    path = tmp_path / "etichette.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(HarnessError, match="ricordami"):
        sample.load(path)


def test_scoring_rewrites_every_condition_and_judges_every_context(labelled: sample.Sample) -> None:
    model = FakeModel(
        {
            ("Banca Rossi", "The user: se sono sul sito della banca."): 0.99,
            (
                "changelog.md - rossi - Visual Studio Code",
                "The user: quando lavoro al progetto Rossi.",
            ): 0.98,
        }
    )
    scores = sample.score(labelled, model)
    assert scores.build == BUILD
    assert scores.d == (
        (0.0, 0.98, 0.0),
        (0.99, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )


def test_a_perfect_judge_takes_every_relevant_pair_with_no_false_alarm(
    labelled: sample.Sample,
) -> None:
    d = [[float(cell) for cell in row] for row in labelled.relevant]
    summary = sample.summarize(labelled, d)
    assert summary.auroc.value == 1.0
    assert summary.auroc.interval == (1.0, 1.0)
    for budget in sample.BUDGETS:
        assert summary.within[budget][0] == Operating(1.0, 1.0, 0.0)
    assert summary.at_threshold == Operating(0.97, 1.0, 0.0)
    assert list(summary.kinds) == ["name", "type", "negation"]
    assert summary.kinds["negation"] == sample.Kind(reminders=1, relevant=2, auroc=1.0, recall=1.0)


def test_a_build_compared_with_itself_differs_in_nothing(labelled: sample.Sample) -> None:
    d = [[0.9, 0.2, 0.99], [0.98, 0.1, 0.3], [0.5, 0.5, 0.97], [0.1, 0.99, 0.2]]
    differences = sample.compare(labelled, d, d)
    assert differences.auroc == sample.Measure(0.0, (0.0, 0.0))
    assert all(
        gain == sample.Measure(0.0, (0.0, 0.0)) for gain in differences.recall_within.values()
    )
    assert differences.at_threshold == (0.0, 0.0)


def test_scores_are_saved_and_read_back_as_a_baseline(
    labelled: sample.Sample, tmp_path: Path
) -> None:
    scores = sample.Scores(BUILD, ((0.1, 0.2, 0.3),) * 4)
    path = sample.save(labelled, scores, tmp_path, datetime(2026, 10, 1, 9, 30, tzinfo=UTC))
    assert path.name == "sample-20261001-093000.json"
    assert sample.load_baseline(labelled, path) == scores
    assert "Rossi" not in path.read_text(encoding="utf-8")  # ids and numbers only


def test_a_baseline_of_another_sample_is_refused(labelled: sample.Sample, tmp_path: Path) -> None:
    path = sample.save(
        labelled, sample.Scores(BUILD, ((0.1, 0.2, 0.3),) * 4), tmp_path, datetime.now(UTC)
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record["contexts"] = record["contexts"][:3]
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(HarnessError, match="another sample"):
        sample.load_baseline(labelled, path)


def test_the_report_holds_numbers_and_no_texts(labelled: sample.Sample) -> None:
    d = [[float(cell) for cell in row] for row in labelled.relevant]
    scores = sample.Scores(BUILD, tuple(tuple(row) for row in d))
    text = sample.report(labelled, scores, sample.summarize(labelled, d))
    assert "## Sample: engine 0.1.0, llama.cpp b6500, judge prompt 2" in text
    assert "4 contexts, 3 reminders: 4 relevant pairs of 12." in text
    assert "| AUROC | 1.000 | 1.000 to 1.000 |" in text
    assert "| At the threshold 0.97: false alarms per evaluated context | 0.000 |  |" in text
    assert "| negation | 1 | 2 | 1.000 | 1.00 |" in text
    assert not any(word in text for word in ("Rossi", "banca", "Posta", "lavoro"))


def test_the_report_against_a_baseline_shows_the_differences(labelled: sample.Sample) -> None:
    perfect = [[float(cell) for cell in row] for row in labelled.relevant]
    worse = [[0.0] * 3 for _ in range(4)]
    scores, old = (
        sample.Scores(LATER, tuple(map(tuple, perfect))),
        sample.Scores(BUILD, tuple(map(tuple, worse))),
    )
    text = sample.report(
        labelled,
        scores,
        sample.summarize(labelled, perfect),
        (old, sample.summarize(labelled, worse), sample.compare(labelled, perfect, worse)),
    )
    assert "Baseline: engine 0.1.0, llama.cpp b6500" in text
    assert "| AUROC | 1.000 | 1.000 to 1.000 | 0.500 | +0.500 |" in text
    assert "| At the threshold 0.97: recall | 1.00 |  | 0.00 | +1.00 |  |" in text


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "etichette.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    return path


def test_the_command_prints_a_summary_and_saves_the_scores(
    sample_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    @contextmanager
    def running(models: Path) -> Iterator[FakeModel]:
        assert models == tmp_path / "models"
        yield FakeModel({("Banca Rossi", "The user: se sono sul sito della banca."): 0.99})

    monkeypatch.setattr(engine, "running", running)
    data = tmp_path / "prove"
    arguments = ["sample", "--data", str(data), "--sample", str(sample_file)]
    arguments += ["--models", str(tmp_path / "models")]
    assert harness.main(arguments) == 0
    assert "## Sample: engine 0.1.0" in capsys.readouterr().out
    (saved,) = data.glob("sample-*.json")

    assert harness.main([*arguments, "--baseline", str(saved)]) == 0
    assert "| AUROC | 0.625 |" in capsys.readouterr().out


def test_an_engine_that_fails_stops_the_command_with_a_message(
    sample_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class Failing(FakeModel):
        def rewrite(self, condition: str) -> str:
            raise ModelError("rewrite: the engine failed")

    @contextmanager
    def running(models: Path) -> Iterator[FakeModel]:
        yield Failing({})

    monkeypatch.setattr(engine, "running", running)
    arguments = ["sample", "--data", str(tmp_path), "--sample", str(sample_file)]
    assert harness.main(arguments) == 1
    assert capsys.readouterr().err.endswith("error: the engine: rewrite: the engine failed\n")
