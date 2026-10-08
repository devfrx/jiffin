"""`statements`: every reminder's condition beside the time and the situations understood, the
remainder and the English statement the engine judges (ADR-0008, ADR-0021, ADR-0028).

On the acceptance day the owner checks that each statement says what its remainder says, and
that each time and situation is read right: the alerts of a reminder without a remainder are
right when they are (ADR-0022, ADR-0031). A statement, a time or a situation that is wrong is
fixed by editing the reminder.

The words of a time are the interface's (ADR-0020): `ui.words` is pure Python, without Qt, and
the one module of `ui` that the harness imports. Those of the situations are provisional, in
`harness.toml`, until the interface writes them too (#153).
"""

from datetime import date
from pathlib import Path

from jiffin.core.clock import Clock
from jiffin.core.meanings import read
from jiffin.core.model import EngineBuild
from jiffin.core.records import Revision
from jiffin.core.schedule import jiffin_day
from jiffin.core.situations import CALL_APPS, Ends, Holds, Lasts, Situation, Term
from jiffin.harness import render
from jiffin.harness.calls import name
from jiffin.lang.harness import HARNESS
from jiffin.store.store import Log
from jiffin.ui.words import when


def page(log: Log, copy: Path, folder: Path, clock: Clock) -> Path:
    today = jiffin_day(clock.local(clock.now()))
    texts = HARNESS.statements
    rows = [
        {
            "number": reminder.id,
            "state": texts.active if reminder.completed_at is None else texts.completed,
            "condition": reminder.revision.condition,
            "time": _time(reminder.revision, today),
            "situations": ", ".join(_term(term) for term in reminder.revision.situations),
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


def _term(term: Term) -> str:
    texts = HARNESS.statements
    match term:
        case Holds(situation, value):
            return _situation(situation, value)
        case Ends(situation, value):
            return texts.ends.format(situation=_situation(situation, value))
        case Lasts(minutes, situation, value):
            if situation is None:  # the thing of the condition, which the judge checks
                return texts.lasting.format(minutes=minutes)
            return texts.lasts.format(situation=_situation(situation, value), minutes=minutes)


def _situation(situation: Situation, value: str | None) -> str:
    if situation is Situation.CALL and value is not None:
        return HARNESS.statements.call_on.format(app=name(CALL_APPS[value]))
    return HARNESS.statements.understood[situation if value is None else f"{situation} {value}"]


def _unclear(revision: Revision, clock: Clock) -> str:
    """The words of a time or a situation not understood, as written: the reminder rings at any
    time, or as if they were not there (ADR-0028). A condition of version 0.1 was never read."""
    if revision.written_at is None:
        return ""
    reading = read(revision.condition, clock.local(revision.written_at))
    return ", ".join(revision.condition[start:end] for start, end in reading.unclear)


def _build(build: EngineBuild | None) -> str:
    if build is None:
        return ""
    return HARNESS.statements.written_by.format(
        engine=build.engine_version, prompt=build.rewrite_prompt
    )
