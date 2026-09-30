from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.model import EngineBuild, ModelError
from jiffin.core.records import (
    Alert,
    Answer,
    CacheEntry,
    Evaluation,
    LastIds,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    SilencesCleared,
    Snapshot,
)
from jiffin.core.reminders import HOUR_MS, MINUTE_MS, THRESHOLD, Reminders, Snooze

START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", judge_prompt=1, rewrite_prompt=2)
FIGMA = Context("figma", "Icone - Figma", None)
BANK = Context("vivaldi", "Banca Rossi", "bancarossi.it")
ROSSI = Context("code", "changelog.md - rossi", None)


def english(condition: str) -> str:
    return f"The user: {condition}."


class FakeModel:
    """Judges from a table: d is what the test says for a pair, and -6 otherwise."""

    def __init__(self) -> None:
        self.scores: dict[tuple[Context, str], float] = {}
        self.down = False
        self.calls: list[dict[int, str]] = []

    def says(self, context: Context, condition: str, d: float = 4.0) -> None:
        self.scores[(context, english(condition))] = d

    def build(self) -> EngineBuild:
        self._answer()
        return BUILD

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        self._answer()
        self.calls.append(dict(statements))
        return {id: self.scores.get((context, text), -6.0) for id, text in statements.items()}

    def rewrite(self, condition: str) -> str:
        self._answer()
        return english(condition)

    def _answer(self) -> None:
        if self.down:
            raise ModelError("the engine is down")


class Scene:
    """One `Reminders` with the clock, the model and the interface around it."""

    def __init__(
        self,
        model: FakeModel | None = None,
        start: int = START,
        zone: tzinfo = UTC,
        saved: Snapshot | None = None,
    ) -> None:
        self.model = model or FakeModel()
        self.clock = SimulatedClock(start, zone)
        self.views: list[AlertsView] = []
        self.reminders = Reminders(self.model, self.clock, self.views.append, saved)
        self.records: list[Record] = []

    def create(self, condition: str, action: str = "esportare le icone") -> Reminder:
        return self.reminders.create(condition, action)

    def stay(self, context: Context | None, milliseconds: int = DEBOUNCE_MS) -> None:
        """Bring a context to the foreground and stay there."""
        self.reminders.observe(Observation(self.clock.now(), context))
        self.wait(milliseconds)

    def wait(self, milliseconds: int) -> None:
        self.clock.advance(milliseconds)
        self.reminders.poll()

    @property
    def view(self) -> AlertsView:
        return self.views[-1] if self.views else AlertsView((), 0, ())

    def saved[T](self, kind: type[T]) -> list[T]:
        self.records += self.reminders.take_records()
        return [record for record in self.records if isinstance(record, kind)]

    def outcomes(self) -> list[Outcome]:
        """The outcomes of the last evaluation."""
        return [candidate.outcome for candidate in self.saved(Evaluation)[-1].candidates]

    def alert(self) -> Alert:
        """The one alert on screen."""
        [alert] = self.view.visible
        return alert


# Reminders and revisions


def test_a_new_reminder_gets_its_statement_from_the_engine() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    assert reminder.revision.statement == english("quando apro Figma")
    assert reminder.revision.statement_build == BUILD
    saved = scene.saved(Reminder)
    assert [r.revision.statement for r in saved] == [None, english("quando apro Figma")]


def test_a_reminder_without_a_statement_is_judged_once_the_engine_writes_it() -> None:
    scene = Scene()
    scene.model.down = True
    reminder = scene.create("quando apro Figma")
    assert reminder.revision.statement is None
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    assert scene.outcomes() == []
    scene.model.down = False
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.alert().reminder_id == reminder.id


def test_a_new_text_is_a_new_revision_without_silences() -> None:
    scene = Scene()
    reminder = scene.create("quando lavoro al progetto Rossi")
    scene.model.says(ROSSI, "quando lavoro al progetto Rossi")
    scene.stay(ROSSI)
    scene.reminders.not_here(scene.alert().id)
    scene.reminders.edit(reminder.id, "quando lavoro al progetto Rossi", "aggiornare la versione")
    assert scene.saved(SilencesCleared) == [SilencesCleared(reminder.id)]
    edited = scene.saved(Reminder)[-1].revision
    assert (edited.number, edited.action) == (2, "aggiornare la versione")
    assert edited.statement == english("quando lavoro al progetto Rossi")
    scene.stay(BANK, HOUR_MS)
    scene.stay(ROSSI)
    assert scene.model.calls[-1] == {edited.id: edited.statement}
    assert scene.outcomes() == [Outcome.ALERT]


def test_the_same_text_is_not_a_new_revision() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma", "esportare le icone")
    scene.saved(Reminder)
    scene.reminders.edit(reminder.id, "quando apro Figma", "esportare le icone")
    assert scene.reminders.take_records() == []


def test_a_completed_reminder_is_no_longer_judged_and_its_alerts_go() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.complete(reminder.id)
    assert scene.view.visible == ()
    assert scene.saved(Reminder)[-1].completed_at == START + DEBOUNCE_MS
    scene.stay(BANK, HOUR_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == []


def test_commands_about_what_is_gone_do_nothing() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    alert = scene.alert()
    scene.reminders.delete(reminder.id)
    assert scene.saved(ReminderDeleted) == [ReminderDeleted(reminder.id)]
    assert scene.view.visible == ()
    scene.reminders.done(alert.id)
    scene.reminders.useful(alert.id)
    scene.reminders.not_here(alert.id)
    scene.reminders.snooze(alert.id, Snooze.HOUR)
    scene.reminders.vanished(alert.id)
    scene.reminders.edit(reminder.id, "quando apro Photoshop", "esportare le icone")
    scene.reminders.complete(reminder.id)
    scene.reminders.delete(reminder.id)
    assert scene.reminders.take_records() == []
    assert scene.reminders.deadline is None


def test_reminders_go_on_from_what_was_saved() -> None:
    revision = Revision(
        7, 3, 1, "quando apro Figma", "esportare le icone", english("quando apro Figma"), BUILD
    )
    unseen = Alert(5, 3, revision, 4, FIGMA, 4.0, START, START, START + 10_000)
    saved = Snapshot(
        reminders=(Reminder(3, START, revision),),
        silences=(Silence(3, BANK),),
        cache=(CacheEntry(FIGMA, 7, BUILD, 4.0, START),),
        last_alerts=((3, START),),
        unseen=(unseen,),
        last_ids=LastIds(reminder=3, revision=7, evaluation=4, alert=5),
    )
    scene = Scene(saved=saved)
    scene.wait(0)
    assert scene.view.unseen == (unseen,)
    scene.stay(FIGMA)
    assert (scene.model.calls, scene.outcomes()) == ([], [Outcome.HELD_BACK])
    assert scene.saved(Evaluation)[-1].id == 5
    scene.model.says(BANK, "quando apro Figma")
    scene.stay(BANK, HOUR_MS)
    assert scene.outcomes() == [Outcome.SILENCED]
    created = scene.create("se sono sul sito della banca")
    assert (created.id, created.revision.id) == (4, 8)


def test_a_saved_snooze_still_ends_on_time() -> None:
    snoozed = replace(Scene().create("quando apro Figma"), snoozed_until=START + HOUR_MS)
    scene = Scene(saved=Snapshot(reminders=(snoozed,)))
    assert scene.reminders.deadline == START + HOUR_MS


# Judging


def test_a_stable_context_judges_every_active_reminder_in_one_call() -> None:
    scene = Scene()
    figma = scene.create("quando apro Figma")
    scene.create("se sono sul sito della banca")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    assert [len(call) for call in scene.model.calls] == [2]
    [evaluation] = scene.saved(Evaluation)
    assert (evaluation.context, evaluation.context_since) == (FIGMA, START)
    assert (evaluation.at, evaluation.threshold, evaluation.build) == (
        START + DEBOUNCE_MS,
        THRESHOLD,
        BUILD,
    )
    assert [(c.outcome, c.from_cache) for c in evaluation.candidates] == [
        (Outcome.ALERT, False),
        (Outcome.BELOW_THRESHOLD, False),
    ]
    alert = scene.alert()
    assert (alert.reminder_id, alert.context, alert.evaluation_id) == (
        figma.id,
        FIGMA,
        evaluation.id,
    )


def test_the_threshold_is_reached_from_its_value_up() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.create("quando disegno icone")
    scene.model.says(FIGMA, "quando apro Figma", THRESHOLD)
    scene.model.says(FIGMA, "quando disegno icone", THRESHOLD - 0.01)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT, Outcome.BELOW_THRESHOLD]


def test_pairs_already_judged_come_from_the_cache() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.stay(FIGMA)
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert len(scene.model.calls) == 2
    last = scene.saved(Evaluation)[-1]
    assert [c.from_cache for c in last.candidates] == [True]
    assert scene.saved(CacheEntry)[-1].last_used == last.at


def test_an_engine_failure_is_an_error_and_not_a_silence() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.model.down = True
    scene.stay(FIGMA)
    [evaluation] = scene.saved(Evaluation)
    assert evaluation.failed
    assert evaluation.candidates == ()
    assert scene.view.visible == ()


def test_a_model_that_leaves_a_statement_out_fails() -> None:
    class Forgetful(FakeModel):
        def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
            return {}

    scene = Scene(Forgetful())
    scene.create("quando apro Figma")
    scene.stay(FIGMA)
    assert scene.saved(Evaluation)[0].failed


def test_an_evaluation_is_saved_before_its_alerts() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    kinds = [type(record) for record in scene.reminders.take_records()]
    assert kinds.index(Evaluation) < kinds.index(Alert)


# Alert rules


def test_an_alert_repeats_at_most_once_an_hour() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.HELD_BACK]
    scene.stay(BANK, HOUR_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_staying_in_a_true_context_does_not_repeat_the_alert() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA, 3 * HOUR_MS)
    assert len(scene.saved(Alert)) == 1


@pytest.mark.parametrize(
    ("snooze", "minutes"), [(Snooze.QUARTER_HOUR, 15), (Snooze.HOUR, 60)], ids=["15 min", "1 ora"]
)
def test_a_snoozed_alert_comes_back_when_the_snooze_ends_in_a_true_context(
    snooze: Snooze, minutes: int
) -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, snooze)
    end = scene.clock.now() + minutes * MINUTE_MS
    assert scene.saved(Reminder)[-1].snoozed_until == scene.reminders.deadline == end
    scene.wait(minutes * MINUTE_MS - 1)
    assert scene.view.visible == ()
    scene.wait(1)
    assert scene.alert().shown_at == end
    assert scene.saved(Reminder)[-1].snoozed_until is None


ROME_SUMMER = timezone(timedelta(hours=2))


def milliseconds(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


@pytest.mark.parametrize(
    ("zone", "snoozed", "back"),
    [
        (UTC, datetime(2026, 9, 21, 14, 13, tzinfo=UTC), datetime(2026, 9, 22, 8, tzinfo=UTC)),
        (UTC, datetime(2026, 9, 22, 2, 10, tzinfo=UTC), datetime(2026, 9, 22, 8, tzinfo=UTC)),
        (UTC, datetime(2026, 9, 22, 4, 0, tzinfo=UTC), datetime(2026, 9, 23, 8, tzinfo=UTC)),
        (
            ROME_SUMMER,
            datetime(2026, 9, 21, 23, 30, tzinfo=ROME_SUMMER),
            datetime(2026, 9, 22, 8, tzinfo=ROME_SUMMER),
        ),
    ],
    ids=["afternoon", "late night", "four in the morning", "local time"],
)
def test_tomorrow_is_the_next_morning_at_eight(
    zone: tzinfo, snoozed: datetime, back: datetime
) -> None:
    scene = Scene(start=milliseconds(snoozed) - DEBOUNCE_MS, zone=zone)
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.TOMORROW)
    assert scene.reminders.deadline == milliseconds(back)


def test_a_snoozed_reminder_keeps_quiet_until_the_snooze_ends() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.HOUR)
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SNOOZED]


def test_a_snooze_that_ends_elsewhere_waits_for_a_true_context() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.QUARTER_HOUR)
    scene.stay(BANK, 20 * MINUTE_MS)
    assert scene.view.visible == ()
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_not_here_silences_the_reminder_in_that_exact_context() -> None:
    scene = Scene()
    reminder = scene.create("quando lavoro al progetto Rossi")
    report = Context("code", "report.md - rossi", None)
    scene.model.says(ROSSI, "quando lavoro al progetto Rossi")
    scene.model.says(report, "quando lavoro al progetto Rossi")
    scene.stay(ROSSI)
    scene.reminders.not_here(scene.alert().id)
    assert scene.saved(Silence) == [Silence(reminder.id, ROSSI)]
    scene.stay(BANK, HOUR_MS)
    scene.stay(ROSSI)
    assert scene.outcomes() == [Outcome.SILENCED]
    scene.stay(report)
    assert scene.outcomes() == [Outcome.ALERT]


def test_done_completes_the_reminder() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.done(scene.alert().id)
    assert [a.answer for a in scene.saved(Alert) if a.answer] == [Answer.DONE]
    assert scene.saved(Reminder)[-1] == Reminder(
        reminder.id, START, reminder.revision, completed_at=START + DEBOUNCE_MS
    )


def test_useful_keeps_the_reminder_active() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.useful(scene.alert().id)
    assert [a.answer for a in scene.saved(Alert) if a.answer] == [Answer.USEFUL]
    scene.stay(BANK, HOUR_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_a_fourth_alert_waits_for_a_place_on_screen() -> None:
    scene = Scene()
    for name in ("Figma", "le icone", "il logo", "la palette"):
        scene.create(f"quando apro {name}")
        scene.model.says(FIGMA, f"quando apro {name}")
    scene.stay(FIGMA)
    assert (len(scene.view.visible), scene.view.waiting, scene.view.dot) == (3, 1, True)
    scene.reminders.useful(scene.view.visible[0].id)
    assert (len(scene.view.visible), scene.view.waiting) == (3, 0)


def test_an_unanswered_alert_waits_on_top_of_the_tray_list() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    alert = scene.alert()
    scene.wait(10_000)
    scene.reminders.vanished(alert.id)
    assert (scene.view.visible, [a.id for a in scene.view.unseen]) == ((), [alert.id])
    assert scene.view.dot
    assert scene.saved(Alert)[-1].vanished_at == scene.clock.now()
    scene.wait(60_000)
    scene.reminders.seen()
    assert scene.saved(Alert)[-1].seen_at == scene.clock.now()
    assert not scene.view.dot
    scene.reminders.done(alert.id)
    assert scene.view.unseen == ()
    assert scene.saved(Reminder)[-1].completed_at == scene.clock.now()
    assert scene.saved(Reminder)[-1].id == reminder.id
