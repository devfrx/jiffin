from dataclasses import replace
from datetime import UTC, date
from pathlib import Path

from jiffin.core.clock import SimulatedClock
from jiffin.core.records import Revision
from jiffin.core.situations import NO, YES, Ends, Holds, Lasts, Situation, SituationStretch, Term
from jiffin.harness import calls, truth
from jiffin.harness.truth import Truth

T0 = 1_791_190_800_000  # 2026-10-05 09:00 UTC
DAY = date(2026, 10, 5)
MINUTE = 60_000
CALL, AWAY, POWER = Situation.CALL, Situation.AWAY, Situation.POWER


def at(minutes: float) -> int:
    return T0 + round(minutes * MINUTE)


def stretch(kind: Situation, value: str, since: float, until: float) -> SituationStretch:
    return SituationStretch(kind, value, at(since), at(until))


ZOOM = stretch(CALL, "zoom.exe", 60, 90)
TEAMS = stretch(CALL, "ms-teams.exe", 85, 100)  # overlaps Zoom: one call, for "in call"
LUNCH = stretch(AWAY, YES, 180, 200)
LATE = stretch(CALL, "zoom.exe", 230, 240)  # a call cut by the app's close
RECORDED = (
    stretch(AWAY, NO, 0, 180),
    stretch(POWER, "plugged", 0, 240),
    ZOOM,
    TEAMS,
    LUNCH,
    stretch(AWAY, NO, 200, 240),
    LATE,
)


def revision(*terms: Term, perennial: bool = False, written: float = -60) -> Revision:
    return Revision(
        1,
        1,
        1,
        "condizione",
        "azione",
        "",
        written_at=at(written),
        perennial=perennial,
        situations=terms,
    )


def test_a_situation_holds_over_its_stretches_merged_where_they_touch() -> None:
    assert truth.intervals(RECORDED, CALL, None) == [(at(60), at(100)), (at(230), at(240))]
    assert truth.intervals(RECORDED, CALL, "zoom") == [(at(60), at(90)), (at(230), at(240))]
    assert truth.intervals(RECORDED, CALL, "teams") == [(at(85), at(100))]


def test_no_end_where_the_situations_stopped_being_read() -> None:
    recorded = Truth.of(RECORDED, None)
    assert recorded.unread == frozenset({at(240)})
    assert truth.ends(RECORDED, CALL, None, recorded.unread) == [at(100)]  # not at the close


def test_what_held_is_borne_out_within_a_minute() -> None:
    on_teams = revision(Holds(CALL, "teams"))
    recorded = Truth.of(RECORDED, None)
    assert truth.supported(on_teams, at(85) - 59_000, recorded)
    assert not truth.supported(on_teams, at(85) - 61_000, recorded)
    assert truth.supported(on_teams, at(100.5), recorded)
    assert not truth.supported(on_teams, at(70), recorded)  # Zoom then


def test_an_end_is_borne_out_by_a_true_end_within_a_minute_of_the_recorded_one() -> None:
    ends = revision(Ends(CALL))
    recorded = Truth.of(RECORDED, None)
    assert truth.rang_for(Ends(CALL), at(105), recorded) == at(100)
    assert truth.supported(ends, at(105), recorded)
    later = replace(TEAMS, until=at(102))  # the call went on 2 minutes longer
    true = tuple(later if s == TEAMS else s for s in RECORDED)
    corrected = replace(recorded, true=true, added=(later,), wrong=(TEAMS,), checked=True)
    assert not truth.supported(ends, at(105), corrected)
    assert not truth.supported(ends, at(50), recorded)  # no end yet


def test_a_duration_is_borne_out_once_reached_within_a_minute() -> None:
    long = revision(Lasts(30, CALL))
    recorded = Truth.of(RECORDED, None)
    assert truth.supported(long, at(89.5), recorded)  # 60 + 30, a minute early at most
    assert not truth.supported(long, at(88), recorded)


def test_an_end_holds_from_when_it_came_after_the_condition_was_written() -> None:
    clock = SimulatedClock(T0, UTC)
    recorded = Truth.of(RECORDED, None)
    assert truth.holds_at(revision(Ends(CALL)), at(150), recorded, clock)
    assert not truth.holds_at(revision(Ends(CALL)), at(99), recorded, clock)
    assert not truth.holds_at(revision(Ends(CALL), written=101), at(150), recorded, clock)
    assert truth.holds_at(revision(Ends(AWAY, YES)), at(210), recorded, clock)
    assert truth.holds_at(revision(Holds(AWAY, YES)), at(190), recorded, clock)
    assert not truth.holds_at(revision(Lasts(30, AWAY, YES)), at(195), recorded, clock)


def test_ogni_volta_holds_an_end_only_within_its_jiffin_day() -> None:
    clock = SimulatedClock(T0, UTC)
    every = revision(Ends(CALL), perennial=True)
    assert truth.holds_at(every, at(150), Truth.of(RECORDED, None), clock)
    assert not truth.holds_at(every, at(24 * 60), Truth.of(RECORDED, None), clock)


def test_the_owners_truth_counts_once_checked(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    owners = calls.prepare(RECORDED, (), calls.path_for(tmp_path, DAY), DAY)
    owners.mark(calls.key(TEAMS), True)
    owners.add("call", "zoom.exe", "11:00", "11:20", clock)
    assert Truth.of(RECORDED, owners).true == RECORDED  # not checked yet
    owners.check(clock.local(at(600)))
    checked = Truth.of(RECORDED, owners)
    added = stretch(CALL, "zoom.exe", 120, 140)
    assert (checked.wrong, checked.added, checked.checked) == ((TEAMS,), (added,), True)
    assert truth.intervals(checked.true, CALL, None)[:2] == [(at(60), at(90)), (at(120), at(140))]
