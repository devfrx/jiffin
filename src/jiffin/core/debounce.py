"""The debounce: a context is evaluated once it has stayed in the foreground for a while."""

from dataclasses import dataclass

from jiffin.core.context import Context, Observation

DEBOUNCE_MS = 20_000
"""How long a context must stay unchanged before it is evaluated (ADR-0007)."""


@dataclass(frozen=True, slots=True)
class EvaluationRequest:
    context: Context
    context_since: int
    """When the context came to the foreground, in UTC milliseconds (ADR-0013)."""


class Debounce:
    """Turns observations into one evaluation request per stable context.

    Every change of context starts over, "no context" included: a context that comes back
    is requested again once it has been stable again. Times come from the observations and
    from the caller, on the same clock.
    """

    def __init__(self) -> None:
        self._current: Context | None = None
        self._pending: EvaluationRequest | None = None

    @property
    def deadline(self) -> int | None:
        """When the pending request falls due, or None when nothing is pending."""
        if self._pending is None:
            return None
        return self._pending.context_since + DEBOUNCE_MS

    def observe(self, observation: Observation) -> EvaluationRequest | None:
        """Take an observation; return the previous context's request if it fell due by then."""
        due = self.poll(observation.at)
        if observation.context != self._current:
            self._current = observation.context
            self._pending = (
                None
                if observation.context is None
                else EvaluationRequest(observation.context, observation.at)
            )
        return due

    def poll(self, now: int) -> EvaluationRequest | None:
        """Return the request that is due at `now`, once."""
        deadline = self.deadline
        if deadline is None or now < deadline:
            return None
        due, self._pending = self._pending, None
        return due
