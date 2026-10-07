"""What `core` knows, as plain data: the records that `store` keeps (ADR-0013, ADR-0014, ADR-0021);
and the engine's sleeps, which the client records and `core` never sees (ADR-0027)."""

from dataclasses import dataclass
from enum import StrEnum

from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.schedule import Schedule
from jiffin.core.situations import SituationStretch, Term


@dataclass(frozen=True, slots=True)
class Revision:
    """A version of a reminder's text. The statement comes later, from the engine."""

    id: int
    reminder_id: int
    number: int
    condition: str
    """The "Quando" box, in Italian: "quando apro Figma dopo le 23"."""
    action: str
    """The "Ricordami di" box: "esportare le icone"."""
    remainder: str
    """The condition without the words of its time and of its situations, which the engine
    rewrites (ADR-0020, ADR-0028): the whole condition when it has neither; empty for a reminder
    with only a time or situations, never judged."""
    statement: str | None = None
    """The remainder as one English statement, once the engine has written it (ADR-0008)."""
    statement_build: EngineBuild | None = None
    schedule: Schedule | None = None
    """The time of the condition in real dates; None without a time, or with one not understood."""
    written_at: int | None = None
    """When the condition was written: its time counts from then, and a new revision that keeps
    the condition keeps it (ADR-0020). None in version 0.1, whose reminders have no time."""
    perennial: bool = False
    """ "Ogni volta": Done means "done this time", and the reminder waits for its next unit."""
    created_at: int | None = None
    """When the revision was made; unknown for the later revisions of version 0.1."""
    situations: tuple[Term, ...] = ()
    """The situations of the condition (ADR-0028): none without, or when they are not
    understood. `store` keeps them from migration 0003 (#150)."""


@dataclass(frozen=True, slots=True)
class Reminder:
    """A reminder with its current revision. Saving it saves the revision too."""

    id: int
    created_at: int
    revision: Revision
    completed_at: int | None = None
    snoozed_until: int | None = None
    """Set by a Snooze with a time. Once past, the reminder may ring again within its unit, until
    it rings (ADR-0021)."""


@dataclass(frozen=True, slots=True)
class ReminderDeleted:
    """The reminder is gone, and everything about it with it (ADR-0014)."""

    reminder_id: int


@dataclass(frozen=True, slots=True)
class Silence:
    """Not here, as `store` keeps it until migration 0003 (#150): the reminder keeps quiet in
    this context until its text changes."""

    reminder_id: int
    context: Context


class Here(StrEnum):
    """What the user said of a reminder in one place, an exact context (ADR-0029): the last one
    counts, until the reminder's text changes."""

    NO = "not_here"
    """Not here: the reminder keeps quiet in this context."""
    YES = "remind_here"
    """Remind here, "qui dovevi avvisarmi": the reminder counts as true in this context, also
    under its threshold."""
    WITHDRAWN = "withdrawn"
    """What was said there is taken back: from the tray list, or by a change of text."""


@dataclass(frozen=True, slots=True)
class ContextAnswer:
    """An answer per place, or its withdrawal (ADR-0029), for the table `context_answer` of
    migration 0003 (#150)."""

    reminder_id: int
    context: Context
    here: Here
    d: float | None
    """The reminder's d in the context when it was said, from the cache; None when unknown."""
    build: EngineBuild | None
    """The engine build of that d: a threshold learns only from the build in use."""
    at: int


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """The d of a revision in a context, from one engine build (ADR-0004)."""

    context: Context
    revision_id: int
    build: EngineBuild
    d: float
    last_used: int


class Outcome(StrEnum):
    """What a judgement gave a reminder; they are checked in the order of ADR-0021."""

    ALERT = "alert"
    BELOW_THRESHOLD = "below_threshold"
    OUTSIDE_TIME = "outside_time"
    """True in the context, but out of its time."""
    OUTSIDE_SITUATION = "outside_situation"
    """True in the context and within its time, but its situation does not hold: absent, an end
    not come yet, a duration not reached (ADR-0028)."""
    SILENCED = "silenced"
    SNOOZED = "snoozed"
    SAME_OCCASION = "same_occasion"
    """It has rung already in its unit: the occasion, or the instance of its time."""
    HELD_BACK = "held_back"
    """By the once-an-hour rule of version 0.1: only in its rows."""


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
    return_pause: int | None = None
    """The return pause it was judged with, in milliseconds; None in version 0.1."""


@dataclass(frozen=True, slots=True)
class Left:
    """A stable context left the foreground: `store` writes when on its evaluations, so that the
    harness can replay the occasions (ADR-0021)."""

    context: Context
    since: int
    """When it came to the foreground: the `context_since` of its evaluations."""
    until: int


class Answer(StrEnum):
    DONE = "fatto"
    USEFUL = "utile"
    """Version 0.1 only: Next time took its place."""
    SNOOZE = "rimanda"
    NOT_HERE = "non_qui"
    CLOSED = "chiuso"
    """The X: the alert was seen, and gives no label (ADR-0014)."""


class Snooze(StrEnum):
    """Which Snooze (ADR-0021)."""

    NEXT_TIME = "next_time"
    """Next time: the reminder waits for its next unit."""
    QUARTER_HOUR = "quarter_hour"
    HOUR = "hour"
    TOMORROW = "tomorrow"


@dataclass(frozen=True, slots=True)
class Alert:
    id: int
    reminder_id: int
    revision: Revision
    evaluation_id: int | None
    """None for a reminder with only a time, which is never judged."""
    context: Context
    d: float | None
    """None for a reminder with only a time."""
    created_at: int
    due_at: int
    """Since when it was due: the arrival of its context, the start of its time or the end of its
    snooze, whichever came last (ADR-0022). In version 0.1, the arrival of its context."""
    shown_at: int | None = None
    """When it appeared; None while it waits for a free place."""
    vanished_at: int | None = None
    """When it left the screen unanswered, after 10 s."""
    seen_at: int | None = None
    """When the tray list showed it, after it vanished."""
    answer: Answer | None = None
    answered_at: int | None = None
    snooze: Snooze | None = None
    """Which Snooze, with the answer `rimanda`; unknown in version 0.1."""
    requested: bool = False
    """Asked for with Remind here (ADR-0029): it counts in its unit, and is never the judge's.
    `store` keeps it from migration 0003 (#150)."""


Record = (
    Reminder
    | ReminderDeleted
    | ContextAnswer
    | CacheEntry
    | Evaluation
    | Left
    | SituationStretch
    | Alert
)


class SleepReason(StrEnum):
    """Why the engine fell asleep (ADR-0027)."""

    IDLE = "idle"
    """5 minutes after `core` last asked it for a judgement or a statement."""
    NOTHING_IN_FRONT = "nothing_in_front"
    """Nothing is in front for the reminders: no context, or the pause from the tray."""


class Waker(StrEnum):
    """What woke the engine (ADR-0027, ADR-0031)."""

    CONTEXT = "context"
    """A context waits for its 5 s with judgements not in the cache: the wake `core` announced."""
    STATEMENT = "statement"
    """A statement to write, asked while it slept."""
    JUDGEMENT = "judgement"
    """A judgement asked while it slept, which no waiting context had announced."""
    RETRY = "retry"
    """Retry, on the GPU's memory."""


@dataclass(frozen=True, slots=True)
class EngineSleep:
    """A light sleep of the engine (ADR-0027). It is recorded when the engine falls asleep, then
    again, with the same `slept_at`, when the sleep ends."""

    slept_at: int
    reason: SleepReason
    woken_at: int | None = None
    """When the wake started, or when the engine was found failed; None while it sleeps."""
    woken_by: Waker | None = None
    """None while it sleeps, and when the engine failed asleep."""
    ready_at: int | None = None
    """When the model was ready again, its warm-up done; None while it sleeps, and when the sleep
    ended without a model: the wake failed, or the engine failed asleep."""


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
    last_alerts: tuple[tuple[int, int, int], ...] = ()
    """For each reminder that has rung, its id, then the id and the time of its last alert not
    answered Not here: the one that counts in its unit (ADR-0021)."""
    unseen: tuple[Alert, ...] = ()
    """Alerts shown and never answered, the last of their reminder, newest first."""
    last_ids: LastIds = LastIds()
