from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone, tzinfo

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
    Left,
    Outcome,
    Record,
    Reminder,
    ReminderDeleted,
    Revision,
    Silence,
    SilencesCleared,
    Snapshot,
    Snooze,
)
from jiffin.core.reminders import (
    HOUR_MS,
    MINUTE_MS,
    RETURN_PAUSE_MS,
    THRESHOLD,
    ActiveReminder,
    Pause,
    Reminders,
    RemindersView,
    snooze_end,
    tomorrow,
)
from jiffin.core.schedule import OnDate, Schedule, Slot

START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", judge_prompt=1, rewrite_prompt=2)
FIGMA = Context("figma.exe", "Icone - Figma", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")
ROSSI = Context("code.exe", "changelog.md - rossi", None)
CLAUDE = Context("claude.exe", "Claude", None)
TEAMS = Context("ms-teams.exe", "Chat | Microsoft Teams", None)
OUTLOOK = Context("olk.exe", "Posta in arrivo - Outlook", None)
DAY_MS = 24 * HOUR_MS


def english(condition: str) -> str:
    return f"The user: {condition}."


def milliseconds(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def at(day: int, hour: int, minute: int = 0, second: int = 0) -> int:
    """A moment of October 2026 in UTC, the scenes' local time; the 2nd is a Friday."""
    return milliseconds(datetime(2026, 10, day, hour, minute, second, tzinfo=UTC))


class FakeModel:
    """Judges from a table: d is what the test says for a pair, and -6 otherwise."""

    def __init__(self) -> None:
        self.scores: dict[tuple[Context, str], float] = {}
        self.down = False
        self.calls: list[dict[int, str]] = []
        self.rewritten: list[str] = []

    def says(self, context: Context, remainder: str, d: float = 4.0) -> None:
        self.scores[(context, english(remainder))] = d

    def build(self) -> EngineBuild:
        self._answer()
        return BUILD

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        self._answer()
        self.calls.append(dict(statements))
        return {id: self.scores.get((context, text), -6.0) for id, text in statements.items()}

    def rewrite(self, condition: str) -> str:
        self._answer()
        self.rewritten.append(condition)
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
        return_pause: int = RETURN_PAUSE_MS,
        paused_until: int | None = None,
    ) -> None:
        self.model = model or FakeModel()
        self.clock = SimulatedClock(start, zone)
        self.views: list[AlertsView] = []
        self.lists: list[RemindersView] = []
        self.reminders = Reminders(
            self.model,
            self.clock,
            self.views.append,
            self.lists.append,
            saved,
            return_pause=return_pause,
            paused_until=paused_until,
        )
        self.records: list[Record] = []

    def create(
        self, condition: str, action: str = "esportare le icone", perennial: bool = False
    ) -> Reminder:
        return self.reminders.create(condition, action, perennial)

    def stay(self, context: Context | None, milliseconds: int = DEBOUNCE_MS) -> None:
        """Bring a context to the foreground and stay there."""
        self.reminders.observe(Observation(self.clock.now(), context))
        self.wait(milliseconds)

    def wait(self, milliseconds: int) -> None:
        self.clock.advance(milliseconds)
        self.reminders.poll()

    def until(self, moment: int) -> None:
        self.wait(moment - self.clock.now())

    @property
    def view(self) -> AlertsView:
        return self.views[-1] if self.views else AlertsView((), 0, ())

    @property
    def listed(self) -> tuple[ActiveReminder, ...]:
        """The active reminders in the tray list."""
        return self.lists[-1].active if self.lists else ()

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

    def rang(self) -> list[Alert]:
        """Every alert made so far, as first saved."""
        found: dict[int, Alert] = {}
        for alert in self.saved(Alert):
            found.setdefault(alert.id, alert)
        return list(found.values())


def figma(return_pause: int = RETURN_PAUSE_MS) -> Scene:
    """A scene with "quando apro Figma", true in Figma."""
    scene = Scene(return_pause=return_pause)
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    return scene


# Reminders and revisions


def test_a_new_reminder_gets_its_statement_from_the_engine() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    assert reminder.revision.statement == english("quando apro Figma")
    assert reminder.revision.statement_build == BUILD
    saved = scene.saved(Reminder)
    assert [r.revision.statement for r in saved] == [None, english("quando apro Figma")]


def test_the_time_of_a_new_reminder_is_read_when_it_is_saved() -> None:
    scene = Scene(start=at(2, 22))
    revision = scene.create("quando apro Claude dopo le 23", "chiudere il portatile").revision
    assert revision.remainder == "quando apro Claude"
    assert revision.schedule == Schedule(hours=Slot(time(23), time(4)))
    assert (revision.written_at, revision.created_at) == (at(2, 22), at(2, 22))
    assert not revision.perennial
    assert revision.statement == english("quando apro Claude")
    assert scene.create("quando apro Figma", perennial=True).revision.perennial


def test_a_reminder_with_only_a_time_never_reaches_the_engine() -> None:
    scene = Scene(start=at(2, 10))
    revision = scene.create("alle 15", "chiamare Mario").revision
    assert (revision.remainder, revision.statement) == ("", None)
    scene.stay(FIGMA)
    scene.reminders.model_ready()
    assert (scene.model.calls, scene.model.rewritten) == ([], [])
    assert [evaluation.candidates for evaluation in scene.saved(Evaluation)] == [(), ()]


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


def test_the_same_condition_keeps_its_time_and_statement() -> None:
    scene = Scene(start=at(2, 10))
    reminder = scene.create("domani quando apro Teams", "chiedere le ferie")
    scene.until(at(3, 18))
    scene.reminders.edit(reminder.id, "domani quando apro Teams", "chiedere i permessi")
    edited = scene.saved(Reminder)[-1].revision
    assert edited.schedule == Schedule(OnDate(date(2026, 10, 3)))
    assert (edited.written_at, edited.created_at) == (at(2, 10), at(3, 18))
    assert edited.statement == reminder.revision.statement
    assert scene.model.rewritten == ["quando apro Teams"]


def test_a_new_condition_is_read_again_from_now() -> None:
    scene = Scene(start=at(2, 10))
    reminder = scene.create("domani quando apro Teams", "chiedere le ferie")
    scene.until(at(3, 18))
    scene.reminders.edit(reminder.id, "domani quando apro Outlook", "chiedere le ferie")
    edited = scene.saved(Reminder)[-1].revision
    assert edited.schedule == Schedule(OnDate(date(2026, 10, 4)))
    assert (edited.remainder, edited.written_at) == ("quando apro Outlook", at(3, 18))
    assert edited.statement == english("quando apro Outlook")


def test_a_new_condition_with_the_same_remainder_keeps_the_statement() -> None:
    scene = Scene(start=at(2, 10))
    reminder = scene.create("quando apro Teams la mattina", "leggere la chat")
    scene.reminders.edit(reminder.id, "quando apro Teams la sera", "leggere la chat")
    edited = scene.saved(Reminder)[-1].revision
    assert edited.schedule == Schedule(hours=Slot(time(18), time(23)))
    assert edited.statement == reminder.revision.statement
    assert scene.model.rewritten == ["quando apro Teams"]


def test_a_new_text_is_not_true_until_it_is_judged() -> None:
    scene = figma()
    scene.stay(FIGMA)
    [active] = scene.listed
    scene.reminders.edit(active.reminder.id, "quando apro Figma", "esportare i loghi")
    scene.wait(10 * MINUTE_MS)
    scene.stay(BANK, MINUTE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_the_same_text_is_not_a_new_revision() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma", "esportare le icone")
    scene.saved(Reminder)
    scene.reminders.edit(reminder.id, "quando apro Figma", "esportare le icone")
    assert scene.reminders.take_records() == []


def test_ogni_volta_alone_is_a_new_revision_that_keeps_the_silences() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.not_here(scene.alert().id)
    [active] = scene.listed
    scene.reminders.edit(active.reminder.id, "quando apro Figma", "esportare le icone", True)
    edited = scene.saved(Reminder)[-1].revision
    assert (edited.number, edited.perennial) == (2, True)
    assert scene.saved(SilencesCleared) == []
    assert scene.listed[0].silences == 1


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
    scene.reminders.close(alert.id)
    scene.reminders.not_here(alert.id)
    scene.reminders.snooze(alert.id, Snooze.HOUR)
    scene.reminders.snooze(alert.id, Snooze.NEXT_TIME)
    scene.reminders.vanished(alert.id)
    scene.reminders.edit(reminder.id, "quando apro Photoshop", "esportare le icone")
    scene.reminders.complete(reminder.id)
    scene.reminders.delete(reminder.id)
    assert scene.reminders.take_records() == []
    assert scene.reminders.deadline is None


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
    assert evaluation.return_pause == RETURN_PAUSE_MS
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
    assert (alert.d, alert.due_at) == (4.0, START)


def test_the_threshold_is_reached_from_its_value_up() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.create("quando disegno icone")
    scene.model.says(FIGMA, "quando apro Figma", THRESHOLD)
    scene.model.says(FIGMA, "quando disegno icone", THRESHOLD - 0.01)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT, Outcome.BELOW_THRESHOLD]


def test_the_harness_may_judge_at_another_threshold() -> None:
    model, clock = FakeModel(), SimulatedClock(START)
    reminders = Reminders(model, clock, lambda view: None, lambda view: None, threshold=0.5)
    reminders.create("quando apro Figma", "esportare le icone")
    model.says(FIGMA, "quando apro Figma", 0.6)
    reminders.observe(Observation(clock.now(), FIGMA))
    clock.advance(DEBOUNCE_MS)
    reminders.poll()
    [evaluation] = [r for r in reminders.take_records() if isinstance(r, Evaluation)]
    assert evaluation.threshold == 0.5
    assert [candidate.outcome for candidate in evaluation.candidates] == [Outcome.ALERT]


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


def test_once_the_engine_is_back_the_stable_context_is_judged_again() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.model.down = True
    scene.stay(FIGMA)
    scene.model.down = False
    scene.reminders.model_ready()
    assert [evaluation.failed for evaluation in scene.saved(Evaluation)] == [True, False]
    assert scene.outcomes() == [Outcome.ALERT]
    assert scene.alert().reminder_id == reminder.id


def test_once_the_engine_is_back_the_statements_it_missed_are_written() -> None:
    scene = Scene()
    scene.model.down = True
    scene.create("quando apro Figma")
    scene.model.down = False
    scene.reminders.model_ready()
    assert scene.saved(Reminder)[-1].revision.statement == english("quando apro Figma")
    assert scene.saved(Evaluation) == []


def test_once_the_engine_is_back_what_it_judged_comes_from_the_cache() -> None:
    scene = Scene()
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.model_ready()
    assert len(scene.model.calls) == 1
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    assert len(scene.saved(Alert)) == 1


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


def test_a_stable_context_that_leaves_is_recorded_with_when_it_came_and_went() -> None:
    scene = Scene()
    scene.stay(FIGMA, MINUTE_MS)
    scene.stay(BANK, 1_000)  # a quick switch: never stable
    scene.stay(ROSSI)
    assert scene.saved(Left) == [Left(FIGMA, START, START + MINUTE_MS)]


# Occasions


def test_a_reminder_rings_once_per_occasion() -> None:
    scene = figma()
    scene.stay(FIGMA, 3 * HOUR_MS)
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK, RETURN_PAUSE_MS - 1)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]
    assert len(scene.rang()) == 2


def test_a_quick_switch_and_no_context_count_as_away() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.stay(BANK, 1_000)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    scene.stay(None, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_the_return_pause_is_the_settings() -> None:
    scene = figma(return_pause=10_000)
    scene.stay(FIGMA)
    scene.stay(BANK, 10_000)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]
    assert {evaluation.return_pause for evaluation in scene.saved(Evaluation)} == {10_000}


def test_not_here_on_a_wrong_context_does_not_end_the_occasion() -> None:
    scene = Scene()
    scene.create("quando scrivo a Rossi", "chiedere il preventivo")
    scene.model.says(TEAMS, "quando scrivo a Rossi")
    scene.model.says(OUTLOOK, "quando scrivo a Rossi")
    scene.stay(TEAMS)
    scene.reminders.not_here(scene.alert().id)
    scene.stay(OUTLOOK)
    assert scene.outcomes() == [Outcome.ALERT]
    scene.stay(TEAMS)
    assert scene.outcomes() == [Outcome.SILENCED]


def test_a_slot_that_opens_and_closes_with_the_context_in_front_starts_and_ends_a_stretch() -> None:
    scene = Scene(start=at(2, 22, 30))
    scene.create("quando apro Claude dopo le 23", "chiudere il portatile")
    scene.model.says(CLAUDE, "quando apro Claude")
    assert scene.reminders.deadline is None
    scene.stay(CLAUDE)
    assert scene.outcomes() == [Outcome.OUTSIDE_TIME]
    assert scene.reminders.deadline == at(2, 23)
    scene.until(at(2, 23))
    evaluation = scene.saved(Evaluation)[-1]
    assert (evaluation.at, evaluation.context_since) == (at(2, 23), at(2, 22, 30))
    assert scene.outcomes() == [Outcome.ALERT]
    assert scene.alert().due_at == at(2, 23)
    scene.reminders.vanished(scene.alert().id)
    scene.until(at(3, 4))
    assert scene.outcomes() == [Outcome.OUTSIDE_TIME]
    scene.until(at(3, 23))
    assert scene.outcomes() == [Outcome.ALERT]
    scene.stay(None, 1_000)
    assert scene.reminders.deadline is None


def test_staying_on_the_thing_while_the_next_day_starts_keeps_the_occasion() -> None:
    scene = Scene(start=at(6, 3, 50))  # Tuesday before 04:00: still Monday
    scene.create("quando apro Outlook nei giorni feriali", "leggere la posta")
    scene.model.says(OUTLOOK, "quando apro Outlook")
    scene.stay(OUTLOOK)
    assert scene.outcomes() == [Outcome.ALERT]
    scene.until(at(6, 4))
    assert scene.outcomes() == [Outcome.SAME_OCCASION]


def test_a_slot_with_an_app_rings_at_every_occasion_within_it() -> None:
    scene = Scene(start=at(2, 23))
    scene.create("quando apro Claude dopo le 23", "chiudere il portatile")
    scene.model.says(CLAUDE, "quando apro Claude")
    scene.stay(CLAUDE)
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(CLAUDE)
    assert len(scene.rang()) == 2


# Instances of a time


def test_a_reminder_with_only_a_time_rings_at_its_moment_in_any_stable_context() -> None:
    scene = Scene(start=at(2, 14, 50))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(FIGMA)
    assert scene.view.visible == ()
    assert scene.reminders.deadline == at(2, 15)
    scene.until(at(2, 15))
    alert = scene.alert()
    assert (alert.context, alert.evaluation_id, alert.d) == (FIGMA, None, None)
    assert (alert.created_at, alert.due_at) == (at(2, 15), at(2, 15))
    assert len(scene.saved(Evaluation)) == 1  # when Figma became stable


def test_a_moment_that_came_while_away_rings_when_the_user_is_back() -> None:
    scene = Scene(start=at(2, 14))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(None, 2 * HOUR_MS)
    assert scene.view.visible == ()
    assert scene.reminders.deadline is None
    scene.stay(FIGMA)
    assert (scene.alert().created_at, scene.alert().due_at) == (at(2, 16, 0, 5), at(2, 16))


def test_a_reminder_with_only_a_time_waits_for_a_context_stable_for_5_s() -> None:
    scene = Scene(start=at(2, 14, 59, 58))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(FIGMA)
    assert (scene.alert().created_at, scene.alert().due_at) == (at(2, 15, 0, 3), at(2, 15))


def test_a_one_off_moment_is_never_lost_and_comes_back_with_the_next_one() -> None:
    scene = Scene(start=at(2, 14))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(None, at(3, 10) - at(2, 14))
    scene.stay(FIGMA)
    late = scene.alert()
    assert late.due_at == at(3, 10)
    scene.reminders.vanished(late.id)
    scene.stay(BANK)
    assert scene.view.visible == ()
    scene.until(at(3, 15))
    assert (scene.alert().created_at, scene.alert().due_at) == (at(3, 15), at(3, 15))


def test_a_perennial_moment_may_ring_until_four() -> None:
    scene = Scene(start=at(2, 14))
    scene.create("alle 15", "prendere la pastiglia", perennial=True)
    scene.stay(None, at(3, 3) - at(2, 14))
    scene.stay(FIGMA)
    scene.reminders.done(scene.alert().id)
    assert scene.saved(Reminder)[-1].completed_at is None
    scene.stay(None, at(4, 4, 30) - scene.clock.now())
    scene.stay(FIGMA)
    assert scene.view.visible == ()
    assert len(scene.rang()) == 1


def test_a_one_off_date_rings_once_even_late() -> None:
    scene = Scene(start=at(2, 10))
    scene.create("domani alle 15", "chiamare Mario")
    scene.stay(None, at(4, 9) - at(2, 10))
    scene.stay(FIGMA)
    assert scene.alert().due_at == at(4, 9)
    scene.reminders.close(scene.alert().id)
    scene.stay(BANK, DAY_MS)
    scene.stay(FIGMA)
    assert len(scene.rang()) == 1


def test_a_perennial_date_rings_only_until_its_instance_ends() -> None:
    scene = Scene(start=at(2, 10))
    scene.create("domani alle 15", "chiamare Mario", perennial=True)
    scene.stay(None, at(4, 9) - at(2, 10))
    scene.stay(FIGMA)
    assert scene.rang() == []


def test_a_slot_without_an_app_rings_once_per_slot() -> None:
    scene = Scene(start=at(2, 17))
    scene.create("la sera", "annaffiare le piante")
    scene.stay(FIGMA)
    assert scene.view.visible == ()
    scene.until(at(2, 18))
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK, HOUR_MS)
    scene.stay(FIGMA)
    assert len(scene.rang()) == 1
    scene.stay(None, at(3, 18, 30) - scene.clock.now())
    scene.stay(FIGMA)
    assert len(scene.rang()) == 2


def test_a_frequency_rings_once_per_period_and_after_a_period_away_in_the_next() -> None:
    scene = Scene(start=at(2, 10))
    scene.create("ogni settimana", "fare il backup")
    scene.stay(FIGMA)
    scene.reminders.vanished(scene.alert().id)
    scene.stay(None, at(5, 10) - scene.clock.now())
    scene.stay(FIGMA)
    assert len(scene.rang()) == 1
    scene.stay(None, at(20, 10) - scene.clock.now())
    scene.stay(FIGMA)
    assert [alert.created_at for alert in scene.rang()] == [at(2, 10, 0, 5), at(20, 10, 0, 5)]


def test_an_ended_period_goes_silent() -> None:
    scene = Scene(start=at(2, 10))
    scene.create("quando apro Teams la sera fino a domenica", "segnare le ore")
    scene.model.says(TEAMS, "quando apro Teams")
    scene.stay(None, at(5, 19) - at(2, 10))
    scene.stay(TEAMS)
    assert scene.outcomes() == [Outcome.OUTSIDE_TIME]
    assert scene.reminders.deadline is None


def test_a_moment_with_an_app_rings_once_from_the_moment_on() -> None:
    scene = Scene(start=at(2, 22))
    scene.create("quando apro Claude alle 23", "chiudere il portatile")
    scene.model.says(CLAUDE, "quando apro Claude")
    scene.stay(CLAUDE)
    assert scene.outcomes() == [Outcome.OUTSIDE_TIME]
    scene.stay(BANK, 2 * HOUR_MS)
    scene.stay(CLAUDE)
    assert scene.outcomes() == [Outcome.ALERT]
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK, 10 * MINUTE_MS)
    scene.stay(CLAUDE)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]


def test_a_date_with_an_app_that_passed_without_ringing_rings_late_once() -> None:
    scene = Scene(start=at(2, 10))
    scene.create("domani quando apro Teams", "chiedere le ferie")
    scene.model.says(TEAMS, "quando apro Teams")
    scene.stay(TEAMS)
    assert scene.outcomes() == [Outcome.OUTSIDE_TIME]
    scene.stay(None, at(4, 10) - scene.clock.now())
    scene.stay(TEAMS)
    assert scene.outcomes() == [Outcome.ALERT]
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK, HOUR_MS)
    scene.stay(TEAMS)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]


def test_a_reminder_with_only_a_time_rings_while_the_engine_is_down() -> None:
    scene = Scene(start=at(2, 14, 50))
    scene.create("quando apro Figma")
    scene.create("alle 15", "chiamare Mario")
    scene.model.down = True
    scene.stay(FIGMA)
    scene.until(at(2, 15))
    assert scene.alert().revision.condition == "alle 15"
    assert [evaluation.failed for evaluation in scene.saved(Evaluation)] == [True]


# Answers


def test_done_completes_a_one_off_reminder() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.done(scene.alert().id)
    assert [a.answer for a in scene.saved(Alert) if a.answer] == [Answer.DONE]
    assert scene.saved(Reminder)[-1].completed_at == START + DEBOUNCE_MS
    assert scene.saved(Reminder)[-1].id == reminder.id


def test_done_on_a_perennial_reminder_waits_for_the_next_occasion() -> None:
    scene = Scene()
    scene.create("quando apro Figma", perennial=True)
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.done(scene.alert().id)
    assert [a.answer for a in scene.saved(Alert) if a.answer] == [Answer.DONE]
    assert [active.reminder.completed_at for active in scene.listed] == [None]
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_alla_prossima_volta_waits_for_the_next_occasion() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.NEXT_TIME)
    [answered] = [a for a in scene.saved(Alert) if a.answer]
    assert (answered.answer, answered.snooze) == (Answer.SNOOZE, Snooze.NEXT_TIME)
    assert scene.listed[0].reminder.snoozed_until is None
    assert scene.reminders.deadline is None
    scene.stay(FIGMA, 3 * HOUR_MS)
    assert len(scene.rang()) == 1
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


@pytest.mark.parametrize(
    ("snooze", "minutes"), [(Snooze.QUARTER_HOUR, 15), (Snooze.HOUR, 60)], ids=["15 min", "1 ora"]
)
def test_a_snoozed_alert_comes_back_when_the_snooze_ends_even_within_the_occasion(
    snooze: Snooze, minutes: int
) -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, snooze)
    end = scene.clock.now() + minutes * MINUTE_MS
    assert scene.saved(Reminder)[-1].snoozed_until == scene.reminders.deadline == end
    assert scene.saved(Alert)[-1].snooze is snooze
    scene.wait(minutes * MINUTE_MS - 1)
    assert scene.view.visible == ()
    scene.wait(1)
    assert (scene.alert().shown_at, scene.alert().due_at) == (end, end)
    scene.reminders.vanished(scene.alert().id)
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]


ROME_SUMMER = timezone(timedelta(hours=2))


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


def test_each_rimanda_ends_after_its_time_but_alla_prossima_volta() -> None:
    clock = SimulatedClock(START, UTC)
    assert [snooze_end(snooze, clock, START) for snooze in Snooze] == [
        None,
        START + 15 * MINUTE_MS,
        START + HOUR_MS,
        tomorrow(clock, START),
    ]


def test_a_snoozed_reminder_keeps_quiet_until_the_snooze_ends() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.HOUR)
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SNOOZED]


def test_a_snooze_that_ends_elsewhere_waits_for_a_true_context() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.QUARTER_HOUR)
    scene.stay(BANK, 20 * MINUTE_MS)
    assert scene.view.visible == ()
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]
    assert scene.alert().due_at == scene.saved(Evaluation)[-1].context_since


def test_alla_prossima_volta_on_an_older_alert_lifts_a_snooze() -> None:
    scene = figma()
    scene.stay(FIGMA)
    older = scene.alert()
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    [newer] = [alert for alert in scene.view.visible if alert.id != older.id]
    scene.reminders.snooze(newer.id, Snooze.HOUR)
    scene.reminders.snooze(older.id, Snooze.NEXT_TIME)
    assert scene.saved(Reminder)[-1].snoozed_until is None
    assert scene.reminders.deadline is None


def test_not_here_silences_the_reminder_in_that_exact_context() -> None:
    scene = Scene()
    reminder = scene.create("quando lavoro al progetto Rossi")
    report = Context("code.exe", "report.md - rossi", None)
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


def test_not_here_on_a_reminder_with_only_a_time_rings_it_elsewhere() -> None:
    scene = Scene(start=at(2, 14, 50))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(FIGMA)
    scene.until(at(2, 15))
    scene.reminders.not_here(scene.alert().id)
    scene.stay(BANK)
    assert (scene.alert().context, scene.alert().due_at) == (BANK, at(2, 15))
    scene.reminders.vanished(scene.alert().id)
    scene.stay(ROSSI)
    assert len(scene.rang()) == 2


def test_the_x_waits_for_the_next_occasion_and_is_not_unseen() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.close(scene.alert().id)
    assert [a.answer for a in scene.saved(Alert) if a.answer] == [Answer.CLOSED]
    assert (scene.view.visible, scene.view.unseen) == ((), ())
    scene.stay(BANK)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    assert scene.outcomes() == [Outcome.ALERT]


def test_a_fourth_alert_waits_for_a_place_on_screen() -> None:
    scene = Scene()
    for name in ("Figma", "le icone", "il logo", "la palette"):
        scene.create(f"quando apro {name}")
        scene.model.says(FIGMA, f"quando apro {name}")
    scene.stay(FIGMA)
    assert (len(scene.view.visible), scene.view.waiting, scene.view.dot) == (3, 1, True)
    scene.reminders.close(scene.view.visible[0].id)
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


def test_the_tray_list_keeps_one_unseen_alert_per_reminder() -> None:
    scene = figma()
    scene.stay(FIGMA)
    first = scene.alert()
    scene.reminders.vanished(first.id)
    scene.stay(BANK, RETURN_PAUSE_MS)
    scene.stay(FIGMA)
    second = scene.alert()
    assert not scene.view.unseen
    scene.reminders.vanished(second.id)
    assert [alert.id for alert in scene.view.unseen] == [second.id]


# The pause from the tray (ADR-0024)


def test_a_pause_holds_every_alert_until_it_ends_then_rings_as_after_being_away() -> None:
    scene = figma()
    scene.stay(BANK)
    end = scene.reminders.pause(Pause.HOUR)
    assert end == START + DEBOUNCE_MS + HOUR_MS
    assert scene.lists[-1].paused_until == end == scene.reminders.deadline
    assert scene.saved(Left)[-1] == Left(BANK, START, START + DEBOUNCE_MS)
    scene.stay(FIGMA, 10 * MINUTE_MS)
    scene.until(end + DEBOUNCE_MS - 1)
    assert scene.view.visible == ()
    assert len(scene.saved(Evaluation)) == 1  # Banca, before the pause
    assert scene.lists[-1].paused_until is None
    scene.wait(1)
    assert scene.outcomes() == [Outcome.ALERT]
    assert scene.saved(Evaluation)[-1].context_since == end
    assert scene.alert().created_at == end + DEBOUNCE_MS


def test_what_came_due_before_the_pause_is_handled_first() -> None:
    """The worker may take the pause before it polls: `core` still goes in order."""
    scene = figma()
    scene.reminders.observe(Observation(START, FIGMA))
    scene.clock.advance(DEBOUNCE_MS + 1)
    scene.reminders.pause(Pause.HOUR)
    assert scene.outcomes() == [Outcome.ALERT]
    assert scene.saved(Left)[-1] == Left(FIGMA, START, START + DEBOUNCE_MS + 1)


def test_riprendi_ends_the_pause_at_once() -> None:
    scene = figma()
    scene.reminders.pause(Pause.TOMORROW)
    scene.stay(FIGMA, HOUR_MS)
    assert scene.view.visible == ()
    scene.reminders.resume()
    assert scene.lists[-1].paused_until is None
    assert scene.reminders.deadline == scene.clock.now() + DEBOUNCE_MS
    scene.wait(DEBOUNCE_MS)
    assert scene.outcomes() == [Outcome.ALERT]
    views = len(scene.lists)
    scene.reminders.resume()
    assert len(scene.lists) == views


def test_a_pause_is_an_absence_for_the_occasions() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.vanished(scene.alert().id)
    scene.reminders.pause(Pause.HOUR)
    scene.wait(RETURN_PAUSE_MS - 1)
    scene.reminders.resume()
    scene.wait(DEBOUNCE_MS)
    assert scene.outcomes() == [Outcome.SAME_OCCASION]
    scene.reminders.pause(Pause.HOUR)
    scene.wait(RETURN_PAUSE_MS)
    scene.reminders.resume()
    scene.wait(DEBOUNCE_MS)
    assert scene.outcomes() == [Outcome.ALERT]


def test_a_moment_that_came_during_the_pause_rings_once_it_ends() -> None:
    """Due when the user is back, as after being away (ADR-0022)."""
    scene = Scene(start=at(2, 14, 30))
    scene.create("alle 15", "chiamare Mario")
    scene.stay(FIGMA)
    end = scene.reminders.pause(Pause.HOUR)
    scene.until(end + DEBOUNCE_MS - 1)
    assert scene.view.visible == ()
    scene.wait(1)
    assert (scene.alert().created_at, scene.alert().due_at) == (end + DEBOUNCE_MS, end)


def test_a_snooze_that_ends_during_the_pause_waits_for_its_end() -> None:
    scene = figma()
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.QUARTER_HOUR)
    end = scene.reminders.pause(Pause.HOUR)
    scene.until(end + DEBOUNCE_MS - 1)
    assert scene.view.visible == ()
    scene.wait(1)
    assert scene.alert().shown_at == end + DEBOUNCE_MS


@pytest.mark.parametrize(
    ("paused", "until"),
    [
        (
            datetime(2026, 9, 21, 14, 13, tzinfo=ROME_SUMMER),
            datetime(2026, 9, 22, 8, tzinfo=ROME_SUMMER),
        ),
        (
            datetime(2026, 9, 22, 1, 0, tzinfo=ROME_SUMMER),
            datetime(2026, 9, 22, 8, tzinfo=ROME_SUMMER),
        ),
    ],
    ids=["afternoon", "one in the night"],
)
def test_a_pause_until_tomorrow_ends_at_eight_of_the_next_jiffin_day(
    paused: datetime, until: datetime
) -> None:
    scene = Scene(start=milliseconds(paused), zone=ROME_SUMMER)
    assert scene.reminders.pause(Pause.TOMORROW) == milliseconds(until)


def test_a_pause_kept_in_the_settings_goes_on_after_a_restart() -> None:
    scene = Scene(paused_until=START + HOUR_MS)
    scene.wait(0)
    assert scene.lists == [RemindersView((), START + HOUR_MS)]
    assert scene.reminders.deadline == START + HOUR_MS
    scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.until(START + HOUR_MS + DEBOUNCE_MS - 1)
    assert scene.view.visible == ()
    scene.wait(1)
    assert scene.alert().created_at == START + HOUR_MS + DEBOUNCE_MS


# After a restart


def test_reminders_go_on_from_what_was_saved() -> None:
    revision = Revision(
        7,
        3,
        1,
        "quando apro Figma",
        "esportare le icone",
        "quando apro Figma",
        english("quando apro Figma"),
        BUILD,
    )
    before = START - HOUR_MS
    unseen = Alert(5, 3, revision, 4, FIGMA, 4.0, before, before, before, before + 10_000)
    saved = Snapshot(
        reminders=(Reminder(3, START - DAY_MS, revision),),
        silences=(Silence(3, BANK),),
        cache=(CacheEntry(FIGMA, 7, BUILD, 4.0, before),),
        last_alerts=((3, 5, before),),
        unseen=(unseen,),
        last_ids=LastIds(reminder=3, revision=7, evaluation=4, alert=5),
    )
    scene = Scene(saved=saved)
    scene.wait(0)
    assert scene.view.unseen == (unseen,)
    assert scene.listed == (ActiveReminder(Reminder(3, START - DAY_MS, revision), silences=1),)
    scene.stay(FIGMA)
    # Occasions start afresh: staying on the thing across a restart may give one alert more.
    assert (scene.model.calls, scene.outcomes()) == ([], [Outcome.ALERT])
    assert scene.saved(Evaluation)[-1].id == 5
    assert scene.alert().id == 6
    assert not scene.view.unseen  # the new alert took the old card's place
    scene.model.says(BANK, "quando apro Figma")
    scene.stay(BANK, HOUR_MS)
    assert scene.outcomes() == [Outcome.SILENCED]
    created = scene.create("se sono sul sito della banca")
    assert (created.id, created.revision.id) == (4, 8)


def a_call_at_three() -> tuple[Reminder, Alert]:
    """ "alle 15" written on Friday morning, and its alert at 15:00 in Figma, as saved."""
    scene = Scene(start=at(2, 10))
    reminder = scene.create("alle 15", "chiamare Mario")
    scene.stay(FIGMA, at(2, 15) - at(2, 10))
    alert = scene.alert()
    scene.reminders.vanished(alert.id)
    return reminder, scene.saved(Alert)[-1]


def test_after_a_restart_the_instances_of_a_time_stay_exact() -> None:
    reminder, alert = a_call_at_three()
    saved = Snapshot(
        reminders=(reminder,),
        last_alerts=((reminder.id, alert.id, alert.created_at),),
        unseen=(alert,),
        last_ids=LastIds(reminder=1, revision=1, evaluation=1, alert=1),
    )
    scene = Scene(start=at(2, 16), saved=saved)
    scene.stay(FIGMA)
    assert scene.view.visible == ()
    scene.reminders.not_here(alert.id)
    scene.stay(BANK)
    assert (scene.alert().id, scene.alert().context) == (2, BANK)


def test_a_saved_snooze_still_ends_on_time() -> None:
    snoozed = replace(Scene().create("quando apro Figma"), snoozed_until=START + HOUR_MS)
    scene = Scene(saved=Snapshot(reminders=(snoozed,)))
    assert scene.reminders.deadline == START + HOUR_MS


# The tray list


def test_the_tray_list_shows_the_active_reminders_newest_first() -> None:
    scene = Scene()
    figma = scene.create("quando apro Figma")
    bank = scene.create("se sono sul sito della banca", "pagare l'F24")
    assert [active.reminder for active in scene.listed] == [bank, figma]
    scene.reminders.edit(figma.id, "quando apro Figma", "esportare i loghi")
    assert scene.listed[1].reminder.revision.action == "esportare i loghi"
    scene.reminders.complete(bank.id)
    assert [active.reminder.id for active in scene.listed] == [figma.id]
    scene.reminders.delete(figma.id)
    assert scene.listed == ()


def test_the_tray_list_shows_a_snooze_and_the_silences() -> None:
    scene = Scene()
    reminder = scene.create("quando apro Figma")
    scene.model.says(FIGMA, "quando apro Figma")
    scene.stay(FIGMA)
    scene.reminders.snooze(scene.alert().id, Snooze.QUARTER_HOUR)
    [active] = scene.listed
    assert (active.reminder.snoozed_until, active.silences) == (
        scene.clock.now() + 15 * MINUTE_MS,
        0,
    )
    scene.wait(15 * MINUTE_MS)
    scene.reminders.not_here(scene.alert().id)
    assert scene.listed[0].silences == 1
    scene.reminders.edit(reminder.id, "quando apro Figma", "esportare i loghi")
    assert scene.listed[0].silences == 0
