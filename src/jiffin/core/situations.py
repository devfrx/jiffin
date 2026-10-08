"""The situations: what Jiffin knows beyond the window in front, and how a condition names them
(ADR-0028).

Jiffin reads states, never texts: whether an app captures from a microphone, the user is away,
the PC runs on battery, an external display or headphones are connected, which network it is
on, and whether something plays. The capture observes each one at its changes and at start, as
the values it has: the apps in a call, or one value, or none. `meanings.read` finds them in a
condition as terms, `Holds`, `Ends` and `Lasts`; `Situations` follows them over time, and the
stretches of each value, as records.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from jiffin.core.context import BROWSER_SUFFIXES

CHANGE_MS = 5_000
"""How long a change of a situation must last to count, as a context's (ADR-0019): a microphone
that stops for 2 s does not end a call. A starting number, assumed until real calls measure it
(ADR-0028)."""
AWAY_MS = 180_000
"""How long without a key or the mouse makes the user away, as ActivityWatch's (ADR-0028): a
starting number too, until real days tell whether it suits "quando torno"."""


class Situation(StrEnum):
    """A state the capture observes, as values over time (ADR-0028); the names are the owner's."""

    CALL = "call"
    """An app captures from a microphone: its values are those apps' executables, or for a
    browser the site of the tab in front that records, when its name can be read."""
    AWAY = "away"
    """No key or mouse for `AWAY_MS`, and no call nor anything playing in that time; or the PC
    locked or asleep: `YES` or `NO`."""
    POWER = "power"
    """`BATTERY` or `PLUGGED`."""
    DISPLAY = "display"
    """An external display is connected: `YES` or `NO`."""
    HEADPHONES = "headphones"
    """The default output is headphones or a headset: `YES` or `NO`."""
    NETWORK = "network"
    """`HOME` or `OFFICE`, by the labels of the settings; `OFFLINE`; no value on a network without
    a label."""
    PLAYBACK = "playback"
    """Something plays, through Windows' media controls: its values are the ids Windows gives
    those apps, in lower case (`spotify.exe`, `vivaldi.<id>`). No words name it: it keeps `AWAY`
    off in front of a video."""


YES = "yes"
NO = "no"
BATTERY = "battery"
PLUGGED = "plugged"
HOME = "home"
OFFICE = "office"
OFFLINE = "offline"
"""No network."""


@dataclass(frozen=True, slots=True)
class CallApp:
    """An app for calls, as a condition names it: "in call su Zoom". Names, not Italian
    (ADR-0028)."""

    names: tuple[str, ...]
    """As a condition writes them, in lower case."""
    executables: tuple[str, ...]
    sites: tuple[str, ...]
    """The domains of its pages: a site is one of them, or under one."""


CALL_APPS = {
    "discord": CallApp(("discord",), ("discord.exe",), ("discord.com",)),
    "meet": CallApp(("meet", "google meet"), (), ("meet.google.com",)),
    "slack": CallApp(("slack",), ("slack.exe",), ("app.slack.com",)),
    "teams": CallApp(
        ("teams", "microsoft teams"),
        # Since January 2026 its calls run in a process of their own (Microsoft's MC1189656).
        ("ms-teams.exe", "ms-teams_modulehost.exe"),
        ("teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft"),
    ),
    "telegram": CallApp(("telegram",), ("telegram.exe",), ("web.telegram.org",)),
    "whatsapp": CallApp(("whatsapp",), ("whatsapp.exe",), ("web.whatsapp.com",)),
    "zoom": CallApp(("zoom",), ("zoom.exe",), ("zoom.us",)),
}
"""The call apps a condition may name, by the name its terms keep: a closed list (ADR-0028)."""


def holds(situation: Situation, value: str | None, values: frozenset[str] | None) -> bool:
    """Whether a situation with `values` holds with `value`: for a call, a call on the app named
    `value`, or any call for None; for the others, that value. None, a situation not read, never
    holds."""
    if values is None:
        return False
    if situation is Situation.CALL:
        if value is None:
            return bool(values)
        return any(_on(CALL_APPS[value], found) for found in values)
    return value in values


def _on(app: CallApp, value: str) -> bool:
    """Whether a value of `CALL` is a call on `app`. A browser whose tab that records could not be
    read counts whole: its call may be on any app with a site, the mistake that shows."""
    if value in app.executables:
        return True
    if value in BROWSER_SUFFIXES:
        return bool(app.sites)
    return any(value == site or value.endswith(f".{site}") for site in app.sites)


# The terms of a condition


@dataclass(frozen=True, slots=True)
class Holds:
    """The situation holds: "quando sono in call", "a batteria", "senza cuffie"."""

    situation: Situation
    value: str | None = None
    """The value it holds with, as `holds` reads it: for a call the name of an app of
    `CALL_APPS`, or None for any call."""


@dataclass(frozen=True, slots=True)
class Ends:
    """A stretch of the situation has just ended: "quando finisco la call", "quando tolgo le
    cuffie", "quando torno", the end of `AWAY`."""

    situation: Situation
    value: str | None = None


@dataclass(frozen=True, slots=True)
class Lasts:
    """The stretch of a situation, or the occasion of the thing the judge checks, has lasted at
    least `minutes`: "in call da più di un'ora", "quando sono su YouTube da più di 20 minuti"."""

    minutes: int
    situation: Situation | None = None
    """None for the thing the judge checks."""
    value: str | None = None


type Term = Holds | Ends | Lasts


# Over time


@dataclass(frozen=True, slots=True)
class SituationObservation:
    """What the capture saw of a situation, at a change or at start: what the context port
    delivers besides the window in front (ADR-0012, ADR-0028)."""

    at: int
    """UTC milliseconds."""
    situation: Situation
    values: frozenset[str] | None
    """All its values now; None when it is not read any more: at the app's end, or when the
    capture loses it."""


@dataclass(frozen=True, slots=True)
class SituationStretch:
    """A stretch of one value of a situation, from when it arrived to when it left, recorded once
    it ended: for the table `situation`, as `Left` is for contexts."""

    situation: Situation
    value: str
    since: int
    until: int


@dataclass(slots=True)
class _State:
    """What the capture observed of one situation."""

    values: frozenset[str] | None = None
    """The values that count: None until a first change counts, and once it is not read."""
    arrived: dict[str, int] = field(default_factory=dict)
    """When each value of `values` arrived."""
    pending: frozenset[str] | None = None
    """The values observed since `pending_since`, which do not count yet; None while the values
    observed are those that count."""
    pending_since: int = 0


@dataclass(slots=True)
class _Run:
    """How a situation holds with a value: when it began, and when it last stopped."""

    since: int | None = None
    """When it began to hold, while it holds; None while it does not."""
    ended: int | None = None
    """When it last stopped holding, by a change that counted."""


class Situations:
    """The situations over time, from the capture's observations (ADR-0028). A change counts once
    it has lasted `CHANGE_MS`, and one observed and then back is none; then its values hold from
    when they arrived, and the values gone left then. `core` counts the 5 s, so that a replay
    gives the same stretches.

    Times come from the observations and from the caller, on the same clock: whoever drives it
    polls each `deadline` before giving it a later observation.
    """

    def __init__(self) -> None:
        self._states: dict[Situation, _State] = {}
        self._runs: dict[tuple[Situation, str | None], _Run] = {}
        """How each situation followed holds, by the situation and the value it holds with."""
        self._records: list[SituationStretch] = []

    def take_records(self) -> list[SituationStretch]:
        """The stretches that ended since the last call, in order."""
        records, self._records = self._records, []
        return records

    @property
    def deadline(self) -> int | None:
        """When a change observed counts, unless the values change again first."""
        return min(
            (
                state.pending_since + CHANGE_MS
                for state in self._states.values()
                if state.pending is not None
            ),
            default=None,
        )

    def observe(self, observation: SituationObservation) -> None:
        state = self._states.setdefault(observation.situation, _State())
        if observation.values is None:
            # Not read any more: no change of the user's, and nothing to wait for.
            state.pending = None
            self._count(observation.situation, None, observation.at)
        elif observation.values == state.values:
            state.pending = None  # back before the change counted
        elif observation.values != state.pending:
            state.pending, state.pending_since = observation.values, observation.at

    def poll(self, now: int) -> list[Situation]:
        """Count the changes due at `now`: the situations whose values have changed."""
        changed = []
        for situation, state in self._states.items():
            if state.pending is not None and state.pending_since + CHANGE_MS <= now:
                values, state.pending = state.pending, None
                self._count(situation, values, state.pending_since)
                changed.append(situation)
        return changed

    def follow(self, terms: Iterable[Term]) -> None:
        """Follow the situations of the terms from now on, besides those followed already. What
        holds now holds from when its values arrived; an end before now is not known."""
        for term in terms:
            if term.situation is None or (term.situation, term.value) in self._runs:
                continue
            state = self._states.get(term.situation, _State())
            arrived = [
                at
                for value, at in state.arrived.items()
                if holds(term.situation, term.value, frozenset({value}))
            ]
            self._runs[(term.situation, term.value)] = _Run(min(arrived, default=None))

    def since(self, situation: Situation, value: str | None) -> int | None:
        """When the situation began to hold with `value`, if it holds now."""
        return self._run(situation, value).since

    def ended(self, situation: Situation, value: str | None) -> int | None:
        """When the situation last stopped holding with `value`, by a change that counted."""
        return self._run(situation, value).ended

    def _run(self, situation: Situation, value: str | None) -> _Run:
        self.follow([Holds(situation, value)])
        return self._runs[(situation, value)]

    def _count(self, situation: Situation, values: frozenset[str] | None, at: int) -> None:
        """The values that count change at `at`: the stretches of those gone end there."""
        state = self._states[situation]
        old = state.values
        for gone in sorted((old or frozenset()) - (values or frozenset())):
            self._records.append(SituationStretch(situation, gone, state.arrived.pop(gone), at))
        for come in (values or frozenset()) - (old or frozenset()):
            state.arrived[come] = at
        state.values = values
        for (kind, value), run in self._runs.items():
            if kind is not situation:
                continue
            was, now = holds(kind, value, old), holds(kind, value, values)
            if now and not was:
                run.since = at
            elif was and not now:
                run.since = None
                if values is not None:  # a situation not read any more did not end
                    run.ended = at
