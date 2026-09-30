from datetime import date

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import Alert, Answer, Candidate, Evaluation, Outcome, Revision
from jiffin.harness import day as days
from jiffin.harness.errors import HarnessError
from jiffin.store.store import Log

T0 = 1_791_194_400_000  # 2026-10-05 10:00 UTC
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
FIGMA = Context("figma", "Icone - Figma", None)
BANK = Context("vivaldi", "Banca Rossi", "bancarossi.it")
MAIL = Context("outlook", "Posta in arrivo", None)
ICONS = Revision(10, 1, 1, "quando apro Figma", "esportare le icone", "The user has Figma.", BUILD)
RENT = Revision(20, 2, 1, "se sono sul sito della banca", "pagare l'affitto", "The bank.", BUILD)
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
A1 = Alert(1, 1, ICONS, 1, FIGMA, 2.5, E1.at, shown_at=E1.at, answer=Answer.USEFUL)
A2 = Alert(2, 2, RENT, 2, BANK, 0.99, E2.at, shown_at=E2.at + 5_000)
A3 = Alert(3, 1, ICONS, 3, MAIL, 0.98, E3.at, shown_at=E3.at)
LOG = Log((), REVISIONS, (YESTERDAY, E1, E2, E3, E4, E5), (A1, A2, A3), ())
LABELS = {
    days.key(FIGMA, ICONS.condition): True,
    days.key(FIGMA, RENT.condition): True,  # never shown: below the threshold
    days.key(BANK, ICONS.condition): False,
    days.key(BANK, RENT.condition): True,
    days.key(MAIL, ICONS.condition): False,  # a false alarm
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
        days.select(Log((), {}, (), (), ()), None, clock())


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
    same = days.key(Context("figma", "Icone - Figma", None), "quando apro Figma")
    assert days.key(FIGMA, ICONS.condition) == same
    assert days.key(Context("figma", "Icone - Figma", ""), "quando apro Figma") != same
    assert days.key(FIGMA, "quando apro Sketch") != same


def test_the_summary_counts_evaluations_delays_misses_and_false_alarms() -> None:
    summary = days.summarize(days.select(LOG, None, clock()), LABELS)
    assert summary == days.Summary(
        day=date(2026, 10, 5),
        evaluations=5,
        judged=3,  # the fifth came from the cache
        failed=1,
        hours=1_220_000 / 3_600_000,
        reminders=2,
        shown=3,
        delays=(20.0, 25.0, 20.0),
        pairs=6,
        labelled=5,
        relevant=3,
        missed={"below threshold": 1},
        false_alarms=1,
        unlabelled_alerts=0,
    )
    assert days.delay(summary, 50) == 20.0


def test_a_missed_pair_says_how_close_it_came() -> None:
    held = judged(6, T0 + 1_500_000, MAIL, (1.5, Outcome.HELD_BACK), (0.3, Outcome.BELOW_THRESHOLD))
    log = Log((), REVISIONS, (E1, held), (A1,), ())
    labels = {days.key(MAIL, ICONS.condition): True}
    (missed,) = days.missed(days.select(log, None, clock()), labels)
    assert (missed.pair.context, missed.why, missed.d) == (MAIL, "held back", 1.5)
