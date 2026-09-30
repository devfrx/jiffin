import time

import pytest

from jiffin.core.clock import SimulatedClock, SystemClock


def test_the_system_clock_counts_utc_milliseconds() -> None:
    before = time.time_ns() // 1_000_000
    now = SystemClock().now()
    assert before <= now <= time.time_ns() // 1_000_000


def test_a_simulated_clock_moves_only_when_told_to() -> None:
    clock = SimulatedClock(start=1_000)
    assert clock.now() == 1_000
    clock.advance(250)
    assert clock.now() == 1_250


def test_a_simulated_clock_does_not_go_back() -> None:
    with pytest.raises(ValueError):
        SimulatedClock(start=1_000).advance(-1)
