"""The words of the situations (ADR-0026, ADR-0028), from `it/situations.toml`: `SITUATIONS`, what
the grammar of `core` reads in a condition besides its time, and what `ui.words` writes back. The
rules that put them together are the grammar's and `ui.words`'."""

from dataclasses import dataclass

from jiffin.lang import read


@dataclass(frozen=True, slots=True)
class CallWords:
    words: tuple[str, ...]
    before_app: tuple[str, ...]
    holds: tuple[str, ...]
    """{call} stands for one of `words`."""
    holds_verbs: tuple[str, ...]
    ends: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AwayWords:
    holds: tuple[str, ...]
    ends: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PowerWords:
    battery: tuple[str, ...]
    battery_verbs: tuple[str, ...]
    plugged: tuple[str, ...]
    plugged_verbs: tuple[str, ...]
    unplug: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DisplayWords:
    words: tuple[str, ...]
    connected: tuple[str, ...]
    """{display} stands for one of `words`, here and below."""
    disconnected: tuple[str, ...]
    disconnect: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HeadphonesWords:
    words: tuple[str, ...]
    on: tuple[str, ...]
    """{headphones} stands for one of `words`, here and below."""
    off: tuple[str, ...]
    take_off: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NetworkWords:
    home: tuple[str, ...]
    office: tuple[str, ...]
    offline: tuple[str, ...]
    verbs: tuple[str, ...]
    leave_home: tuple[str, ...]
    leave_office: tuple[str, ...]
    online: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Read:
    openers: tuple[str, ...]
    modifiers_before: tuple[str, ...]
    modifiers_after: tuple[str, ...]
    leftover: tuple[str, ...]
    lasting: tuple[str, ...]
    after_lasting: tuple[str, ...]
    call: CallWords
    away: AwayWords
    power: PowerWords
    display: DisplayWords
    headphones: HeadphonesWords
    network: NetworkWords


@dataclass(frozen=True, slots=True)
class DurationWrite:
    minute: str
    minutes: str
    hour: str
    hours: str
    half: str
    hours_and_minutes: str


@dataclass(frozen=True, slots=True)
class CallWrite:
    holds: str
    ends: str
    on: str


@dataclass(frozen=True, slots=True)
class AwayWrite:
    holds: str
    ends: str


@dataclass(frozen=True, slots=True)
class PowerWrite:
    battery: str
    plugged: str
    unplug: str


@dataclass(frozen=True, slots=True)
class DisplayWrite:
    connected: str
    disconnected: str
    disconnect: str


@dataclass(frozen=True, slots=True)
class HeadphonesWrite:
    on: str
    off: str
    take_off: str


@dataclass(frozen=True, slots=True)
class NetworkWrite:
    home: str
    office: str
    offline: str
    leave_home: str
    leave_office: str
    online: str


@dataclass(frozen=True, slots=True)
class Write:
    lasting: str
    duration: DurationWrite
    call: CallWrite
    away: AwayWrite
    power: PowerWrite
    display: DisplayWrite
    headphones: HeadphonesWrite
    network: NetworkWrite


@dataclass(frozen=True, slots=True)
class Situations:
    read: Read
    write: Write


SITUATIONS = read(Situations, "situations.toml")
