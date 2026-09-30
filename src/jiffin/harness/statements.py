"""`statements`: every reminder's condition beside the English statement the engine judges.

On the acceptance day the owner checks that each statement says what its condition says
(ADR-0008); a statement that does not is fixed by editing the reminder.
"""

from pathlib import Path

from jiffin.core.model import EngineBuild
from jiffin.harness import render
from jiffin.store.store import Log


def page(log: Log, copy: Path, folder: Path) -> Path:
    rows = [
        {
            "number": reminder.id,
            "state": "attivo" if reminder.completed_at is None else "completato",
            "condition": reminder.revision.condition,
            "action": reminder.revision.action,
            "statement": reminder.revision.statement,
            "build": _build(reminder.revision.statement_build),
        }
        for reminder in log.reminders
    ]
    path = folder / f"statements-{copy.stem}.html"
    return render.page("statements.html", path, copy=copy.name, rows=rows)


def _build(build: EngineBuild | None) -> str:
    if build is None:
        return ""
    return f"motore {build.engine_version}, prompt {build.rewrite_prompt}"
