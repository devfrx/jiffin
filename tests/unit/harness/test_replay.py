import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context, Observation, normalize
from jiffin.core.model import EngineBuild, ModelError
from jiffin.core.records import Alert, Answer, Evaluation
from jiffin.core.reminders import HOUR_MS, Reminders, Snooze
from jiffin.harness import __main__ as harness
from jiffin.harness import day as days
from jiffin.harness import engine, fixtures, labels, replay, snapshot
from jiffin.harness.folders import REPOSITORY
from jiffin.store.store import Log, Store

T0 = 1_791_190_800_000  # 2026-10-05 09:00 UTC
FIXTURE = REPOSITORY / "tests" / "fixtures" / "day.json"
MORNING = json.loads(FIXTURE.read_text(encoding="utf-8"))["contexts"]
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
VERDI = ("quando lavoro al progetto Verdi", "aggiornare il changelog")
BANCA = ("se sono sul sito della banca", "pagare il bollo")
BANCA_ROSSI = "se sono sul sito della Banca Rossi"
PAUSA = ("se non sto lavorando", "fare stretching")
POSTA = ("quando leggo la posta", "rispondere a Bianchi")
D = {
    ("changelog.md - verdi - Visual Studio Code", VERDI[0]): 2.5,
    ("Banca Rossi - Conto", BANCA[0]): 0.99,
    ("Banca Rossi - Conto", BANCA_ROSSI): 1.5,
    ("Posta in arrivo - Outlook", POSTA[0]): 1.2,
    ("Offerte treni", PAUSA[0]): 0.9,
}
FIGMA = Context("figma.exe", "Icone - Figma", None)


class FakeEngine:
    """Rewrites a condition by quoting it, judges from `D`, and may be down."""

    def __init__(self) -> None:
        self.down = False

    def build(self) -> EngineBuild:
        self._answer()
        return BUILD

    def rewrite(self, condition: str) -> str:
        self._answer()
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        self._answer()
        return {
            key: D.get((context.title, text.removeprefix("The user: ").removesuffix(".")), -3.0)
            for key, text in statements.items()
        }

    def _answer(self) -> None:
        if self.down:
            raise ModelError("the engine is down")


def a_day(path: Path) -> Log:
    """The invented morning through the app's own core, with an owner who answers some alerts:
    Utile and then Fatto for Verdi, Non qui for the bank, Rimanda a quarter of an hour for the
    mail; the engine down for a while; the mail's reminder created, the bank's edited."""
    fake = FakeEngine()
    clock = SimulatedClock(T0 - HOUR_MS, UTC)
    core = Reminders(fake, clock, lambda view: None, lambda view: None)
    answers: dict[int, list[tuple[str, int]]] = {
        1: [("useful", 4_000), ("done", 2_000)],
        2: [("not_here", 3_000)],
        4: [("snooze", 5_000)],
    }

    def owner(timeline: replay.Timeline, alert: Alert) -> None:
        replay.passive(timeline, alert)
        planned = answers.get(alert.reminder_id)
        if planned and alert.shown_at is not None:
            what, after = planned.pop(0)

            def answer(core: Reminders) -> None:
                if what == "snooze":
                    core.snooze(alert.id, Snooze.QUARTER_HOUR)
                else:
                    getattr(core, what)(alert.id)

            timeline.at(alert.shown_at + after, answer)

    def engine_down(down: bool) -> replay.Command:
        return lambda core: setattr(fake, "down", down)

    timeline = replay.Timeline(core, clock, owner)
    for condition, action in (VERDI, BANCA, PAUSA):
        timeline.at(T0 - HOUR_MS, replay.new_reminder(condition, action))
    timeline.at(T0 + 600_000, replay.new_reminder(*POSTA))
    timeline.at(T0 + 2_500_000, engine_down(True))
    timeline.at(T0 + 2_600_000, engine_down(False))
    timeline.at(T0 + 2_700_000, lambda core: core.edit(2, BANCA_ROSSI, BANCA[1]))
    for seconds, app, title, address in MORNING:
        context = None if app is None else normalize(app, title, address)
        observation = Observation(T0 + seconds * 1000, context)
        timeline.at(observation.at, replay.observe(observation))
    timeline.run(T0 + 4_800_000)
    store = Store.open(path)
    store.save(timeline.records)
    log = store.log()
    store.close()
    return log


def signature(day: days.Day) -> tuple[list[Any], list[Any]]:
    """What a replay must give back, with texts in place of ids."""
    evaluations = [
        (
            e.context,
            e.context_since,
            e.at,
            e.failed,
            e.threshold,
            sorted(
                (day.revisions[c.revision_id].condition, c.d, c.from_cache, c.outcome.value)
                for c in e.candidates
            ),
        )
        for e in day.evaluations
    ]
    alerts = [
        (a.revision.condition, a.context, a.created_at, a.shown_at, a.vanished_at, a.answer)
        + (a.answered_at,)
        for a in sorted(day.alerts, key=lambda a: (a.created_at, a.revision.condition))
    ]
    return evaluations, alerts


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> tuple[Log, days.Day]:
    log = a_day(tmp_path_factory.mktemp("day") / "jiffin.db")
    return log, days.select(log, None, SimulatedClock(T0, UTC))


def test_the_invented_day_holds_what_makes_a_replay_hard(recorded: tuple[Log, days.Day]) -> None:
    log, day = recorded
    answers = {alert.answer for alert in day.alerts}
    assert answers >= {Answer.USEFUL, Answer.DONE, Answer.NOT_HERE, Answer.SNOOZE}
    assert any(evaluation.failed for evaluation in day.evaluations)
    assert len({revision.condition for revision in log.revisions.values()}) == 5  # one edit
    assert any(reminder.created_at > T0 for reminder in log.reminders)
    assert any(reminder.completed_at is not None for reminder in log.reminders)


def test_a_day_replayed_as_recorded_gives_its_evaluations_and_alerts_back(
    recorded: tuple[Log, days.Day],
) -> None:
    log, day = recorded
    assert signature(replay.Replay(log, day).run()) == signature(day)


def test_a_lower_threshold_alerts_where_the_recorded_scores_reach_it(
    recorded: tuple[Log, days.Day],
) -> None:
    log, day = recorded
    lower = replay.Replay(log, day, threshold=0.8).run()
    new = [alert for alert in lower.alerts if alert.context.title == "Offerte treni"]
    assert [alert.revision.condition for alert in new] == [PAUSA[0]]
    assert len(lower.alerts) == len(day.alerts) + 1
    assert {evaluation.threshold for evaluation in lower.evaluations} == {0.8}


def test_without_answers_every_alert_leaves_the_screen_unanswered(
    recorded: tuple[Log, days.Day],
) -> None:
    log, day = recorded
    silent = replay.Replay(log, day, answers=False).run()
    assert all(alert.answer is None for alert in silent.alerts)
    # Verdi's last alert goes when Verdi is completed, as the log says, before its 10 s are up.
    assert sum(alert.vanished_at is None for alert in silent.alerts) == 1


def test_more_reminders_are_judged_by_the_engine_from_the_start(
    recorded: tuple[Log, days.Day],
) -> None:
    log, day = recorded
    extra = fixtures.reminders(3)
    grown = replay.Replay(log, day, FakeEngine(), rewrite=True, extra=extra).run()
    judged = {
        grown.revisions[candidate.revision_id].condition
        for evaluation in grown.evaluations
        for candidate in evaluation.candidates
    }
    assert {condition for condition, _ in extra} <= judged
    assert not any(evaluation.failed for evaluation in grown.evaluations)  # the engine is up


def test_a_context_seen_twice_in_a_row_was_left_in_between() -> None:
    first = Evaluation(1, 20_000, FIGMA, 0, 0.97, BUILD, ())
    again = Evaluation(2, 120_000, FIGMA, 100_000, 0.97, BUILD, ())
    snooze_end = Evaluation(3, 900_000, FIGMA, 100_000, 0.97, BUILD, ())
    assert replay.observations([again, snooze_end, first]) == [
        Observation(0, FIGMA),
        Observation(99_999, None),
        Observation(100_000, FIGMA),
    ]


def test_recorded_scores_fail_where_the_log_did(recorded: tuple[Log, days.Day]) -> None:
    log, day = recorded
    clock = SimulatedClock(T0, UTC)
    scores = replay.Recorded(log, day, clock)
    judged = next(e for e in day.evaluations if e.candidates)
    statement = day.revisions[judged.candidates[0].revision_id].statement
    assert statement is not None
    clock.advance(judged.at - clock.now())
    assert scores.judge(judged.context, {1: statement}) == {1: judged.candidates[0].d}
    with pytest.raises(ModelError, match="never judged"):
        scores.judge(Context("excel.exe", "Budget", None), {1: statement})
    failed = next(e for e in day.evaluations if e.failed)
    clock.advance(failed.at - clock.now())
    with pytest.raises(ModelError, match="as the log recorded"):
        scores.judge(judged.context, {1: statement})


# The commands


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A data folder with a copy of the invented day."""
    database = tmp_path / "jiffin.db"
    a_day(database)
    folder = tmp_path / "prove"
    folder.mkdir()
    snapshot.snapshot(database, folder, datetime(2026, 10, 5, 12, tzinfo=UTC))
    return folder


@contextmanager
def fake_engine(models: Path) -> Iterator[FakeEngine]:
    yield FakeEngine()


def test_replay_prints_the_day_as_recorded_and_as_replayed(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert harness.main(["replay", "--data", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    recorded, again = (
        line.split(" | ")[1:] for line in lines if line.startswith(("| as", "| thr"))
    )
    assert recorded == again  # the replay at the day's own threshold changes nothing
    assert (data / "replay-2026-10-05-threshold-0.97.html").exists()


def test_replay_at_thresholds_with_the_engine_and_with_more_reminders(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(engine, "running", fake_engine)
    arguments = ["replay", "--data", str(data), "--threshold", "0.8,1.3", "--engine"]
    assert harness.main([*arguments, "--reminders", "6,9"]) == 0
    lines = capsys.readouterr().out.splitlines()
    rows = [line.split(" | ")[0] for line in lines if line.startswith("| ")]
    assert rows[1:] == [
        "| as recorded",
        "| threshold 0.8",
        "| threshold 1.3",
        "| this engine",
        "| 6 reminders",
        "| 9 reminders",
    ]


def test_more_reminders_than_the_day_has_are_needed(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(engine, "running", fake_engine)
    assert harness.main(["replay", "--data", str(data), "--reminders", "2"]) == 1
    assert "has 4 reminders already, more than 2" in capsys.readouterr().err


def test_label_adds_the_pairs_of_the_invented_reminders(data: Path) -> None:
    assert harness.main(["label", "--data", str(data), "--reminders", "6"]) == 0
    labelled = labels.load(labels.path_for(data, date(2026, 10, 5)))
    conditions = {pair["condition"] for pair in labelled.pairs}
    assert {condition for condition, _ in fixtures.reminders(2)} <= conditions
    assert fixtures.reminders(3)[2][0] not in conditions  # 4 of the day and 2 invented make 6


def test_a_replay_runs_again_from_the_start(recorded: tuple[Log, days.Day]) -> None:
    log, day = recorded
    again = replay.Replay(log, day)
    assert signature(again.run()) == signature(again.run())
