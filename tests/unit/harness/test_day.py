from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild
from jiffin.core.records import Alert, Answer, Candidate, Evaluation, Outcome, Revision
from jiffin.harness import day as days
from jiffin.harness.errors import HarnessError
from jiffin.store.store import Log

T0 = 1_791_194_400_000  # 2026-10-05 10:00 UTC
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
FIGMA = Context("figma.exe", "Icone - Figma", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")
MAIL = Context("outlook.exe", "Posta in arrivo", None)
ICONS = Revision(
    10, 1, 1, "quando apro Figma", "esportare le icone", "quando apro Figma", "Figma.", BUILD
)
RENT = Revision(
    20,
    2,
    1,
    "se sono sul sito della banca",
    "pagare l'affitto",
    "se sono sul sito della banca",
    "The bank.",
    BUILD,
)
REVISIONS = {10: ICONS, 20: RENT}


def judged(
    number: int,
    since: int,
    context: Context,
    icons: tuple[float, Outcome],
    rent: tuple[float, Outcome],
    *,
    cached: bool = False,
) -> Evaluation:
    candidates = (
        Candidate(10, icons[0], cached, icons[1]),
        Candidate(20, rent[0], cached, rent[1]),
    )
    return Evaluation(number, since + 20_000, context, since, 0.97, BUILD, candidates)


E1 = judged(1, T0, FIGMA, (2.5, Outcome.ALERT), (0.1, Outcome.BELOW_THRESHOLD))
E2 = judged(2, T0 + 120_000, BANK, (0.2, Outcome.BELOW_THRESHOLD), (0.99, Outcome.ALERT))
E3 = judged(3, T0 + 280_000, MAIL, (0.98, Outcome.ALERT), (0.3, Outcome.BELOW_THRESHOLD))
E4 = Evaluation(4, T0 + 600_000, FIGMA, T0 + 580_000, 0.97, None, (), failed=True)
E5 = judged(
    5, T0 + 1_200_000, FIGMA, (2.5, Outcome.HELD_BACK), (0.1, Outcome.BELOW_THRESHOLD), cached=True
)
YESTERDAY = judged(
    0, T0 - 86_400_000, MAIL, (0.1, Outcome.BELOW_THRESHOLD), (0.1, Outcome.BELOW_THRESHOLD)
)
A1 = Alert(1, 1, ICONS, 1, FIGMA, 2.5, E1.at, T0, shown_at=E1.at, answer=Answer.USEFUL)
A2 = Alert(2, 2, RENT, 2, BANK, 0.99, E2.at, E2.context_since, shown_at=E2.at + 5_000)
A3 = Alert(3, 1, ICONS, 3, MAIL, 0.98, E3.at, E3.context_since, shown_at=E3.at)
LOG = Log((), REVISIONS, (YESTERDAY, E1, E2, E3, E4, E5), (A1, A2, A3), (), ())
LABELS = {
    days.key(FIGMA, ICONS.remainder): True,
    days.key(FIGMA, RENT.remainder): True,  # never shown: below the threshold
    days.key(BANK, ICONS.remainder): False,
    days.key(BANK, RENT.remainder): True,
    days.key(MAIL, ICONS.remainder): False,  # a false alarm
}


def clock() -> SimulatedClock:
    return SimulatedClock(T0)


def test_a_day_is_a_local_day_the_last_one_by_default() -> None:
    today = days.select(LOG, None, clock())
    assert today.day == date(2026, 10, 5)
    assert today.evaluations == (E1, E2, E3, E4, E5)
    assert today.alerts == (A1, A2, A3)
    yesterday = days.select(LOG, date(2026, 10, 4), clock())
    assert (yesterday.evaluations, yesterday.alerts) == ((YESTERDAY,), ())


def test_a_log_with_no_evaluation_has_no_day() -> None:
    with pytest.raises(HarnessError, match="no evaluation"):
        days.select(Log((), {}, (), (), (), ()), None, clock())


def test_pairs_are_every_judged_context_and_reminder_once() -> None:
    found = days.pairs(days.select(LOG, None, clock()))
    assert [(pair.context, pair.revision.id) for pair in found.values()] == [
        (FIGMA, 10),
        (FIGMA, 20),
        (BANK, 10),
        (BANK, 20),
        (MAIL, 10),
        (MAIL, 20),
    ]


def test_a_key_depends_on_the_texts_only() -> None:
    same = days.key(Context("figma.exe", "Icone - Figma", None), "quando apro Figma")
    assert days.key(FIGMA, ICONS.remainder) == same
    assert days.key(Context("figma.exe", "Icone - Figma", ""), "quando apro Figma") != same
    assert days.key(FIGMA, "quando apro Sketch") != same


def test_the_summary_counts_evaluations_delays_misses_and_false_alarms() -> None:
    summary = days.summarize(days.select(LOG, None, clock()), LABELS, clock())
    assert summary == days.Summary(
        day=date(2026, 10, 5),
        evaluations=5,
        judged=3,  # the fifth came from the cache
        failed=1,
        hours=1_220_000 / 3_600_000,
        reminders=2,
        pauses=(),  # judged by version 0.1
        shown=3,
        time_only=0,
        delays=(20.0, 25.0, 20.0),
        pairs=6,
        labelled=5,
        relevant=3,
        missed={"below threshold": 1},
        alerted=3,
        false_alarms=1,
        unlabelled=0,
    )
    assert days.delay(summary, 50) == 20.0


def test_a_missed_pair_says_how_close_it_came() -> None:
    held = judged(6, T0 + 1_500_000, MAIL, (1.5, Outcome.HELD_BACK), (0.3, Outcome.BELOW_THRESHOLD))
    log = Log((), REVISIONS, (E1, held), (A1,), (), ())
    labels = {days.key(MAIL, ICONS.remainder): True}
    (missed,) = days.missed(days.select(log, None, clock()), labels, clock())
    assert (missed.pair.context, missed.why, missed.d) == (MAIL, "held back", 1.5)


# Version 0.2: times, and reminders with only a time (ADR-0021, ADR-0022)

WRITTEN = T0 - 3_600_000  # 09:00


def written(number: int, reminder_id: int, condition: str, action: str) -> Revision:
    """A revision as core makes it, its time read when it was written."""
    reading = read(condition, datetime.fromtimestamp(WRITTEN / 1000, UTC))
    statement = f"The user: {reading.remainder}." if reading.remainder else None
    return Revision(
        number,
        reminder_id,
        1,
        condition,
        action,
        reading.remainder,
        statement,
        BUILD if statement else None,
        schedule=reading.schedule,
        written_at=WRITTEN,
        created_at=WRITTEN,
    )


LATE = written(30, 3, "quando apro Figma dopo le 11", "salvare il file")
CALL = written(40, 4, "alle 10:30", "chiamare Rossi")
LOGO = Context("figma.exe", "Logo - Figma", None)


def test_a_pair_is_keyed_by_its_remainder_since_the_code_checks_the_time() -> None:
    assert LATE.remainder == ICONS.remainder == "quando apro Figma"
    assert days.Pair(FIGMA, LATE).key == days.Pair(FIGMA, ICONS).key
    assert days.Pair(FIGMA, LATE).key == days.key(FIGMA, "quando apro Figma")


def test_a_pair_true_only_out_of_its_time_is_not_missed() -> None:
    early = Evaluation(
        6, T0 + 20_000, FIGMA, T0, 0.97, BUILD, (Candidate(30, 2.5, False, Outcome.OUTSIDE_TIME),)
    )
    later = Evaluation(  # 11:30, within "dopo le 11"
        7,
        T0 + 5_420_000,
        LOGO,
        T0 + 5_400_000,
        0.97,
        BUILD,
        (Candidate(30, 0.2, False, Outcome.BELOW_THRESHOLD),),
    )
    log = Log((), {30: LATE}, (early, later), (), (), ())
    labels = {days.key(FIGMA, LATE.remainder): True, days.key(LOGO, LATE.remainder): True}
    day = days.select(log, None, clock())
    (missed,) = days.missed(day, labels, clock())
    assert (missed.pair.context, missed.why) == (LOGO, "below threshold")
    summary = days.summarize(day, labels, clock())
    assert (summary.pairs, summary.relevant, summary.missed) == (2, 1, {"below threshold": 1})


def test_a_day_keeps_the_alerts_of_reminders_with_only_a_time() -> None:
    called = Alert(4, 4, CALL, None, MAIL, None, T0 + 1_800_000, T0 + 1_800_000)
    yesterday = replace(called, id=3, created_at=T0 - 84_600_000, due_at=T0 - 84_600_000)
    log = Log((), REVISIONS | {40: CALL}, (YESTERDAY, E1), (yesterday, A1, called), (), ())
    assert days.select(log, None, clock()).alerts == (A1, called)


def test_false_alarms_count_each_wrong_pair_once_and_times_apart() -> None:
    again = judged(6, T0 + 1_500_000, MAIL, (0.98, Outcome.ALERT), (0.3, Outcome.BELOW_THRESHOLD))
    twice = Alert(4, 1, ICONS, 6, MAIL, 0.98, again.at, again.context_since, shown_at=again.at)
    called = Alert(
        5, 4, CALL, None, MAIL, None, T0 + 1_810_000, T0 + 1_800_000, shown_at=T0 + 1_810_000
    )
    log = Log((), REVISIONS | {40: CALL}, (E1, E2, E3, again), (A1, A2, A3, twice, called), (), ())
    summary = days.summarize(days.select(log, None, clock()), LABELS, clock())
    assert (summary.shown, summary.time_only) == (5, 1)
    assert (summary.alerted, summary.false_alarms, summary.unlabelled) == (3, 1, 0)
    assert summary.delays == (20.0, 25.0, 20.0, 20.0, 10.0)  # the time's, from its moment


def test_the_summary_tells_the_return_pauses_of_the_day() -> None:
    first = (replace(E1, return_pause=120_000), replace(E2, return_pause=120_000))
    longer = replace(E3, return_pause=600_000)
    one = Log((), REVISIONS, first, (), (), ())
    two = Log((), REVISIONS, (*first, longer), (), (), ())
    assert days.summarize(days.select(one, None, clock()), {}, clock()).pauses == (120_000,)
    assert days.summarize(days.select(two, None, clock()), {}, clock()).pauses == (
        120_000,
        600_000,
    )
