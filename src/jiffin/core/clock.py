"""The clock port: the current time, in UTC milliseconds (ADR-0012).

Deadlines are times on the same clock: a part that waits for one exposes it, and whoever
drives the part calls it back once the clock reaches it.
"""

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> int:
        """The current time, in UTC milliseconds."""
        ...


class SystemClock:
    def now(self) -> int:
        return time.time_ns() // 1_000_000


class SimulatedClock:
    """A clock that moves only when told to, for tests and for the harness."""

    def __init__(self, start: int) -> None:
        self._now = start

    def now(self) -> int:
        return self._now

    def advance(self, milliseconds: int) -> None:
        if milliseconds < 0:
            raise ValueError("a clock does not go back")
        self._now += milliseconds
