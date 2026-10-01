"""`convert`: the prototype's capture of a day as a copy of the app's log (ADR-0017).

The harness reads one format of recorded days, the app's own log; the prototype's capture of
2026-09-28 is converted once to be compared. `contesti-<day>.jsonl` holds one JSON line per
event: `context` when the window in front, its title or the address changed, `capture_start`
and `capture_stop`, and `idle_*` and `heartbeat`, which the app has no use for. The app's rules
apply (ADR-0004, context.md): a private window, or one whose privacy could not be told, is no
context; typing in the bar gives no address; an address counts only in the supported browsers.
The day goes through `core`, with the reminders the prototype judged that day and nobody
answering, and its records into a copy that the other commands read.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from jiffin.core.clock import SimulatedClock, SystemClock
from jiffin.core.context import BROWSER_SUFFIXES, Context, Observation, normalize
from jiffin.core.model import Model
from jiffin.core.reminders import Reminders
from jiffin.harness.errors import HarnessError
from jiffin.harness.replay import Timeline, new_reminder, observe, passive
from jiffin.store.store import Store


@dataclass(frozen=True, slots=True)
class Capture:
    observations: tuple[Observation, ...]
    end: int
    """When the capture stopped, or its last line when it was cut short."""


def read(path: Path) -> Capture:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise HarnessError(f"the capture cannot be read: {error.strerror}") from None
    found: list[Observation] = []
    end = 0
    for line in lines:
        try:
            row: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue  # a line cut short when the capture stopped
        at = round(datetime.fromisoformat(row["ts"]).timestamp() * 1000)
        end = at
        match row.get("type"):
            case "capture_start" | "capture_stop":
                found.append(Observation(at, None))
            case "context":
                found.append(Observation(at, _context(row)))
    if all(observation.context is None for observation in found):
        raise HarnessError(f"{path.name} holds no context")
    return Capture(tuple(found), end)


def convert(
    capture: Capture, reminders: Sequence[tuple[str, str]], model: Model, copy: Path
) -> None:
    """The day through `core`, with `reminders` from its start, into a new copy of the log."""
    if copy.exists():
        raise HarnessError(f"{copy.name} exists already: forget it first")
    begin = capture.observations[0].at - 1
    clock = SimulatedClock(begin, SystemClock().local(begin).tzinfo or UTC)
    timeline = Timeline(
        Reminders(model, clock, lambda view: None, lambda view: None), clock, passive
    )
    for condition, action in reminders:
        timeline.at(begin, new_reminder(condition, action))
    for observation in capture.observations:
        timeline.at(observation.at, observe(observation))
    timeline.run(capture.end)
    store = Store.open(copy)
    try:
        store.save(timeline.records)
    finally:
        store.close()


def _context(row: dict[str, Any]) -> Context | None:
    if row.get("private") is not False or row.get("title") is None:
        return None  # private, or its privacy could not be told
    exe = PureWindowsPath(row.get("exe") or "").name
    typing = bool(row.get("address_bar_focused"))
    context = normalize(exe, row["title"], None if typing else row.get("address_bar"))
    if context.app not in BROWSER_SUFFIXES and context.address is not None:
        return Context(context.app, context.title, None)
    return context
