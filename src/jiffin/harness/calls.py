"""`label --calls`: the owner's truth on the day's calls and absences (ADR-0031).

`core` reads the situations from states (ADR-0028), and the capture may miss a call, split one at
a mute, or end an absence that was only reading. A page lists the calls and the absences
recorded that day, with the app in front when each began and when it ended; the owner marks the
wrong ones (they did not happen, are split, or start or end more than a minute from the true
time), adds the true ones that are missing, and closes with "Controllato": only then do the
unmarked ones count as right. The other situations are cheap and reliable to read (ADR-0028),
and count as recorded.

The file, `calls-<day>.json` in the data folder, keys each recorded stretch by its situation,
value and start, so preparing it again from a new copy keeps the marks.
"""

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from jiffin.core.clock import Clock
from jiffin.core.records import Evaluation
from jiffin.core.situations import CALL_APPS, YES, Situation, SituationStretch
from jiffin.harness.errors import HarnessError

FORMAT = 1
APPS = {
    app.executables[0] if app.executables else app.sites[0]: app.title for app in CALL_APPS.values()
}
"""The value an added call gets, by the app the owner picks, with the name the page shows: one
`core` reads as a call on that app (`situations.holds`)."""
OTHER = "other"
"""The value of an added call on another app: a call for "in call", on no app a condition
names."""


@dataclass(slots=True)
class Calls:
    path: Path
    day: date
    stretches: list[dict[str, Any]]
    """The calls and the absences recorded: key, kind, value, since, until, and the apps in
    front when each began and when it ended, `before` and `after`."""
    wrong: list[str] = field(default_factory=list)
    """The keys of those the owner marked wrong."""
    added: list[dict[str, Any]] = field(default_factory=list)
    """Those the owner added: kind, value, since, until."""
    checked: str | None = None
    """When the owner pressed "Controllato"; None before, and again once new ones are
    recorded."""

    def mark(self, key: object, wrong: object) -> None:
        if key not in {stretch["key"] for stretch in self.stretches}:
            raise ValueError("unknown stretch")
        if not isinstance(wrong, bool):
            raise TypeError("wrong is true or false")
        self.wrong = [k for k in self.wrong if k != key] + ([str(key)] if wrong else [])
        self.save()

    def add(self, kind: object, value: object, start: object, end: object, clock: Clock) -> None:
        """A call or an absence the owner adds, from its local times "HH:MM" on the day."""
        if kind == Situation.CALL.value:
            if value not in APPS and value != OTHER:
                raise ValueError("unknown app")
        elif kind == Situation.AWAY.value:
            value = YES
        else:
            raise ValueError("a call or an absence")
        since, until = (self._instant(text, clock) for text in (start, end))
        if until <= since:
            raise ValueError("it ends before it starts")
        self.added.append({"kind": kind, "value": value, "since": since, "until": until})
        self.save()

    def remove(self, index: object) -> None:
        if not isinstance(index, int) or isinstance(index, bool):
            raise TypeError("an index")
        del self.added[index]
        self.save()

    def check(self, now: datetime) -> None:
        self.checked = now.isoformat(timespec="seconds")
        self.save()

    def save(self) -> None:
        record = {
            "format": FORMAT,
            "day": self.day.isoformat(),
            "stretches": self.stretches,
            "wrong": self.wrong,
            "added": self.added,
            "checked": self.checked,
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)

    def _instant(self, text: object, clock: Clock) -> int:
        if not isinstance(text, str):
            raise TypeError("a time is HH:MM")
        return clock.instant(self.day, time.fromisoformat(text))


def path_for(folder: Path, day: date) -> Path:
    return folder / f"calls-{day.isoformat()}.json"


def key(stretch: SituationStretch) -> str:
    text = json.dumps([stretch.situation.value, stretch.value, stretch.since])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def listed(stretch: SituationStretch) -> bool:
    """Whether the page lists it for the owner: a call, or an absence."""
    return stretch.situation is Situation.CALL or (
        stretch.situation is Situation.AWAY and stretch.value == YES
    )


def load(path: Path) -> Calls:
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HarnessError(f"the calls cannot be read: {error.strerror}") from None
    except json.JSONDecodeError as error:
        raise HarnessError(f"{path.name} is not valid JSON: {error}") from None
    if record.get("format") != FORMAT:
        raise HarnessError(f"{path.name} has format {record.get('format')}, not {FORMAT}")
    return Calls(
        path,
        date.fromisoformat(record["day"]),
        record["stretches"],
        list(record.get("wrong", [])),
        list(record.get("added", [])),
        record.get("checked"),
    )


def prepare(
    stretches: Iterable[SituationStretch],
    evaluations: Sequence[Evaluation],
    path: Path,
    day: date,
) -> Calls:
    """Write the day's recorded calls and absences, keeping the owner's marks and additions;
    the check is to do again when one is new."""
    calls = load(path) if path.exists() else Calls(path, day, [])
    known = {stretch["key"] for stretch in calls.stretches}
    calls.stretches = [
        {
            "key": key(stretch),
            "kind": stretch.situation.value,
            "value": stretch.value,
            "since": stretch.since,
            "until": stretch.until,
            "before": _in_front(evaluations, stretch.since),
            "after": _in_front(evaluations, stretch.until),
        }
        for stretch in stretches
        if listed(stretch)
    ]
    if any(stretch["key"] not in known for stretch in calls.stretches):
        calls.checked = None
    calls.save()
    return calls


def truth(recorded: Iterable[SituationStretch], calls: Calls | None) -> list[SituationStretch]:
    """The true stretches: those recorded, without the calls and absences the owner marked wrong
    and with those the owner added, once the owner checked them; those recorded before."""
    if calls is None or calls.checked is None:
        return list(recorded)
    wrong = set(calls.wrong)
    kept = [stretch for stretch in recorded if key(stretch) not in wrong]
    added = [
        SituationStretch(Situation(a["kind"]), a["value"], a["since"], a["until"])
        for a in calls.added
    ]
    return sorted([*kept, *added], key=lambda s: (s.since, s.situation, s.value))


def _in_front(evaluations: Sequence[Evaluation], at: int) -> str | None:
    """The app of the last context that came to the foreground by `at`, judged that day."""
    found = [e for e in evaluations if e.context_since <= at]
    return max(found, key=lambda e: e.context_since).context.app if found else None
