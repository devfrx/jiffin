"""The words of the situations (ADR-0026, ADR-0028), from `it/situations.toml`: `SITUATIONS`, what
the grammar of `core` reads in a condition besides its time. The rules that put them together
are the grammar's."""

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
class Situations:
    read: Read


SITUATIONS = read(Situations, "situations.toml")
