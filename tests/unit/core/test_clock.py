import time as clock_time
from datetime import date, time, timedelta, timezone

import pytest

from jiffin.core.clock import SimulatedClock, SystemClock


def test_the_system_clock_counts_utc_milliseconds() -> None:
    before = clock_time.time_ns() // 1_000_000
    now = SystemClock().now()
    assert before <= now <= clock_time.time_ns() // 1_000_000


def test_a_simulated_clock_moves_only_when_told_to() -> None:
    clock = SimulatedClock(start=1_000)
    assert clock.now() == 1_000
    clock.advance(250)
    assert clock.now() == 1_250


def test_a_simulated_clock_does_not_go_back() -> None:
    with pytest.raises(ValueError):
        SimulatedClock(start=1_000).advance(-1)


def test_a_simulated_clock_shows_the_local_time_of_its_zone() -> None:
    zone = timezone(timedelta(hours=2))
    clock = SimulatedClock(start=0, zone=zone)
    local = clock.local(0)
    assert (local.date(), local.time(), local.utcoffset()) == (
        date(1970, 1, 1),
        time(2),
        timedelta(hours=2),
    )
    assert clock.instant(date(1970, 1, 1), time(2)) == 0


def test_the_system_clock_converts_to_local_time_and_back() -> None:
    clock = SystemClock()
    instant = 1_790_000_000_123  # 2026-09-21: no time zone changes its clock that day
    local = clock.local(instant)
    assert local.timestamp() * 1000 == pytest.approx(instant)
    assert clock.instant(local.date(), local.time()) == instant
