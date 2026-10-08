import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from jiffin.core.clock import SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation, normalize
from jiffin.core.model import EngineBuild, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    ContextAnswer,
    Evaluation,
    Here,
    Left,
    Outcome,
    Snooze,
)
from jiffin.core.reminders import HOUR_MS, Reminders
from jiffin.core.situations import Situation, SituationObservation, SituationStretch
from jiffin.harness import __main__ as harness
from jiffin.harness import day as days
from jiffin.harness import engine, fixtures, labels, page, replay, snapshot
from jiffin.harness.folders import REPOSITORY
from jiffin.lang.harness import HARNESS
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
    """Rewrites a condition by quoting it, judges from `scores`, and may be down."""

    def __init__(self, scores: Mapping[tuple[str, str], float] = D) -> None:
        self.down = False
        self._scores = scores

    def build(self) -> EngineBuild:
        self._answer()
        return BUILD

    def rewrite(self, condition: str) -> str:
        self._answer()
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        self._answer()
        return {
            key: self._scores.get(
                (context.title, text.removeprefix("The user: ").removesuffix(".")), -3.0
            )
            for key, text in statements.items()
        }

    def _answer(self) -> None:
        if self.down:
            raise ModelError("the engine is down")


def a_day(path: Path) -> Log:
    """The invented morning through the app's own core, with an owner who answers some alerts:
    Next time and then Done for Verdi, Not here for the bank, Snooze a quarter of an
    hour for the mail; the engine down for a while; the mail's reminder created, the bank's
    edited."""
    fake = FakeEngine()
    clock = SimulatedClock(T0 - HOUR_MS, UTC)
    core = Reminders(fake, clock, lambda view: None, lambda view: None)
    answers: dict[int, list[tuple[str, int]]] = {
        1: [("next_time", 4_000), ("done", 2_000)],
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
                elif what == "next_time":
                    core.snooze(alert.id, Snooze.NEXT_TIME)
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
    answers = {(alert.answer, alert.snooze) for alert in day.alerts}
    assert answers >= {
        (Answer.SNOOZE, Snooze.NEXT_TIME),
        (Answer.DONE, None),
        (Answer.NOT_HERE, None),
        (Answer.SNOOZE, Snooze.QUARTER_HOUR),
    }
    assert log.left
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


def test_an_answer_said_before_the_day_counts_from_its_start(
    recorded: tuple[Log, days.Day],
) -> None:
    log, day = recorded
    [pause] = [reminder for reminder in log.reminders if reminder.revision.condition == PAUSA[0]]
    trains = next(e.context for e in day.evaluations if e.context.title == "Offerte treni")

    def alerts_there(*said: tuple[Here, int]) -> int:
        """Pause's alerts in the trains at a lower threshold, with these answers in the log."""
        answers = tuple(ContextAnswer(pause.id, trains, here, None, None, at) for here, at in said)
        lower = replay.Replay(replace(log, answers=answers), day, threshold=0.8).run()
        return sum(alert.context == trains for alert in lower.alerts)

    assert alerts_there() == 1
    assert alerts_there((Here.NO, T0 - 2_000)) == 0
    assert alerts_there((Here.NO, T0 - 2_000), (Here.WITHDRAWN, T0 - 1_000)) == 1
    assert alerts_there((Here.NO, T0 + 4_600_000)) == 1  # said after its alert: not from the start


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
    extra = fixtures.reminders(4)
    grown = replay.Replay(log, day, FakeEngine(), rewrite=True, extra=extra).run()
    judged = {
        grown.revisions[candidate.revision_id].condition
        for evaluation in grown.evaluations
        for candidate in evaluation.candidates
    }
    situated = {"quando finisco la call", "quando torno al PC"}  # never judged: no remainder
    assert {condition for condition, _ in extra} - situated <= judged
    assert not situated & judged
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


def test_a_context_that_left_where_the_log_says_is_left_then() -> None:
    first = Evaluation(1, 20_000, FIGMA, 0, 0.97, BUILD, ())
    again = Evaluation(2, 120_000, FIGMA, 100_000, 0.97, BUILD, ())
    assert replay.observations([again, first], [Left(FIGMA, 0, 30_000)]) == [
        Observation(0, FIGMA),
        Observation(30_000, None),
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


def test_a_rimanda_of_0_1_without_its_kind_is_found_from_the_judgements(
    recorded: tuple[Log, days.Day],
) -> None:
    """Version 0.1 did not record which Snooze: the one whose end falls between the reminder's
    last judgement as snoozed and its first as free."""
    log, day = recorded
    unknown = tuple(
        replace(alert, snooze=None) if alert.snooze is Snooze.QUARTER_HOUR else alert
        for alert in day.alerts
    )
    assert unknown != day.alerts
    assert signature(replay.Replay(log, replace(day, alerts=unknown)).run()) == signature(day)


# Version 0.2: the return pause, the times, and a Snooze from the day before (ADR-0021)

YESTERDAY = T0 - 15 * HOUR_MS  # 2026-10-04 18:00 UTC
MINUTE = 60_000
CODE = Context("code.exe", "changelog.md - verdi - Visual Studio Code", None)
MAIL = Context("outlook.exe", "Posta in arrivo - Outlook", None)
NEWS = Context("vivaldi.exe", "Notizie", "notizie.it")
CHAT = Context("teams.exe", "Chat - Teams", None)
"""Yesterday's only: a replay starts with an empty cache, so a context judged yesterday too
would ask again what the app found in its cache, a difference no summary shows."""
CALL = ("alle 18:05", "chiamare Rossi")
STANDUP = ("alle 9:05", "aprire la riunione")
STANDUP_LATER = "alle 9:20"
REPORT = ("alle 10:30", "mandare il resoconto")


def a_day_of_times(path: Path) -> Log:
    """Version 0.2 through the app's own core, in UTC: a return pause of 30 s, then of 5 minutes;
    reminders with only a time: one that rang yesterday and was put off to today with Tomorrow,
    one edited after it rang, one that rings after the day's last evaluation."""
    clock = SimulatedClock(YESTERDAY, UTC)
    core = Reminders(FakeEngine(), clock, lambda view: None, lambda view: None, return_pause=30_000)
    answers: dict[str, list[tuple[Snooze | str, int]]] = {
        CALL[0]: [(Snooze.TOMORROW, 3_000), ("done", 2_000)],
        STANDUP[0]: [("close", 2_000)],
    }

    def owner(timeline: replay.Timeline, alert: Alert) -> None:
        replay.passive(timeline, alert)
        planned = answers.get(alert.revision.condition)
        if planned and alert.shown_at is not None:
            what, after = planned.pop(0)

            def answer(core: Reminders) -> None:
                if isinstance(what, Snooze):
                    core.snooze(alert.id, what)
                else:
                    getattr(core, what)(alert.id)

            timeline.at(alert.shown_at + after, answer)

    def longer_pause(core: Reminders) -> None:
        core.return_pause = 5 * MINUTE

    timeline = replay.Timeline(core, clock, owner)

    def see(at: int, context: Context | None) -> None:
        timeline.at(at, replay.observe(Observation(at, context)))

    for condition, action in (VERDI, CALL, STANDUP, REPORT):
        timeline.at(YESTERDAY, replay.new_reminder(condition, action))
    see(YESTERDAY + 4 * MINUTE, CHAT)  # the call rings at 18:05, and is put off to tomorrow
    see(YESTERDAY + 10 * MINUTE, None)
    see(T0, CODE)  # Verdi rings; the call returns, and is done; the stand-up rings at 09:05
    see(T0 + 6 * MINUTE, NEWS)
    see(T0 + 7 * MINUTE, CODE)  # away 60 s, more than the pause: Verdi rings again
    timeline.at(T0 + 10 * MINUTE, lambda core: core.edit(3, STANDUP_LATER, STANDUP[1]))
    timeline.at(T0 + 12 * MINUTE, longer_pause)
    see(T0 + 15 * MINUTE, NEWS)
    see(T0 + 16 * MINUTE, CODE)  # away 60 s, less than the pause: the same occasion
    see(T0 + 60 * MINUTE, MAIL)  # the last evaluation; the report rings at 10:30, after it
    see(T0 + 105 * MINUTE, None)
    timeline.run(T0 + 2 * HOUR_MS)
    store = Store.open(path)
    store.save(timeline.records)
    log = store.log()
    store.close()
    return log


@pytest.fixture(scope="module")
def times(tmp_path_factory: pytest.TempPathFactory) -> tuple[Log, days.Day]:
    log = a_day_of_times(tmp_path_factory.mktemp("times") / "jiffin.db")
    return log, days.select(log, None, SimulatedClock(T0, UTC))


def test_the_day_of_times_holds_what_version_0_2_adds(times: tuple[Log, days.Day]) -> None:
    log, day = times
    assert [evaluation.return_pause for evaluation in day.evaluations] == [30_000] * 3 + [
        5 * MINUTE
    ] * 3
    rang = [
        candidate.outcome
        for evaluation in day.evaluations
        for candidate in evaluation.candidates
        if candidate.outcome is not Outcome.BELOW_THRESHOLD
    ]
    assert rang == [Outcome.ALERT, Outcome.ALERT, Outcome.SAME_OCCASION]
    alone = [alert for alert in day.alerts if alert.evaluation_id is None]
    assert [(alert.revision.condition, alert.answer) for alert in alone] == [
        (CALL[0], Answer.DONE),
        (STANDUP[0], Answer.CLOSED),
        (STANDUP_LATER, None),
        (REPORT[0], None),
    ]
    assert alone[-1].created_at > day.evaluations[-1].at
    (put_off,) = (alert for alert in log.alerts if alert.snooze is Snooze.TOMORROW)
    assert put_off.created_at < day.evaluations[0].at  # yesterday


def test_a_day_of_0_2_replays_with_its_pauses_its_times_and_yesterdays_rimanda(
    times: tuple[Log, days.Day],
) -> None:
    log, day = times
    assert signature(replay.Replay(log, day, zone=UTC).run()) == signature(day)


# Version 0.3: the situations and the answers per place (ADR-0028, ADR-0029)

TRAINS = Context("vivaldi.exe", "Offerte treni", "treni.it")
WEATHER = Context("vivaldi.exe", "Meteo", "meteo.it")
SPORT = Context("vivaldi.exe", "Notizie sportive", "sport.it")
CALL_ENDS = ("quando finisco la call", "segnare le decisioni")
ON_TEAMS = ("quando sono in call su Teams", "chiedere la data a Bianchi")
BACK = ("quando torno al PC", "bere un bicchiere d'acqua")
MAIL_AFTER_CALL = ("quando finisco la call e leggo la posta", "mandare il riassunto")
SITUATED = {
    (CODE.title, VERDI[0]): 2.5,
    (MAIL.title, "quando leggo la posta"): 1.2,
    (TRAINS.title, PAUSA[0]): 0.9,
    (WEATHER.title, PAUSA[0]): 0.5,
    (SPORT.title, PAUSA[0]): 0.8,
}
"""Pause is under the threshold in the trains and the weather, near the cut: Remind here there
twice lowers its threshold to 0.72, under its d in the sport news."""


def a_day_of_situations(path: Path) -> Log:
    """Version 0.3 through the app's own core, in UTC. Yesterday Verdi rang unanswered, and this
    morning the owner says Not here on it from the tray list. A Zoom call ends; a Teams call
    starts and ends; the owner is away for lunch, and comes back; the app closes during a third
    call, and starts again with the call over. Remind here on Pause in the trains and in the
    weather, near the cut, lowers its threshold; the weather's is withdrawn in the afternoon."""
    clock = SimulatedClock(YESTERDAY, UTC)
    core = Reminders(FakeEngine(SITUATED), clock, lambda view: None, lambda view: None)
    answers: dict[str, list[tuple[str, int]]] = {
        CALL_ENDS[0]: [("close", 3_000), ("close", 3_000)],
        MAIL_AFTER_CALL[0]: [("done", 4_000)],
        BACK[0]: [("done", 2_000)],
        PAUSA[0]: [("close", 2_000)] * 4,
    }
    yesterdays: list[int] = []

    def owner(timeline: replay.Timeline, alert: Alert) -> None:
        replay.passive(timeline, alert)
        if alert.revision.condition == VERDI[0]:
            yesterdays.append(alert.id)
        planned = answers.get(alert.revision.condition)
        if planned and alert.shown_at is not None:
            what, after = planned.pop(0)
            timeline.at(alert.shown_at + after, lambda core: getattr(core, what)(alert.id))

    timeline = replay.Timeline(core, clock, owner)

    def see(at: int, context: Context | None) -> None:
        timeline.at(at, replay.observe(Observation(at, context)))

    def situation(at: int, kind: Situation, *values: str) -> None:
        observation = SituationObservation(at, kind, frozenset(values))
        timeline.at(at, replay.observe(observation))

    def closed(at: int) -> None:
        for kind in (Situation.CALL, Situation.AWAY, Situation.POWER):
            timeline.at(at, replay.observe(SituationObservation(at, kind, None)))

    def said(at: int, what: str, reminder_id: int, context: Context) -> None:
        timeline.at(at, lambda core: getattr(core, what)(reminder_id, context))

    for condition, action in (VERDI, PAUSA, CALL_ENDS, ON_TEAMS, BACK, MAIL_AFTER_CALL):
        timeline.at(YESTERDAY, replay.new_reminder(condition, action))
    situation(YESTERDAY, Situation.POWER, "plugged")
    situation(YESTERDAY, Situation.AWAY, "no")
    see(YESTERDAY + 4 * MINUTE, CODE)  # Verdi rings, and vanishes unanswered
    see(YESTERDAY + 10 * MINUTE, None)
    see(T0, MAIL)
    timeline.at(T0 + 30 * MINUTE, lambda core: core.not_here(yesterdays[0]))  # the tray list
    see(T0 + 40 * MINUTE, CODE)  # Verdi keeps quiet
    situation(T0 + 60 * MINUTE, Situation.CALL, "zoom.exe")
    situation(T0 + 90 * MINUTE, Situation.CALL)  # the call ends
    see(T0 + 100 * MINUTE, MAIL)  # the mail after the call
    situation(T0 + 120 * MINUTE, Situation.CALL, "ms-teams.exe")
    situation(T0 + 140 * MINUTE, Situation.CALL)
    see(T0 + 150 * MINUTE, TRAINS)
    said(T0 + 151 * MINUTE, "remind_here", 2, TRAINS)
    see(T0 + 165 * MINUTE, WEATHER)
    said(T0 + 166 * MINUTE, "remind_here", 2, WEATHER)
    see(T0 + 180 * MINUTE, None)  # lunch
    situation(T0 + 180 * MINUTE, Situation.AWAY, "yes")
    situation(T0 + 195 * MINUTE, Situation.AWAY, "no")
    see(T0 + 195 * MINUTE, SPORT)  # back: Pause rings under its lowered threshold
    see(T0 + 205 * MINUTE, None)
    see(T0 + 210 * MINUTE, TRAINS)  # Pause rings for Remind here, in a new occasion
    situation(T0 + 240 * MINUTE, Situation.CALL, "zoom.exe")
    see(T0 + 250 * MINUTE, None)
    closed(T0 + 250 * MINUTE)  # the app closes during the call
    situation(T0 + 260 * MINUTE, Situation.POWER, "plugged")
    situation(T0 + 260 * MINUTE, Situation.AWAY, "no")
    situation(T0 + 260 * MINUTE, Situation.CALL)
    see(T0 + 260 * MINUTE, MAIL)  # no end of a call: it was not read
    said(T0 + 330 * MINUTE, "withdraw", 2, WEATHER)
    see(T0 + 340 * MINUTE, None)
    see(T0 + 345 * MINUTE, SPORT)  # Pause's threshold is back at 0.97: quiet
    see(T0 + 360 * MINUTE, None)
    timeline.run(T0 + 7 * HOUR_MS)
    store = Store.open(path)
    store.save(timeline.records)
    log = store.log()
    store.close()
    return log


@pytest.fixture(scope="module")
def situated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Log, days.Day]:
    log = a_day_of_situations(tmp_path_factory.mktemp("situated") / "jiffin.db")
    return log, days.select(log, None, SimulatedClock(T0, UTC))


def asked(day: days.Day) -> tuple[list[Any], list[Any]]:
    """The alerts asked for with Remind here, and the answers per place said during the day.

    A replay starts with an empty cache, so a Not here on yesterday's alert, in a place not
    judged yet that day, has no d there: no threshold reads the d of a Not here."""
    names = {revision.reminder_id: revision.action for revision in day.revisions.values()}
    begin = day.evaluations[0].context_since
    return (
        [(a.revision.condition, a.context, a.created_at, a.answer) for a in day.requested],
        [
            (names[a.reminder_id], a.context, a.here, a.d if a.here is Here.YES else None, a.at)
            for a in day.answers
            if a.at > begin
        ],
    )


def test_the_day_of_situations_holds_what_version_0_3_adds(
    situated: tuple[Log, days.Day],
) -> None:
    _, day = situated
    rang = {(alert.revision.condition, alert.d is None) for alert in day.alerts}
    assert rang == {
        (CALL_ENDS[0], True),
        (ON_TEAMS[0], True),
        (BACK[0], True),
        (MAIL_AFTER_CALL[0], False),
        (PAUSA[0], False),
    }
    assert [alert.context for alert in day.alerts if alert.revision.condition == PAUSA[0]] == [
        SPORT,
        TRAINS,
    ]
    assert [alert.context for alert in day.requested] == [TRAINS, WEATHER]
    assert [answer.here for answer in day.answers] == [Here.NO, Here.YES, Here.YES, Here.WITHDRAWN]
    calls = [s for s in day.situations if s.situation is Situation.CALL]
    assert [(s.value, s.until - s.since) for s in calls] == [
        ("zoom.exe", 30 * MINUTE),
        ("ms-teams.exe", 20 * MINUTE),
        ("zoom.exe", 10 * MINUTE),  # cut by the app's close
    ]
    assert sum(alert.revision.condition == CALL_ENDS[0] for alert in day.alerts) == 2
    assert all(
        candidate.outcome is not Outcome.ALERT
        for evaluation in day.evaluations
        if evaluation.context == CODE
        for candidate in evaluation.candidates
    )  # Verdi said Not here this morning, on yesterday's alert


def uncached(day: days.Day) -> tuple[list[Any], list[Any]]:
    """`signature`, without whether each score came from the cache: a replay starts with an empty
    cache, and Verdi's place was judged yesterday too (see `CHAT`)."""
    evaluations, alerts = signature(day)
    return [
        (*evaluation[:5], [(name, d, outcome) for name, d, _, outcome in evaluation[5]])
        for evaluation in evaluations
    ], alerts


def test_a_day_of_0_3_replays_with_its_situations_and_its_answers_per_place(
    situated: tuple[Log, days.Day],
) -> None:
    log, day = situated
    again = replay.Replay(log, day, zone=UTC).run()
    assert uncached(again) == uncached(day)
    assert asked(again) == asked(day)
    assert again.situations == day.situations


def test_the_situations_come_back_as_the_capture_observed_them() -> None:
    zoom = SituationStretch(Situation.CALL, "zoom.exe", 10_000, 50_000)
    chrome = SituationStretch(Situation.CALL, "chrome.exe", 20_000, 80_000)
    plugged = SituationStretch(Situation.POWER, "plugged", 0, 30_000)
    battery = SituationStretch(Situation.POWER, "battery", 30_000, 80_000)
    again = SituationStretch(Situation.POWER, "plugged", 90_000, 95_000)
    seen = replay.situation_observations([zoom, chrome, plugged, battery, again])
    assert [(o.at, o.situation.value, o.values) for o in seen] == [
        (0, "power", frozenset({"plugged"})),
        (10_000, "call", frozenset({"zoom.exe"})),
        (20_000, "call", frozenset({"zoom.exe", "chrome.exe"})),
        (30_000, "power", frozenset({"battery"})),
        (50_000, "call", frozenset({"chrome.exe"})),
        (80_000, "call", None),  # power stopped being read then: the app closed
        (80_000, "power", None),
        (90_000, "power", frozenset({"plugged"})),
        (95_000, "power", None),
    ]


def test_a_call_that_ends_while_the_app_runs_is_an_end() -> None:
    zoom = SituationStretch(Situation.CALL, "zoom.exe", 10_000, 50_000)
    plugged = SituationStretch(Situation.POWER, "plugged", 0, 90_000)
    seen = replay.situation_observations([zoom, plugged])
    assert (50_000, frozenset()) in [(o.at, o.values) for o in seen]


def test_a_remind_here_rings_again_in_a_replay_at_another_threshold(
    situated: tuple[Log, days.Day],
) -> None:
    """The offsets come from the answers as `core` computes them, relative to the threshold of
    the replay: at 1.6 the Remind here in the weather is no longer near the cut (0.5 is more
    than 1 under it), so Pause's threshold does not go down, and the sport news keep quiet."""
    log, day = situated
    higher = replay.Replay(log, day, threshold=1.6, zone=UTC).run()
    pause = [alert.context for alert in higher.alerts if alert.revision.condition == PAUSA[0]]
    assert pause == [TRAINS]  # for the Remind here said there, under any threshold
    assert [alert.context for alert in higher.requested] == [TRAINS, WEATHER]


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
        "| this engine, threshold 0.8",
        "| this engine, threshold 1.3",
        "| 6 reminders, threshold 0.8",
        "| 6 reminders, threshold 1.3",
        "| 9 reminders, threshold 0.8",
        "| 9 reminders, threshold 1.3",
    ]
    assert (data / "replay-2026-10-05-reminders-9-threshold-1.3.html").exists()
    assert (data / "scores-2026-10-05.json").exists()


def test_the_engine_starts_only_for_the_scores_not_kept(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(engine, "running", fake_engine)
    arguments = ["replay", "--data", str(data), "--reminders", "6"]
    assert harness.main(arguments) == 0
    first = capsys.readouterr().out

    @contextmanager
    def no_engine(models: Path) -> Iterator[FakeEngine]:
        raise AssertionError("the engine started")
        yield FakeEngine()

    monkeypatch.setattr(engine, "running", no_engine)
    assert harness.main(arguments) == 0
    assert capsys.readouterr().out == first
    assert harness.main([*arguments, "--threshold", "0.5,1.5"]) == 0  # at other thresholds too
    rows = [line for line in capsys.readouterr().out.splitlines() if line.startswith("| 6 rem")]
    assert len(rows) == 2 and rows[0] != rows[1]


def test_more_reminders_than_the_day_has_are_needed(
    data: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(engine, "running", fake_engine)
    assert harness.main(["replay", "--data", str(data), "--reminders", "2"]) == 1
    assert "has 4 reminders already, more than 2" in capsys.readouterr().err


def test_label_adds_the_pairs_of_the_invented_reminders_the_engine_judges(data: Path) -> None:
    assert harness.main(["label", "--data", str(data), "--reminders", "8"]) == 0
    labelled = labels.load(labels.path_for(data, date(2026, 10, 5)))
    remainders = {pair["remainder"] for pair in labelled.pairs}
    invented = [condition for condition, _ in fixtures.reminders(6)]
    assert invented[1] in remainders and invented[3] in remainders
    assert "" not in remainders  # the first and the third are on situations only: never judged
    assert invented[5] not in remainders  # 4 of the day and 4 invented make 8


def test_the_pairs_of_an_invented_reminder_are_keyed_by_its_remainder(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invented = [("quando apro Figma dopo le 23", "salvare il file")]
    monkeypatch.setattr(fixtures, "reminders", lambda count: invented[:count])
    assert harness.main(["label", "--data", str(data), "--reminders", "5"]) == 0
    labelled = labels.load(labels.path_for(data, date(2026, 10, 5)))
    assert "quando apro Figma" in {pair["remainder"] for pair in labelled.pairs}


def test_the_owner_checks_the_calls_and_the_report_counts_by_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The day of situations: the owner marks the Teams call wrong, and adds a Zoom call while
    the mail was in front, whose end "quando finisco la call" should have rung for."""
    database = tmp_path / "jiffin.db"
    a_day_of_situations(database)
    data = tmp_path / "prove"
    data.mkdir()
    snapshot.snapshot(database, data, datetime(2026, 10, 5, 18, tzinfo=UTC))
    served: list[page.PageServer] = []
    monkeypatch.setattr(page, "serve", lambda server, open_browser: served.append(server))
    assert harness.main(["label", "--data", str(data), "--calls", "--no-browser"]) == 0
    (server,) = served
    server.server_close()
    assert isinstance(server, page.CallsServer)
    owners = server.calls
    assert [(s["value"], s["before"], s["after"]) for s in owners.stretches] == [
        ("zoom.exe", CODE.app, CODE.app),
        ("ms-teams.exe", MAIL.app, MAIL.app),
        ("yes", TRAINS.app, TRAINS.app),  # lunch
        ("zoom.exe", TRAINS.app, TRAINS.app),  # cut by the app's close
    ]
    capsys.readouterr()
    assert harness.main(["report", "--data", str(data)]) == 0
    summary = capsys.readouterr().out
    assert (
        "Calls: 3 recorded; absences: 1 recorded. "
        "Not checked by the owner yet (label --calls): they count as recorded."
    ) in summary
    assert "Asked for with Remind here: 2 alerts, never the judge's." in summary
    assert (
        "Shown under the threshold, by why: for Remind here 1, under a lowered threshold 1."
    ) in summary
    shown = (data / "report-2026-10-05.html").read_text(encoding="utf-8").split("<h2>")[1]
    (trains,) = (row for row in shown.split("<tr>") if TRAINS.title in row and PAUSA[0] in row)
    assert f'<span class="yes">{HARNESS.report.right}</span>' in trains  # Remind here's label

    clock = SystemClock()
    owners.mark(owners.stretches[1]["key"], True)
    start, end = (f"{clock.local(T0 + minutes * MINUTE):%H:%M}" for minutes in (270, 290))
    owners.add("call", "zoom.exe", start, end, clock)
    owners.check(clock.local(T0 + 8 * HOUR_MS))
    assert harness.main(["report", "--data", str(data)]) == 0
    assert (
        "Calls: 3 recorded, 1 marked wrong, 1 added; absences: 1 recorded, 0 marked wrong, "
        "0 added. Checked by the owner."
    ) in capsys.readouterr().out
    detail = (data / "report-2026-10-05.html").read_text(encoding="utf-8")
    texts = HARNESS.report
    assert detail.count(texts.marked_wrong) == 1 and detail.count(texts.added) == 1
    assert texts.requested.format(count=2) in detail
    missed = detail.split(texts.units.format(count=1))[1]
    assert f'<td class="number">{end}</td>' in missed and CALL_ENDS[0] in missed
    assert harness.main(["replay", "--data", str(data)]) == 0  # by the owner's truth too


def test_a_not_here_said_today_on_yesterdays_alert_counts_from_then(tmp_path: Path) -> None:
    """The mail's reminder for tonight after 22 rang at 23:30 and went unanswered. It rings once
    in its window, which runs past midnight, so at 00:10 it keeps quiet; at 00:20 the owner says
    Not here on it from the tray list. The replay starts the day knowing that alert."""
    clock = SimulatedClock(T0 - 11 * HOUR_MS, UTC)  # 2026-10-04 22:00
    core = Reminders(FakeEngine(SITUATED), clock, lambda view: None, lambda view: None)
    rang: list[int] = []

    def owner(timeline: replay.Timeline, alert: Alert) -> None:
        replay.passive(timeline, alert)
        rang.append(alert.id)

    def see(at: int, context: Context | None) -> None:
        timeline.at(at, replay.observe(Observation(at, context)))

    timeline = replay.Timeline(core, clock, owner)
    tonight = replay.new_reminder("quando leggo la posta stasera dopo le 22", "rispondere")
    timeline.at(clock.now(), tonight)
    late = T0 - 9 * HOUR_MS - 30 * MINUTE  # 23:30
    see(late, MAIL)
    see(late + 10 * MINUTE, None)
    morning = T0 - 9 * HOUR_MS + 10 * MINUTE  # 00:10 of the 5th
    see(morning, MAIL)
    timeline.at(morning + 10 * MINUTE, lambda core: core.not_here(rang[0]))
    see(morning + 20 * MINUTE, None)
    timeline.run(morning + 30 * MINUTE)
    store = Store.open(tmp_path / "jiffin.db")
    store.save(timeline.records)
    log = store.log()
    store.close()
    day = days.select(log, None, SimulatedClock(T0, UTC))
    assert (len(rang), day.alerts) == (1, ())  # quiet at 00:10, in the same unit
    again = replay.Replay(log, day, zone=UTC).run()
    assert uncached(again) == uncached(day)


def test_the_replay_hears_only_the_situations_of_the_run_under_way(tmp_path: Path) -> None:
    """Yesterday a call ended with nothing in front, so "quando finisco la call" did not ring,
    and the app closed. Today the app starts again and hears the situations from its start: the
    replay of today must not hear yesterday's end either, or it would ring for it."""
    store = Store.open(tmp_path / "jiffin.db")
    clock = SimulatedClock(YESTERDAY, UTC)
    core = Reminders(FakeEngine(SITUATED), clock, lambda view: None, lambda view: None)
    timeline = replay.Timeline(core, clock, replay.passive)

    def situation(at: int, kind: Situation, values: frozenset[str] | None) -> None:
        timeline.at(at, replay.observe(SituationObservation(at, kind, values)))

    def starts(at: int) -> None:
        for kind, value in ((Situation.AWAY, "no"), (Situation.POWER, "plugged")):
            situation(at, kind, frozenset({value}))

    for condition, action in (CALL_ENDS, MAIL_AFTER_CALL):
        timeline.at(YESTERDAY, replay.new_reminder(condition, action))
    starts(YESTERDAY)
    situation(YESTERDAY + 10 * MINUTE, Situation.CALL, frozenset({"zoom.exe"}))
    situation(YESTERDAY + 40 * MINUTE, Situation.CALL, frozenset())  # nothing in front
    for kind in (Situation.AWAY, Situation.POWER, Situation.CALL):
        situation(YESTERDAY + 60 * MINUTE, kind, None)  # the app closes
    timeline.run(YESTERDAY + 60 * MINUTE)
    store.save(timeline.records)
    clock.advance(T0 - 5 * MINUTE - clock.now())
    core = Reminders(
        FakeEngine(SITUATED), clock, lambda view: None, lambda view: None, store.load()
    )
    timeline = replay.Timeline(core, clock, replay.passive)
    starts(clock.now())
    timeline.at(T0, replay.observe(Observation(T0, MAIL)))
    timeline.at(T0 + 10 * MINUTE, replay.observe(Observation(T0 + 10 * MINUTE, None)))
    timeline.run(T0 + 20 * MINUTE)
    store.save(timeline.records)
    log = store.log()
    store.close()
    day = days.select(log, None, SimulatedClock(T0, UTC))
    assert day.alerts == ()
    assert uncached(replay.Replay(log, day, zone=UTC).run()) == uncached(day)


def test_a_replay_runs_again_from_the_start(recorded: tuple[Log, days.Day]) -> None:
    log, day = recorded
    again = replay.Replay(log, day)
    assert signature(again.run()) == signature(again.run())
