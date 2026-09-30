from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context, Observation, normalize
from jiffin.core.debounce import DEBOUNCE_MS, Debounce, EvaluationRequest

START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
ROSSI = Context("code.exe", "changelog.md - rossi", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")


def observe(debounce: Debounce, clock: SimulatedClock, context: Context | None) -> None:
    assert debounce.observe(Observation(clock.now(), context)) is None


def test_a_context_is_requested_once_it_has_been_stable_for_20_seconds() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    assert debounce.deadline == START + DEBOUNCE_MS
    clock.advance(DEBOUNCE_MS - 1)
    assert debounce.poll(clock.now()) is None
    clock.advance(1)
    assert debounce.poll(clock.now()) == EvaluationRequest(ROSSI, context_since=START)


def test_a_stable_context_is_requested_only_once() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    clock.advance(DEBOUNCE_MS)
    assert debounce.poll(clock.now()) is not None
    assert debounce.deadline is None
    clock.advance(60_000)
    observe(debounce, clock, ROSSI)
    assert debounce.poll(clock.now()) is None


def test_the_request_carries_when_the_context_came_to_the_foreground() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    debounce.observe(
        Observation(clock.now(), normalize("Code.exe", "● changelog.md - rossi", None))
    )
    clock.advance(5_000)
    observe(debounce, clock, normalize("code.exe", "changelog.md - rossi", None))
    clock.advance(15_000)
    assert debounce.poll(clock.now()) == EvaluationRequest(ROSSI, context_since=START)


def test_a_change_before_20_seconds_starts_over() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    clock.advance(10_000)
    observe(debounce, clock, BANK)
    clock.advance(10_000)
    assert debounce.poll(clock.now()) is None
    clock.advance(10_000)
    assert debounce.poll(clock.now()) == EvaluationRequest(BANK, context_since=START + 10_000)


def test_a_context_that_comes_back_is_requested_again() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    clock.advance(DEBOUNCE_MS)
    assert debounce.poll(clock.now()) is not None
    observe(debounce, clock, BANK)
    clock.advance(5_000)
    observe(debounce, clock, ROSSI)
    clock.advance(DEBOUNCE_MS)
    assert debounce.poll(clock.now()) == EvaluationRequest(ROSSI, START + DEBOUNCE_MS + 5_000)


def test_no_context_is_never_requested_and_breaks_stability() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    clock.advance(10_000)
    observe(debounce, clock, None)
    assert debounce.deadline is None
    clock.advance(60_000)
    assert debounce.poll(clock.now()) is None
    observe(debounce, clock, ROSSI)
    assert debounce.deadline == clock.now() + DEBOUNCE_MS


def test_a_request_that_fell_due_is_not_lost_to_a_late_poll() -> None:
    clock, debounce = SimulatedClock(START), Debounce()
    observe(debounce, clock, ROSSI)
    clock.advance(25_000)
    due = debounce.observe(Observation(clock.now(), BANK))
    assert due == EvaluationRequest(ROSSI, context_since=START)
    assert debounce.deadline == START + 25_000 + DEBOUNCE_MS


def test_nothing_is_due_before_the_first_observation() -> None:
    debounce = Debounce()
    assert debounce.deadline is None
    assert debounce.poll(START) is None
