from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Alert,
    Answer,
    Candidate,
    ContextAnswer,
    Evaluation,
    Here,
    Left,
    Outcome,
    Reminder,
    Revision,
)
from jiffin.core.situations import Ends, Holds, Lasts, Situation, SituationStretch
from jiffin.harness import calls
from jiffin.harness import day as days
from jiffin.harness.errors import HarnessError
from jiffin.harness.truth import Truth
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
        reminded={},
        alerted=3,
        false_alarms=1,
        unlabelled=0,
    )
    assert days.delay(summary, 50) == 20.0


@pytest.mark.parametrize(
    ("outcome", "d", "why", "missed"),
    [
        (Outcome.BELOW_THRESHOLD, 0.5, "below threshold", True),
        (Outcome.ALERT, 1.5, "waited", True),  # made, and never on screen
        (Outcome.SAME_OCCASION, 1.5, "same occasion", False),
        (Outcome.HELD_BACK, 1.5, "held back", False),  # the hour of version 0.1
        (Outcome.SNOOZED, 1.5, "snoozed", False),
        (Outcome.SILENCED, 1.5, "silenced", False),
    ],
)
def test_a_pair_never_shown_is_missed_unless_kept_quiet_as_already_reminded(
    outcome: Outcome, d: float, why: str, missed: bool
) -> None:
    """Its reminder had rung in the same unit, or the user had answered it (ADR-0025)."""
    later = judged(6, T0 + 1_500_000, MAIL, (d, outcome), (0.3, Outcome.BELOW_THRESHOLD))
    log = Log((), REVISIONS, (E1, later), (A1,), (), ())
    labels = {days.key(MAIL, ICONS.remainder): True}
    day = days.select(log, None, clock())
    (pair,) = days.unshown(day, labels, clock())
    assert (pair.pair.context, pair.why, pair.d, pair.missed) == (MAIL, why, d, missed)
    summary = days.summarize(day, labels, clock())
    assert (summary.missed, summary.reminded) == (({why: 1}, {}) if missed else ({}, {why: 1}))
    assert summary.relevant == 1  # the share keeps them all as its base


def test_a_pair_whose_own_alert_never_reached_the_screen_is_missed() -> None:
    """The alert waited for a place, and the occasion it used kept the pair quiet after."""
    made = judged(6, T0 + 1_500_000, MAIL, (1.5, Outcome.ALERT), (0.3, Outcome.BELOW_THRESHOLD))
    again = judged(
        7,
        T0 + 1_700_000,
        MAIL,
        (1.5, Outcome.SAME_OCCASION),
        (0.3, Outcome.BELOW_THRESHOLD),
        cached=True,
    )
    waiting = Alert(4, 1, ICONS, 6, MAIL, 1.5, made.at, made.context_since)
    log = Log((), REVISIONS, (E1, made, again), (A1, waiting), (), ())
    labels = {days.key(MAIL, ICONS.remainder): True}
    (pair,) = days.unshown(days.select(log, None, clock()), labels, clock())
    assert (pair.why, pair.missed) == ("waited", True)


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
        situations=reading.situations,
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
    (missed,) = days.unshown(day, labels, clock())
    assert (missed.pair.context, missed.why) == (LOGO, "below threshold")
    summary = days.summarize(day, labels, clock())
    assert (summary.pairs, summary.relevant, summary.missed) == (2, 1, {"below threshold": 1})


def test_a_day_keeps_the_alerts_of_reminders_with_only_a_time() -> None:
    called = Alert(4, 4, CALL, None, MAIL, None, T0 + 1_800_000, T0 + 1_800_000)
    yesterday = replace(called, id=3, created_at=T0 - 84_600_000, due_at=T0 - 84_600_000)
    log = Log((), REVISIONS | {40: CALL}, (YESTERDAY, E1), (yesterday, A1, called), (), ())
    assert days.select(log, None, clock()).alerts == (A1, called)


def test_a_day_keeps_the_alerts_asked_for_with_remind_here_apart() -> None:
    asked = Alert(4, 2, RENT, None, BANK, 0.5, T0 + 60_000, T0 + 60_000, requested=True)
    log = Log((), REVISIONS, (E1,), (A1, asked), (), ())
    day = days.select(log, None, clock())
    assert (day.alerts, day.requested) == ((A1,), (asked,))
    assert days.summarize(day, {}, clock()).requested == 1


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


# Version 0.3: the situations, and what Remind here teaches (ADR-0028, ADR-0029, ADR-0031)

MINUTE = 60_000
CODE = Context("code.exe", "main.py - Visual Studio Code", None)
GMAIL = Context("vivaldi.exe", "Posta - Gmail", "mail.google.com")
CALENDAR = Context("outlook.exe", "Calendario", None)
ENDS = written(50, 5, "quando finisco la call", "segnare le decisioni")
ON_TEAMS = written(60, 6, "quando sono in call su Teams", "chiedere la data a Bianchi")
AFTER = written(70, 7, "quando finisco la call e leggo la posta", "mandare il riassunto")
AGENDA = written(80, 8, "quando sono in call su Teams e apro il calendario", "segnare la data")
SITUATED = {revision.id: revision for revision in (ENDS, ON_TEAMS, AFTER, AGENDA)}
ZOOM_CALL = SituationStretch(Situation.CALL, "zoom.exe", T0, T0 + 30 * MINUTE)  # 10:00-10:30
PHANTOM = SituationStretch(Situation.CALL, "zoom.exe", T0 + 45 * MINUTE, T0 + 47 * MINUTE)
PLUGGED = SituationStretch(Situation.POWER, "plugged", T0 - 60 * MINUTE, T0 + 240 * MINUTE)


def at_minute(
    number: int, minute: int, context: Context, *scores: tuple[float, Outcome]
) -> Evaluation:
    """An evaluation of `context`, there since `minute` after 10:00, of After and Agenda."""
    since = T0 + minute * MINUTE
    candidates = tuple(
        Candidate(revision.id, d, False, outcome)
        for revision, (d, outcome) in zip((AFTER, AGENDA), scores, strict=True)
    )
    return Evaluation(number, since + 5_000, context, since, 0.97, BUILD, candidates)


def shown(
    number: int,
    revision: Revision,
    evaluation: Evaluation | None,
    context: Context,
    due: int,
    d: float | None = None,
) -> Alert:
    made = due + 5_000
    return Alert(
        number,
        revision.reminder_id,
        revision,
        None if evaluation is None else evaluation.id,
        context,
        d,
        made,
        due,
        shown_at=made,
    )


BELOW = (-3.0, Outcome.BELOW_THRESHOLD)
E_CODE = at_minute(11, 20, CODE, BELOW, BELOW)
E_MAIL = at_minute(12, 40, MAIL, (1.2, Outcome.ALERT), BELOW)
E_GMAIL = at_minute(13, 48, GMAIL, (1.2, Outcome.ALERT), BELOW)  # after the phantom call
E_CALENDAR = at_minute(14, 65, CALENDAR, BELOW, (1.5, Outcome.OUTSIDE_SITUATION))
SITUATED_LOG = Log(
    tuple(Reminder(r.reminder_id, WRITTEN, r) for r in SITUATED.values()),
    SITUATED,
    (E_CODE, E_MAIL, E_GMAIL, E_CALENDAR),
    (
        shown(11, ENDS, None, CODE, ZOOM_CALL.until),
        shown(13, AFTER, E_MAIL, MAIL, E_MAIL.context_since, 1.2),
        shown(12, ENDS, None, MAIL, PHANTOM.until),
        shown(14, AFTER, E_GMAIL, GMAIL, E_GMAIL.context_since, 1.2),
    ),
    (),
    (
        Left(CODE, E_CODE.context_since, E_MAIL.context_since),
        Left(MAIL, E_MAIL.context_since, E_GMAIL.context_since),
        Left(GMAIL, E_GMAIL.context_since, E_CALENDAR.context_since),
        Left(CALENDAR, E_CALENDAR.context_since, T0 + 90 * MINUTE),
    ),
    situations=(PLUGGED, ZOOM_CALL, PHANTOM),
)
SITUATED_LABELS = {
    days.key(context, revision.remainder): (context, revision)
    in {(MAIL, AFTER), (GMAIL, AFTER), (CALENDAR, AGENDA)}
    for context in (CODE, MAIL, GMAIL, CALENDAR)
    for revision in (AFTER, AGENDA)
}


def owners_truth(folder: Path, day: days.Day) -> Truth:
    """The owner marks the phantom call wrong, and adds the Teams call from 11:00 to 11:20 that
    the capture missed."""
    owners = calls.prepare(
        day.situations, day.evaluations, calls.path_for(folder, day.day), day.day
    )
    owners.mark(calls.key(PHANTOM), True)
    owners.add("call", "ms-teams.exe", "11:00", "11:20", clock())
    owners.check(clock().local(T0))
    return Truth.of(day.situations, owners)


def test_the_conditions_read_as_the_situated_day_needs() -> None:
    assert (ENDS.remainder, ENDS.situations) == ("", (Ends(Situation.CALL),))
    assert ON_TEAMS.situations == (Holds(Situation.CALL, "teams"),)
    assert (AFTER.remainder, AGENDA.remainder) == (
        "quando leggo la posta",
        "quando apro il calendario",
    )
    assert AGENDA.situations == (Holds(Situation.CALL, "teams"),)


def test_as_recorded_every_situation_is_read_right() -> None:
    day = days.select(SITUATED_LOG, None, clock())
    summary = days.summarize(day, SITUATED_LABELS, clock())
    assert (summary.shown, summary.time_only, summary.situated) == (4, 0, 2)
    assert (summary.relevant, summary.missed, summary.false_alarms) == (4, {}, 0)
    assert (summary.alerted, summary.situated_pairs, summary.misread) == (4, 2, 0)


def test_the_owners_truth_counts_the_situations_read_wrong(tmp_path: Path) -> None:
    day = days.select(SITUATED_LOG, None, clock())
    truth = owners_truth(tmp_path, day)
    summary = days.summarize(day, SITUATED_LABELS, clock(), truth)
    assert summary.missed == {days.NOT_READ: 2, "outside its situation": 1}
    assert summary.relevant == 6  # 3 pairs, a unit rung right and the 2 the capture missed
    assert (summary.alerted, summary.situated_pairs, summary.situated_wrong) == (4, 2, 1)
    assert (summary.false_alarms, summary.misread, summary.unlabelled) == (2, 1, 0)


def test_the_units_of_the_reminders_without_a_remainder(tmp_path: Path) -> None:
    day = days.select(SITUATED_LOG, None, clock())
    units = days.situated(day, owners_truth(tmp_path, day), clock())
    assert [unit.key for unit in units.right] == [(5, ZOOM_CALL.until)]
    assert [unit.key for unit in units.wrong] == [(5, PHANTOM.until)]
    teams = T0 + 60 * MINUTE
    assert sorted(unit.key for unit in units.missed) == [(5, teams + 20 * MINUTE), (6, teams)]


def test_a_pair_read_outside_its_true_situation_is_missed(tmp_path: Path) -> None:
    day = days.select(SITUATED_LOG, None, clock())
    (pair,) = days.unshown(day, SITUATED_LABELS, clock(), owners_truth(tmp_path, day))
    assert (pair.pair.context, pair.pair.revision, pair.why, pair.missed) == (
        CALENDAR,
        AGENDA,
        "outside its situation",
        True,
    )
    assert days.unshown(day, SITUATED_LABELS, clock()) == []  # as recorded, no call on Teams


PAUSE = written(90, 9, "se non sto lavorando", "fare stretching")
TRAINS = Context("vivaldi.exe", "Offerte treni", "treni.it")
SPORT = Context("vivaldi.exe", "Notizie sportive", "sport.it")


def test_alerts_under_the_threshold_are_told_apart_by_why() -> None:
    """Remind here said in the trains; the sport news under a threshold it lowered; the bank
    over the threshold (ADR-0029)."""
    evaluations = tuple(
        Evaluation(
            number,
            T0 + minute * MINUTE + 5_000,
            context,
            T0 + minute * MINUTE,
            0.97,
            BUILD,
            (Candidate(90, d, False, Outcome.ALERT),),
        )
        for number, minute, context, d in (
            (21, 0, TRAINS, 0.9),
            (22, 10, SPORT, 0.8),
            (23, 20, BANK, 1.5),
        )
    )
    alerts = tuple(
        shown(
            number,
            PAUSE,
            evaluation,
            evaluation.context,
            evaluation.context_since,
            evaluation.candidates[0].d,
        )
        for number, evaluation in zip((21, 22, 23), evaluations, strict=True)
    )
    said = ContextAnswer(9, TRAINS, Here.YES, 0.9, BUILD, T0 - 60 * MINUTE)
    log = Log((Reminder(9, WRITTEN, PAUSE),), {90: PAUSE}, evaluations, alerts, (said,), ())
    summary = days.summarize(days.select(log, None, clock()), {}, clock())
    assert summary.learned == {days.FOR_YES: 1, days.LOWERED: 1}


YOUTUBE = written(100, 10, "quando sono su YouTube da più di 20 minuti", "fare una pausa")


def test_a_thing_relevant_once_its_occasion_lasted_by_the_labels() -> None:
    """Two videos a minute apart make one occasion of 25 minutes, and the judge missed both:
    the second is relevant, since the occasion reached 20 minutes while it was in front; a third
    video alone, of 5 minutes, is not."""
    videos = [Context("vivaldi.exe", f"Video {n} - YouTube", "youtube.com") for n in (1, 2, 3)]
    stretches = ((0, 11), (12, 25), (60, 65))
    evaluations = tuple(
        Evaluation(
            number,
            T0 + since * MINUTE + 5_000,
            video,
            T0 + since * MINUTE,
            0.97,
            BUILD,
            (Candidate(100, 0.5, False, Outcome.BELOW_THRESHOLD),),
        )
        for number, video, (since, _) in zip((31, 32, 33), videos, stretches, strict=True)
    )
    left = tuple(
        Left(video, T0 + since * MINUTE, T0 + until * MINUTE)
        for video, (since, until) in zip(videos, stretches, strict=True)
    )
    log = Log((Reminder(10, WRITTEN, YOUTUBE),), {100: YOUTUBE}, evaluations, (), (), left)
    labels = {days.key(video, YOUTUBE.remainder): True for video in videos}
    day = days.select(log, None, clock())
    (missed,) = days.unshown(day, labels, clock())
    assert (YOUTUBE.situations, missed.pair.context, missed.why) == (
        (Lasts(20),),
        videos[1],
        "below threshold",
    )
    assert days.summarize(day, labels, clock()).relevant == 1


def test_two_alerts_in_one_call_are_one_pair_of_its_unit() -> None:
    """On Teams rings when a Teams call starts and, after a Snooze, again in the same call: one
    unit of its situation, so one pair (ADR-0031)."""
    teams = SituationStretch(Situation.CALL, "ms-teams.exe", T0 + 100 * MINUTE, T0 + 140 * MINUTE)
    alerts = (
        shown(21, ON_TEAMS, None, CALENDAR, teams.since),
        shown(22, ON_TEAMS, None, CALENDAR, teams.since + 20 * MINUTE),
    )
    log = replace(SITUATED_LOG, alerts=alerts, situations=(*SITUATED_LOG.situations, teams))
    day = days.select(log, None, clock())
    units = days.situated(day, Truth.of(day.situations, None), clock())
    assert [unit.key for unit in units.right] == [(6, teams.since)]


def test_a_day_holds_the_stretches_that_touch_it() -> None:
    start, end = days.bounds(date(2026, 10, 5), clock())
    hour = 60 * MINUTE
    before = SituationStretch(Situation.CALL, "zoom.exe", start - 2 * hour, start - hour)
    across = SituationStretch(Situation.AWAY, "yes", start - hour, start + hour)
    after = SituationStretch(Situation.CALL, "zoom.exe", end, end + hour)
    log = replace(SITUATED_LOG, situations=(before, across, *SITUATED_LOG.situations, after))
    assert days.select(log, None, clock()).situations == (across, *SITUATED_LOG.situations)


def test_a_unit_is_missed_only_while_its_reminder_is_in_force(tmp_path: Path) -> None:
    """Ends was done at 10:50, before the Teams call the capture missed: only On Teams should
    have rung in it."""
    reminders = tuple(
        replace(reminder, completed_at=T0 + 50 * MINUTE)
        if reminder.id == ENDS.reminder_id
        else reminder
        for reminder in SITUATED_LOG.reminders
    )
    day = days.select(replace(SITUATED_LOG, reminders=reminders), None, clock())
    units = days.situated(day, owners_truth(tmp_path, day), clock())
    assert [unit.key for unit in units.missed] == [(6, T0 + 60 * MINUTE)]


def test_a_call_split_by_the_capture_rings_a_wrong_end_and_misses_nothing(
    tmp_path: Path,
) -> None:
    """The capture split the Zoom call at a mute: Ends rang at 10:12, which the owner's whole
    call does not bear out, and at 10:30, which it does; so the call misses no unit."""
    first = replace(ZOOM_CALL, until=T0 + 12 * MINUTE)
    second = replace(ZOOM_CALL, since=T0 + 13 * MINUTE)
    alerts = (shown(21, ENDS, None, CODE, first.until), shown(22, ENDS, None, CODE, second.until))
    log = replace(SITUATED_LOG, alerts=alerts, situations=(PLUGGED, first, second))
    day = days.select(log, None, clock())
    path = calls.path_for(tmp_path, day.day)
    owners = calls.prepare(day.situations, day.evaluations, path, day.day)
    owners.mark(calls.key(first), True)
    owners.mark(calls.key(second), True)
    owners.add("call", "zoom.exe", "10:00", "10:30", clock())
    owners.check(clock().local(T0))
    units = days.situated(day, Truth.of(day.situations, owners), clock())
    assert [unit.key for unit in units.wrong] == [(5, first.until)]
    assert [unit.key for unit in units.right] == [(5, second.until)]
    assert units.missed == ()


def test_a_call_cut_by_the_close_ends_no_unit(tmp_path: Path) -> None:
    """The app closed at 11:10, during a Teams call the capture missed: On Teams should have
    rung at its start, and Ends not at the close, which `core` never hears as an end."""
    closed = replace(PLUGGED, until=T0 + 70 * MINUTE)
    log = replace(SITUATED_LOG, situations=(closed, ZOOM_CALL, PHANTOM))
    day = days.select(log, None, clock())
    owners = calls.prepare(
        day.situations, day.evaluations, calls.path_for(tmp_path, day.day), day.day
    )
    owners.add("call", "ms-teams.exe", "11:00", "11:10", clock())
    owners.check(clock().local(T0))
    units = days.situated(day, Truth.of(day.situations, owners), clock())
    assert [unit.key for unit in units.missed] == [(6, T0 + 60 * MINUTE)]


def test_an_alert_under_the_threshold_is_for_a_remind_here_said_before_it() -> None:
    alert = shown(13, AFTER, E_MAIL, MAIL, E_MAIL.context_since, 0.5)
    said = ContextAnswer(AFTER.reminder_id, MAIL, Here.YES, 0.5, BUILD, alert.created_at + 1_000)
    day = replace(days.select(SITUATED_LOG, None, clock()), answers=(said,))
    assert days.under(day, alert) == days.LOWERED
    earlier = replace(said, at=alert.created_at - 1_000)
    assert days.under(replace(day, answers=(earlier,)), alert) == days.FOR_YES
