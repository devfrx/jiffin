"""What `core` knows, as plain data: the records that `store` keeps (ADR-0013, ADR-0014)."""

from dataclasses import dataclass
from enum import StrEnum

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild


@dataclass(frozen=True, slots=True)
class Revision:
    """A version of a reminder's text. The statement comes later, from the engine."""

    id: int
    reminder_id: int
    number: int
    condition: str
    """The "Quando" box, in Italian: "quando apro Figma"."""
    action: str
    """The "Ricordami di" box: "esportare le icone"."""
    statement: str | None = None
    """The condition as one English statement, once the engine has written it (ADR-0008)."""
    statement_build: EngineBuild | None = None


@dataclass(frozen=True, slots=True)
class Reminder:
    """A reminder with its current revision. Saving it saves the revision too."""

    id: int
    created_at: int
    revision: Revision
    completed_at: int | None = None
    snoozed_until: int | None = None
    """Set by Rimanda. Once past, it lifts the once-an-hour rule until the next alert."""


@dataclass(frozen=True, slots=True)
class ReminderDeleted:
    """The reminder is gone, and everything about it with it (ADR-0014)."""

    reminder_id: int


@dataclass(frozen=True, slots=True)
class Silence:
    """ "Non qui": the reminder keeps quiet in this context until its text changes."""

    reminder_id: int
    context: Context


@dataclass(frozen=True, slots=True)
class SilencesCleared:
    reminder_id: int


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """The d of a revision in a context, from one engine build (ADR-0004)."""

    context: Context
    revision_id: int
    build: EngineBuild
    d: float
    last_used: int


class Outcome(StrEnum):
    ALERT = "alert"
    BELOW_THRESHOLD = "below_threshold"
    SILENCED = "silenced"
    SNOOZED = "snoozed"
    HELD_BACK = "held_back"
    """By the once-an-hour rule."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A reminder judged in an evaluation, as the model saw it."""

    revision_id: int
    d: float
    from_cache: bool
    outcome: Outcome


@dataclass(frozen=True, slots=True)
class Evaluation:
    id: int
    at: int
    """When the decision came."""
    context: Context
    context_since: int
    threshold: float
    build: EngineBuild | None
    """None when there was nothing to judge, or the engine failed."""
    candidates: tuple[Candidate, ...]
    failed: bool = False
    """The engine failed: the evaluation holds no candidates, and it is not a "no alert"."""


class Answer(StrEnum):
    DONE = "fatto"
    USEFUL = "utile"
    SNOOZE = "rimanda"
    NOT_HERE = "non_qui"


@dataclass(frozen=True, slots=True)
class Alert:
    id: int
    reminder_id: int
    revision: Revision
    evaluation_id: int
    context: Context
    d: float
    created_at: int
    shown_at: int | None = None
    """When it appeared; None while it waits for a free place."""
    vanished_at: int | None = None
    """When it left the screen unanswered, after 10 s."""
    seen_at: int | None = None
    """When the tray list showed it, after it vanished."""
    answer: Answer | None = None
    answered_at: int | None = None


Record = Reminder | ReminderDeleted | Silence | SilencesCleared | CacheEntry | Evaluation | Alert


@dataclass(frozen=True, slots=True)
class LastIds:
    """The highest ids saved so far: new records continue after them."""

    reminder: int = 0
    revision: int = 0
    evaluation: int = 0
    alert: int = 0


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What `core` gets back from `store` when the app starts."""

    reminders: tuple[Reminder, ...] = ()
    silences: tuple[Silence, ...] = ()
    cache: tuple[CacheEntry, ...] = ()
    """The entries of the current revisions."""
    last_alerts: tuple[tuple[int, int], ...] = ()
    """For each reminder that has alerted, its id and when its last alert was made."""
    unseen: tuple[Alert, ...] = ()
    """Alerts shown and never answered, newest first."""
    last_ids: LastIds = LastIds()
