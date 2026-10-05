"""`statements`: every reminder's condition beside the time understood, the remainder and the
English statement the engine judges (ADR-0008, ADR-0021).

On the acceptance day the owner checks that each statement says what its remainder says, and
that each time is read right: the alerts of a reminder with only a time are right when it is
(ADR-0022). A statement or a time that is wrong is fixed by editing the reminder.

The words of a time are the interface's (ADR-0020): `ui.words` is pure Python, without Qt, and
the one module of `ui` that the harness imports.
"""

from datetime import date
from pathlib import Path

from jiffin.core.clock import Clock
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild
from jiffin.core.records import Revision
from jiffin.core.schedule import jiffin_day
from jiffin.harness import render
from jiffin.store.store import Log
from jiffin.ui.words import when


def page(log: Log, copy: Path, folder: Path, clock: Clock) -> Path:
    today = jiffin_day(clock.local(clock.now()))
    rows = [
        {
            "number": reminder.id,
            "state": "attivo" if reminder.completed_at is None else "completato",
            "condition": reminder.revision.condition,
            "time": _time(reminder.revision, today),
            "unclear": _unclear(reminder.revision, clock),
            "remainder": reminder.revision.remainder,
            "action": reminder.revision.action,
            "statement": reminder.revision.statement,
            "build": _build(reminder.revision.statement_build),
        }
        for reminder in log.reminders
    ]
    path = folder / f"statements-{copy.stem}.html"
    return render.page("statements.html", path, copy=copy.name, rows=rows)


def _time(revision: Revision, today: date) -> str:
    """The time understood, as the creation window writes it on `today`; empty without one."""
    if revision.schedule is None:
        return ""
    return when(revision.schedule, revision.perennial, today)


def _unclear(revision: Revision, clock: Clock) -> str:
    """The words of a time not understood, as written: the reminder rings at any time. A
    condition of version 0.1 was never read for a time."""
    if revision.schedule is not None or revision.written_at is None:
        return ""
    reading = read(revision.condition, clock.local(revision.written_at))
    return ", ".join(revision.condition[start:end] for start, end in reading.unclear)


def _build(build: EngineBuild | None) -> str:
    if build is None:
        return ""
    return f"motore {build.engine_version}, prompt {build.rewrite_prompt}"
