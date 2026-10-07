"""The situations over time, as the capture observes them (ADR-0028)."""

import pytest

from jiffin.core.situations import (
    CALL_APPS,
    CHANGE_MS,
    HOME,
    NO,
    OFFICE,
    YES,
    Holds,
    Situation,
    SituationObservation,
    Situations,
    SituationStretch,
    holds,
)

START = 1_790_000_000_000
ZOOM = "zoom.exe"
TEAMS_CALLS = "ms-teams_modulehost.exe"
CHROME = "chrome.exe"
MEET = "meet.google.com"


def observe(situations: Situations, at: int, situation: Situation, *values: str) -> None:
    situations.observe(SituationObservation(at, situation, frozenset(values)))


def poll_until(situations: Situations, until: int) -> list[Situation]:
    """Poll every deadline up to `until`, as `core` does; the situations changed."""
    changed = []
    while (deadline := situations.deadline) is not None and deadline <= until:
        changed += situations.poll(deadline)
    return changed


# What holds


@pytest.mark.parametrize(
    ("value", "values", "expected"),
    [
        (None, {ZOOM}, True),
        (None, set(), False),
        ("zoom", {ZOOM}, True),
        ("zoom", {"app.zoom.us"}, True),
        ("zoom", {"discord.exe"}, False),
        ("teams", {TEAMS_CALLS}, True),
        ("meet", {MEET}, True),
        ("meet", {"zoom.us"}, False),
        # A browser whose tab that records cannot be read counts whole: the mistake that shows.
        ("meet", {CHROME}, True),
        ("zoom", {CHROME}, True),
        ("discord", {ZOOM, "discord.exe"}, True),
        # Another browser is a call, but on no app by name.
        ("meet", {"msedge.exe"}, False),
        (None, {"msedge.exe"}, True),
    ],
)
def test_a_call_holds_on_its_app_or_any_call(
    value: str | None, values: set[str], expected: bool
) -> None:
    assert holds(Situation.CALL, value, frozenset(values)) is expected


def test_the_other_situations_hold_with_their_value_and_a_situation_not_read_never() -> None:
    assert holds(Situation.NETWORK, HOME, frozenset({HOME}))
    assert not holds(Situation.NETWORK, HOME, frozenset({OFFICE}))
    assert not holds(Situation.NETWORK, HOME, frozenset())
    assert holds(Situation.HEADPHONES, NO, frozenset({NO}))
    assert not holds(Situation.HEADPHONES, YES, None)
    assert not holds(Situation.CALL, None, None)


def test_every_call_app_has_a_name_and_an_executable_or_a_site() -> None:
    for app in CALL_APPS.values():
        assert app.names
        assert app.executables or app.sites
        assert all(name == name.lower() for name in app.names)


# Over time


def test_a_change_counts_after_5_s_and_holds_from_when_it_came() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.CALL)])
    observe(situations, START, Situation.CALL, ZOOM)
    assert situations.deadline == START + CHANGE_MS
    assert poll_until(situations, START + CHANGE_MS - 1) == []
    assert situations.since(Situation.CALL, None) is None
    assert poll_until(situations, START + CHANGE_MS) == [Situation.CALL]
    assert situations.since(Situation.CALL, None) == START
    assert situations.deadline is None


def test_a_microphone_that_stops_for_2_s_does_not_end_the_call() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.CALL)])
    observe(situations, START, Situation.CALL, ZOOM)
    poll_until(situations, START + CHANGE_MS)
    observe(situations, START + 60_000, Situation.CALL)
    observe(situations, START + 62_000, Situation.CALL, ZOOM)
    assert situations.deadline is None
    assert poll_until(situations, START + 120_000) == []
    assert situations.since(Situation.CALL, None) == START
    assert situations.ended(Situation.CALL, None) is None
    assert situations.take_records() == []


def test_a_stretch_ends_when_its_value_left_and_is_recorded_once() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.CALL)])
    observe(situations, START, Situation.CALL, ZOOM)
    poll_until(situations, START + CHANGE_MS)
    observe(situations, START + 60_000, Situation.CALL)
    assert situations.take_records() == []
    assert poll_until(situations, START + 65_000) == [Situation.CALL]
    assert situations.since(Situation.CALL, None) is None
    assert situations.ended(Situation.CALL, None) == START + 60_000
    assert situations.take_records() == [
        SituationStretch(Situation.CALL, ZOOM, START, START + 60_000)
    ]
    assert situations.take_records() == []


def test_each_value_has_its_own_stretches() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.CALL, "zoom"), Holds(Situation.CALL)])
    observe(situations, START, Situation.CALL, ZOOM)
    poll_until(situations, START + CHANGE_MS)
    observe(situations, START + 60_000, Situation.CALL, ZOOM, "discord.exe")
    poll_until(situations, START + 65_000)
    observe(situations, START + 120_000, Situation.CALL, "discord.exe")
    poll_until(situations, START + 125_000)
    assert situations.since(Situation.CALL, "zoom") is None
    assert situations.ended(Situation.CALL, "zoom") == START + 120_000
    assert situations.since(Situation.CALL, None) == START
    assert situations.ended(Situation.CALL, None) is None
    assert situations.take_records() == [
        SituationStretch(Situation.CALL, ZOOM, START, START + 120_000)
    ]


def test_a_call_that_moves_between_the_tab_and_its_browser_goes_on() -> None:
    """The tab in front records, then another is in front: the browser counts whole."""
    situations = Situations()
    situations.follow([Holds(Situation.CALL, "meet")])
    observe(situations, START, Situation.CALL, MEET)
    poll_until(situations, START + CHANGE_MS)
    observe(situations, START + 60_000, Situation.CALL, CHROME)
    poll_until(situations, START + 65_000)
    assert situations.since(Situation.CALL, "meet") == START
    assert situations.ended(Situation.CALL, "meet") is None
    assert situations.take_records() == [
        SituationStretch(Situation.CALL, MEET, START, START + 60_000)
    ]


def test_the_last_change_counts_from_when_it_came() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.NETWORK, HOME), Holds(Situation.NETWORK, OFFICE)])
    observe(situations, START, Situation.NETWORK, HOME)
    observe(situations, START + 2_000, Situation.NETWORK, OFFICE)
    assert poll_until(situations, START + 6_000) == []
    assert poll_until(situations, START + 7_000) == [Situation.NETWORK]
    assert situations.since(Situation.NETWORK, OFFICE) == START + 2_000
    assert situations.since(Situation.NETWORK, HOME) is None
    assert situations.ended(Situation.NETWORK, HOME) is None  # it never counted


def test_a_situation_not_read_any_more_ends_its_stretches_at_once_but_did_not_end() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.HEADPHONES, YES)])
    observe(situations, START, Situation.HEADPHONES, YES)
    poll_until(situations, START + CHANGE_MS)
    situations.observe(SituationObservation(START + 60_000, Situation.HEADPHONES, None))
    assert situations.deadline is None
    assert situations.since(Situation.HEADPHONES, YES) is None
    assert situations.ended(Situation.HEADPHONES, YES) is None
    assert situations.take_records() == [
        SituationStretch(Situation.HEADPHONES, YES, START, START + 60_000)
    ]


def test_what_holds_when_it_is_first_followed_holds_from_when_it_came() -> None:
    situations = Situations()
    observe(situations, START, Situation.NETWORK, HOME)
    poll_until(situations, START + CHANGE_MS)
    assert situations.since(Situation.NETWORK, HOME) == START
    assert situations.since(Situation.NETWORK, OFFICE) is None


def test_a_state_read_at_start_is_no_end() -> None:
    situations = Situations()
    situations.follow([Holds(Situation.CALL)])
    observe(situations, START, Situation.CALL)
    poll_until(situations, START + CHANGE_MS)
    assert situations.ended(Situation.CALL, None) is None
    assert situations.take_records() == []
