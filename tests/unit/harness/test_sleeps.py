from collections.abc import Sequence
from datetime import UTC

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Candidate,
    EngineSleep,
    Evaluation,
    NothingInFront,
    Outcome,
    Revision,
    SleepReason,
    Waker,
)
from jiffin.harness import day as days
from jiffin.harness.sleeps import NOT_RECORDED, SleepError, Sleeps, Wake, summarize
from jiffin.store.store import Log

T0 = 1_791_194_400_000  # 2026-10-05 10:00 UTC
MINUTE = 60_000
DAY = 24 * 60 * MINUTE
IDLE_LIMIT = 5 * MINUTE + 10_000
NOTHING_LIMIT = 10_000
"""ADR-0031: asleep within 5 minutes and 10 s of `core`'s last request, and within 10 s of
nothing in front."""
CLOCK = SimulatedClock(T0, UTC)
BUILD = EngineBuild(1, "0.3.0", "b11081", "79de5cb8", 1, 2)
FIGMA = Context("figma.exe", "Icone - Figma", None)
STARTED = NothingInFront(T0 - MINUTE, T0 - MINUTE + 1_000, startup=True)
"""The app started a minute before T0, and the capture saw a window at once."""


def judged(number: int, at: int, since: int | None = None, *, cached: bool = False) -> Evaluation:
    """An evaluation of a context stable since `since`, 5 s before by default: it asked the
    engine, unless its d came from the cache."""
    since = at - DEBOUNCE_MS if since is None else since
    candidate = Candidate(10, 0.5, cached, Outcome.BELOW_THRESHOLD)
    return Evaluation(number, at, FIGMA, since, 0.97, BUILD, (candidate,))


def summary(
    *evaluations: Evaluation,
    sleeps: Sequence[EngineSleep] = (),
    nothing: Sequence[NothingInFront] = (STARTED,),
    revisions: Sequence[Revision] = (),
    vram: Sequence[tuple[int, int]] = (),
) -> Sleeps:
    log = Log(
        (),
        {revision.id: revision for revision in revisions},
        evaluations,
        (),
        (),
        (),
        tuple(sleeps),
        tuple(nothing),
    )
    return summarize(log, days.select(log, None, CLOCK), CLOCK, vram)


def sleep(
    at: int,
    woken_at: int | None = None,
    by: Waker | None = None,
    ready_at: int | None = None,
    reason: SleepReason = SleepReason.IDLE,
) -> EngineSleep:
    return EngineSleep(at, reason, woken_at, by, ready_at)


# Recorded or not


def test_a_day_before_0_3_has_no_sleeps_recorded() -> None:
    assert summary(judged(1, T0), judged(2, T0 + 20 * MINUTE, cached=True), nothing=()) == (
        NOT_RECORDED
    )


def test_a_day_before_the_first_run_of_0_3_has_no_sleeps_recorded() -> None:
    later = NothingInFront(T0 + DAY, startup=True)
    assert summary(judged(1, T0), nothing=(later,)) == NOT_RECORDED


# Wakes


def test_a_wake_is_late_when_the_engine_is_ready_after_the_5_s_of_the_context_waiting() -> None:
    before = judged(1, T0 - 20 * MINUTE)
    woken = sleep(T0 - 10 * MINUTE, T0, Waker.CONTEXT, T0 + 6_500)
    waiting = judged(2, T0 + 6_900, since=T0)  # its 5 s ended at T0 + 5 s
    result = summary(before, waiting, sleeps=[woken])
    assert result.wakes == result.late == (Wake(T0, Waker.CONTEXT, 6.5, 1.5),)


def test_a_wake_within_the_5_s_is_not_late() -> None:
    woken = sleep(T0 - 10 * MINUTE, T0, Waker.CONTEXT, T0 + 3_100)
    result = summary(judged(1, T0 + 5_400, since=T0), sleeps=[woken])
    assert result.wakes == (Wake(T0, Waker.CONTEXT, 3.1, 0.0),)
    assert result.late == ()


def test_a_judgement_that_woke_the_engine_itself_waited_the_whole_wake() -> None:
    woken = sleep(T0 - 10 * MINUTE, T0 + 5_000, Waker.JUDGEMENT, T0 + 8_000)
    result = summary(judged(1, T0 + 8_400, since=T0), sleeps=[woken])
    assert result.late == (Wake(T0 + 5_000, Waker.JUDGEMENT, 3.0, 3.0),)


def test_a_wake_for_a_statement_is_never_late() -> None:
    woken = sleep(T0 - 10 * MINUTE, T0, Waker.STATEMENT, T0 + 9_000)
    result = summary(judged(1, T0 + 9_500, since=T0 - MINUTE), sleeps=[woken])
    assert result.wakes == (Wake(T0, Waker.STATEMENT, 9.0, 0.0),)
    assert result.late == ()


def test_a_wake_on_retry_is_late_only_for_a_context_that_came_during_it() -> None:
    woken = sleep(T0 - 10 * MINUTE, T0, Waker.RETRY, T0 + 4_000)
    result = summary(judged(1, T0 + 20 * MINUTE), sleeps=[woken])
    assert result.late == ()


def test_a_wake_without_the_model_is_counted_apart() -> None:
    failed = sleep(T0 - 10 * MINUTE, T0, Waker.CONTEXT)
    result = summary(judged(1, T0 + MINUTE), sleeps=[failed])
    assert (result.wakes, result.unready) == ((), 1)


def test_only_the_sleeps_and_wakes_of_the_day_count() -> None:
    yesterday = sleep(T0 - DAY, T0 - DAY + MINUTE, Waker.CONTEXT, T0 - DAY + MINUTE + 3_000)
    today = sleep(T0 + MINUTE, reason=SleepReason.NOTHING_IN_FRONT)
    started = NothingInFront(T0 - DAY - MINUTE, T0 - DAY - MINUTE + 1, startup=True)
    result = summary(
        judged(1, T0), judged(2, T0 + 2 * MINUTE), sleeps=[yesterday, today], nothing=[started]
    )
    assert result.slept == {SleepReason.NOTHING_IN_FRONT: 1}
    assert result.wakes == ()


# Sleep errors: 5 minutes idle


def test_an_evaluation_that_finds_the_engine_awake_5_min_10_s_after_the_last_request() -> None:
    result = summary(judged(1, T0), judged(2, T0 + IDLE_LIMIT + 1, cached=True))
    assert result.errors == (SleepError(T0 + IDLE_LIMIT, SleepReason.IDLE),)


def test_the_5_min_10_s_themselves_are_no_error() -> None:
    result = summary(judged(1, T0), judged(2, T0 + IDLE_LIMIT, cached=True))
    assert result.errors == ()


def test_a_sleep_later_than_5_min_10_s_after_the_last_request() -> None:
    late = sleep(T0 + IDLE_LIMIT + 1_000)
    assert summary(judged(1, T0), sleeps=[late]).errors == (
        SleepError(T0 + IDLE_LIMIT, SleepReason.IDLE),
    )


def test_each_request_starts_the_5_minutes_again() -> None:
    evaluations = [judged(n, T0 + n * 4 * MINUTE) for n in range(5)]
    on_time = sleep(T0 + 16 * MINUTE + IDLE_LIMIT)
    assert summary(*evaluations, sleeps=[on_time]).errors == ()


def test_an_awake_engine_counts_once_however_many_records_find_it() -> None:
    cached = [judged(n, T0 + n * 10 * MINUTE, cached=True) for n in range(1, 4)]
    result = summary(judged(0, T0), *cached)
    assert result.errors == (SleepError(T0 + IDLE_LIMIT, SleepReason.IDLE),)


def test_only_the_errors_of_the_day_count() -> None:
    started = NothingInFront(T0 - DAY - MINUTE, T0 - DAY - MINUTE + 1_000, startup=True)
    yesterday = [judged(1, T0 - DAY), judged(2, T0 - DAY + 10 * MINUTE, cached=True)]
    asleep = sleep(T0 - DAY + 11 * MINUTE)
    result = summary(*yesterday, judged(3, T0, cached=True), sleeps=[asleep], nothing=[started])
    assert result.errors == ()


def test_without_a_record_after_the_5_minutes_the_app_may_have_closed() -> None:
    assert summary(judged(1, T0)).errors == ()


def test_a_failed_evaluation_proves_the_app_ran_but_not_that_the_engine_was_awake() -> None:
    failed = Evaluation(2, T0 + 10 * MINUTE, FIGMA, T0, 0.97, None, (), failed=True)
    assert summary(judged(1, T0), failed).errors == (SleepError(T0 + IDLE_LIMIT, SleepReason.IDLE),)
    asleep = sleep(T0 + MINUTE)  # its wake was refused, for the GPU's memory
    later = judged(3, T0 + 20 * MINUTE, cached=True)
    assert summary(judged(1, T0), failed, later, sleeps=[asleep]).errors == ()


def test_a_wake_counts_as_a_request() -> None:
    """The context it came for may leave before its 5 s, with no request after the wake."""
    woken = sleep(T0 + 5 * MINUTE, T0 + 10 * MINUTE, Waker.CONTEXT, T0 + 10 * MINUTE + 3_000)
    found = judged(2, T0 + 16 * MINUTE, cached=True)
    result = summary(judged(1, T0), judged(3, T0 + 12 * MINUTE, cached=True), found, sleeps=[woken])
    assert result.errors == (SleepError(T0 + 10 * MINUTE + 3_000 + IDLE_LIMIT, SleepReason.IDLE),)


def test_a_new_run_of_the_app_starts_afresh() -> None:
    restarted = NothingInFront(T0 + 30 * MINUTE, T0 + 30 * MINUTE + 500, startup=True)
    result = summary(
        judged(1, T0), judged(2, T0 + 31 * MINUTE, cached=True), nothing=[STARTED, restarted]
    )
    assert result.errors == ()


def test_the_records_before_the_first_run_of_0_3_are_left_aside() -> None:
    first_run = NothingInFront(T0 + 20 * MINUTE, T0 + 20 * MINUTE + 500, startup=True)
    result = summary(
        judged(1, T0),
        judged(2, T0 + 10 * MINUTE, cached=True),
        judged(3, T0 + 21 * MINUTE, cached=True),
        nothing=[first_run],
    )
    assert result.errors == ()


# Sleep errors: nothing in front


def test_the_engine_sleeps_within_10_s_of_nothing_in_front() -> None:
    nothing = NothingInFront(T0 + MINUTE, T0 + 2 * MINUTE)
    for slept, errors in (
        (T0 + MINUTE + NOTHING_LIMIT, ()),
        (
            T0 + MINUTE + NOTHING_LIMIT + 1,
            (SleepError(T0 + MINUTE + NOTHING_LIMIT, SleepReason.NOTHING_IN_FRONT),),
        ),
    ):
        late = sleep(slept, reason=SleepReason.NOTHING_IN_FRONT)
        assert summary(judged(1, T0), sleeps=[late], nothing=[STARTED, nothing]).errors == errors


def test_an_engine_awake_through_nothing_in_front_is_found_when_something_comes_back() -> None:
    nothing = NothingInFront(T0 + MINUTE, T0 + MINUTE + 30_000)
    assert summary(judged(1, T0), nothing=[STARTED, nothing]).errors == (
        SleepError(T0 + MINUTE + NOTHING_LIMIT, SleepReason.NOTHING_IN_FRONT),
    )


def test_nothing_in_front_for_less_than_10_s_asks_nothing() -> None:
    nothing = NothingInFront(T0 + MINUTE, T0 + MINUTE + 8_000)
    assert summary(judged(1, T0), nothing=[STARTED, nothing]).errors == ()


def test_an_engine_asleep_before_nothing_came_in_front_is_fine() -> None:
    nothing = NothingInFront(T0 + 2 * MINUTE, T0 + 30 * MINUTE)
    asleep = sleep(T0 + MINUTE)
    assert summary(judged(1, T0), sleeps=[asleep], nothing=[STARTED, nothing]).errors == ()


def test_a_statement_written_with_nothing_in_front_gives_the_engine_10_s_more() -> None:
    """The creation window is one of Jiffin's: nothing is in front while it is open, and its
    statement wakes the engine, which goes back to sleep once it is written."""
    window = NothingInFront(T0 + MINUTE, T0 + 3 * MINUTE)
    asleep = sleep(T0 + MINUTE, T0 + 2 * MINUTE, Waker.STATEMENT, T0 + 2 * MINUTE + 3_000)
    written = Revision(
        10,
        1,
        1,
        "quando apro Figma",
        "esportare le icone",
        "quando apro Figma",
        "The user.",
        BUILD,
        created_at=T0 + 2 * MINUTE + 3_500,
    )
    for again, errors in (
        (T0 + 2 * MINUTE + 4_000, ()),
        (
            T0 + 2 * MINUTE + 20_000,
            (SleepError(T0 + 2 * MINUTE + 13_500, SleepReason.NOTHING_IN_FRONT),),
        ),
    ):
        result = summary(
            judged(1, T0),
            sleeps=[asleep, sleep(again, reason=SleepReason.NOTHING_IN_FRONT)],
            nothing=[STARTED, window],
            revisions=[written],
        )
        assert result.errors == errors


# The time asleep and the VRAM


def test_the_time_asleep_is_counted_within_the_days_active_time() -> None:
    first, last = judged(1, T0), judged(2, T0 + 60 * MINUTE)  # from T0 - 5 s
    night = sleep(T0 - 30 * MINUTE, T0 + 5 * MINUTE, Waker.CONTEXT, T0 + 5 * MINUTE + 3_000)
    napped = sleep(T0 + 10 * MINUTE, T0 + 20 * MINUTE, Waker.CONTEXT, T0 + 20 * MINUTE + 3_000)
    closed_asleep = sleep(T0 + 50 * MINUTE)  # the app closed, and started again at 55 min
    restarted = NothingInFront(T0 + 55 * MINUTE, T0 + 55 * MINUTE + 100, startup=True)
    result = summary(
        first, last, sleeps=[night, napped, closed_asleep], nothing=[STARTED, restarted]
    )
    asleep = (5 * MINUTE + DEBOUNCE_MS) + 10 * MINUTE + 5 * MINUTE
    assert (result.asleep_ms, result.active_ms) == (asleep, 60 * MINUTE + DEBOUNCE_MS)
    still = summary(first, last, sleeps=[closed_asleep])  # open until the end of the day
    assert still.asleep_ms == 10 * MINUTE


def test_the_vram_asleep_counts_after_the_first_10_s_of_each_sleep() -> None:
    asleep = sleep(T0 + 2 * MINUTE, T0 + 5 * MINUTE, Waker.CONTEXT, T0 + 5 * MINUTE + 3_000)
    rows = [
        (T0 + MINUTE, 3_247),
        (T0 + 2 * MINUTE + 5_000, 3_300),  # it has just judged, and lets the model go
        (T0 + 3 * MINUTE, 98),
        (T0 + 4 * MINUTE, 120),
        (T0 + 6 * MINUTE, 3_250),
    ]
    result = summary(judged(1, T0), judged(2, T0 + 7 * MINUTE), sleeps=[asleep], vram=rows)
    assert (result.vram_asleep_mib, result.vram_asleep_rows) == (120, 2)
    assert result.vram_awake_mib == 3_250
