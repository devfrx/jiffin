"""The clock port: the current time in UTC milliseconds, and the local calendar (ADR-0012).

Deadlines are times on the same clock: a part that waits for one exposes it, and whoever
drives the part calls it back once the clock reaches it.
"""

import time as clock_time
from datetime import UTC, date, datetime, time, tzinfo
from typing import Protocol


class Clock(Protocol):
    def now(self) -> int:
        """The current time, in UTC milliseconds."""
        ...

    def local(self, instant: int) -> datetime:
        """The local date and time at `instant`."""
        ...

    def instant(self, day: date, at: time) -> int:
        """When the local clock shows `at` on `day`."""
        ...


class SystemClock:
    """Windows' clock and time zone, daylight saving included."""

    def now(self) -> int:
        return clock_time.time_ns() // 1_000_000

    def local(self, instant: int) -> datetime:
        return datetime.fromtimestamp(instant / 1000, UTC).astimezone()

    def instant(self, day: date, at: time) -> int:
        # A naive datetime is read in the system's zone, with its daylight-saving rules.
        return round(datetime.combine(day, at).timestamp() * 1000)


class SimulatedClock:
    """A clock that moves only when told to, for tests and for the harness."""

    def __init__(self, start: int, zone: tzinfo = UTC) -> None:
        self._now = start
        self._zone = zone

    def now(self) -> int:
        return self._now

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("a clock does not go back")
        self._now += milliseconds

    def local(self, instant: int) -> datetime:
        return datetime.fromtimestamp(instant / 1000, self._zone)

    def instant(self, day: date, at: time) -> int:
        return round(datetime.combine(day, at, self._zone).timestamp() * 1000)
