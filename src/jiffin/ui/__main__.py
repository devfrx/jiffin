"""`python -m jiffin.ui`: made-up alerts on screen and made-up reminders in the tray list, to look
at the interface without the app.

Answering an alert prints what happened, once its 5 s with Undo are over (ADR-0030), and a new
alert comes 2 s later; Done on a one-off one puts its reminder among the completed. An alert that
vanishes prints it and waits in the tray list, and no new one comes: alerts come no faster than
the user answers them, since a stream of them buries what is being looked at (#129, #151).
Win+Shift+N opens the creation window, the tray icon the list, and Settings in its menu the
settings; what they change is printed and kept until the end. In the list, Complete moves a
reminder among the completed, and their full circle brings it back. Win+Shift+Q, or the row at
the top of the list, opens the card of Remind here on a made-up place; a pick rings its reminder
at once, and the list shows what it learned there, which its X forgets. Pause in the same menu
shows the pause on the icon and in the list, until Resume. `--model` plays a first run: a
download of a minute and its check, or a problem first, which Retry mends. No model and no data
are needed. Quit in the tray icon's menu ends it, and prints an answer still waiting, which the
app would send then; Ctrl+C in the terminal ends it at once.
"""

import argparse
import itertools
import os
import signal
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import SystemClock
from jiffin.core.context import Context
from jiffin.core.meanings import read
from jiffin.core.records import Alert, Here, Outcome, Reminder, Revision, Snooze
from jiffin.core.reminders import (
    HOUR_MS,
    MINUTE_MS,
    ActiveReminder,
    HereReminder,
    HereView,
    Pause,
    Place,
    RemindersView,
    tomorrow,
)
from jiffin.ui import hotkey
from jiffin.ui.first_run import FirstRun, ModelFile, ModelState
from jiffin.ui.interface import Interface
from jiffin.ui.look import Material
from jiffin.ui.tray_list import TrayList

SAMPLES = (
    ("quando lavoro al progetto Rossi", "aggiornare il changelog prima del rilascio", False),
    ("quando apro Claude dopo le 23", "bere un bicchiere d'acqua", True),
    ("alle 15", "chiamare Giulia per il preventivo", False),
)
"""Condition, action and "Ogni volta" of the alerts: without a time, perennial with one, and with
only a time."""
REMINDERS = (
    ("quando lavoro al progetto Rossi", "aggiornare il changelog", False, 0, 12, 0),
    ("quando apro la posta", "rispondere a Giulia sul preventivo", False, 0, 0, 2),
    ("quando apro Claude dopo le 23", "bere un bicchiere d'acqua", True, 0, 0, 0),
    ("domani alle 15", "chiamare Giulia per il preventivo", False, 0, 0, 0),
    ("per tre giorni quando apro Teams", "scrivere il resoconto", False, 5, 0, 0),
    ("quando prenoto un viaggio", "controllare la scadenza del passaporto", False, 0, 0, 0),
)
"""Condition, action, "Ogni volta", days since it was written, minutes until the snooze ends, and
silences: without a time, perennial with one, with only a time, and with a period over."""
COMPLETED = (
    ("quando apro la posta", "mandare la fattura a Rossi", 20),
    ("quando apro il calendario", "prenotare il tagliando", 26 * 60),
    ("domani alle 9", "chiamare l'idraulico", 5 * 24 * 60),
)
"""Condition, action and minutes since it was completed: today, yesterday and days ago, the
last one with only a time."""
DAY_MS = 24 * HOUR_MS
NEXT_MS = 2000
BROWSERS = ("vivaldi.exe", "chrome.exe", "brave.exe")
HERE = Context("vivaldi.exe", "Preventivi", "mail.google.com/mail/u/0")
"""The made-up place of the card of Remind here."""
QUIET = (
    None,
    Outcome.SNOOZED,
    Outcome.SILENCED,
    Outcome.OUTSIDE_TIME,
    Outcome.SAME_OCCASION,
    Outcome.OUTSIDE_SITUATION,
)
"""What else kept each reminder quiet in that place, from the newest, in turn."""
_NAME = "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
MODEL = ModelFile(
    name=_NAME,
    url=f"https://huggingface.co/rizzoaiacademy/rizzo-flow/resolve/55633c8cbd2b826bd3eefdeb05310450996649df/{_NAME}",
    size=2_600_224_416,
    sha256="79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54",
    folder=Path(tempfile.gettempdir()) / "jiffin-preview" / "models",
)
"""The real pin's look, since the interface does not import `client` (ADR-0012), in a folder of
its own: Open folder never makes the app's."""
TICK_MS = 200
DOWNLOAD_TICKS = 300
"""A minute of download."""
CHECK_TICKS = 20
PROBLEMS = {
    "network": FirstRun.Stage.NETWORK,
    "space": FirstRun.Stage.SPACE,
    "disk": FirstRun.Stage.DISK,
    "mismatch": FirstRun.Stage.MISMATCH,
}


class Download:
    """Plays the model file's part: a download of a minute, then its check, then ready; or a
    problem first, which Retry mends."""

    def __init__(self, start: str) -> None:
        self._start = start
        self._done = MODEL.size * 31 // 100 if start in PROBLEMS else 0
        self._checked = 0
        self._timer = QTimer(interval=TICK_MS)
        self._timer.timeout.connect(self._tick)
        self.interface: Interface | None = None

    def begin(self, interface: Interface) -> None:
        self.interface = interface
        if self._start == "ready":
            self._show(FirstRun.Stage.READY)
        elif self._start in PROBLEMS:
            missing = 1_717_986_919 if self._start == "space" else 0
            self._show(PROBLEMS[self._start], missing)
        else:
            self._timer.start()

    def fetch(self) -> None:
        print("retry, on the model", flush=True)
        # A moment, as the real check of the network or the disk takes.
        QTimer.singleShot(1000, self._timer.start)

    def _tick(self) -> None:
        if self._done < MODEL.size:
            self._done = min(MODEL.size, self._done + MODEL.size // DOWNLOAD_TICKS)
            self._show(FirstRun.Stage.DOWNLOADING)
        elif self._checked < MODEL.size:
            self._checked = min(MODEL.size, self._checked + MODEL.size // CHECK_TICKS)
            self._show(FirstRun.Stage.CHECKING)
        else:
            self._timer.stop()
            self._show(FirstRun.Stage.READY)

    def _show(self, stage: FirstRun.Stage, missing: int = 0) -> None:
        assert self.interface is not None
        done = self._checked if stage is FirstRun.Stage.CHECKING else self._done
        self.interface.show_model(ModelState(stage, done, MODEL.size, missing))


class Preview:
    """Plays `core`'s part: the alerts on screen, a new one after each answer, those that
    vanished in the tray list, and the reminders, printed and kept in memory."""

    def __init__(
        self, count: int, download: "Download | None" = None, *, placed: bool = True
    ) -> None:
        self._download = download
        self._placed = placed
        """False: no place judged yet, for the card of Remind here."""
        self._clock = SystemClock()
        self._ids = itertools.count(1)
        self._texts = itertools.cycle(SAMPLES)
        self._visible = [self._alert() for _ in range(count)]
        self._unseen: list[Alert] = []
        self._reminders: dict[int, ActiveReminder] = {}
        now = self._clock.now()
        for condition, action, perennial, days, minutes, silences in reversed(REMINDERS):
            reminder_id = next(self._ids)
            written_at = now - days * DAY_MS
            reminder = Reminder(
                reminder_id,
                written_at,
                self._revision(reminder_id, condition, action, perennial, written_at),
                snoozed_until=now + minutes * MINUTE_MS if minutes else None,
            )
            mail = (Context("olk.exe", f"Posta {n} - Outlook", None) for n in range(silences))
            places = tuple(Place(context, Here.NO) for context in mail)
            self._reminders[reminder_id] = ActiveReminder(reminder, places)
        self._completed: dict[int, Reminder] = {}
        for condition, action, minutes in COMPLETED:
            reminder_id = next(self._ids)
            completed_at = now - minutes * MINUTE_MS
            written_at = completed_at - DAY_MS
            revision = self._revision(reminder_id, condition, action, False, written_at)
            self._completed[reminder_id] = Reminder(reminder_id, written_at, revision, completed_at)
        self._paused_until: int | None = None
        self.interface: Interface | None = None

    def start(self, interface: Interface) -> None:
        self.interface = interface
        self._show_alerts()
        self._show_reminders()

    def done(self, alert_id: int) -> None:
        alert = next((a for a in (*self._visible, *self._unseen) if a.id == alert_id), None)
        if alert is not None and not alert.revision.perennial:
            # Its reminder goes among the completed, as in `core` (ADR-0030).
            now = self._clock.now()
            reminder = Reminder(alert.reminder_id, alert.created_at, alert.revision, now)
            self._completed[reminder.id] = reminder
            QTimer.singleShot(0, self._show_reminders)
        self._answered(alert_id, "done")

    def not_here(self, alert_id: int) -> None:
        self._answered(alert_id, "not here")

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._answered(alert_id, f"snooze, {snooze.name.lower()}")

    def close(self, alert_id: int) -> None:
        self._answered(alert_id, "closed with the X")

    def vanished(self, alert_id: int) -> None:
        print(f"alert {alert_id}: vanished after 10 s", flush=True)
        now = self._clock.now()
        for alert in self._visible:
            if alert.id == alert_id:
                self._unseen.insert(0, replace(alert, vanished_at=now))
        self._visible = [alert for alert in self._visible if alert.id != alert_id]
        QTimer.singleShot(0, self._show_alerts)

    def seen(self) -> None:
        now = self._clock.now()
        self._unseen = [
            alert if alert.seen_at is not None else replace(alert, seen_at=now)
            for alert in self._unseen
        ]
        QTimer.singleShot(0, self._show_alerts)

    def create(self, condition: str, action: str, perennial: bool) -> None:
        every = ", perennial" if perennial else ""
        print(f"new reminder: {condition!r}, {action!r}{every}", flush=True)
        reminder_id = next(self._ids)
        revision = self._revision(reminder_id, condition, action, perennial)
        reminder = Reminder(reminder_id, self._clock.now(), revision)
        self._reminders[reminder_id] = ActiveReminder(reminder)
        QTimer.singleShot(0, self._show_reminders)

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None:
        every = ", perennial" if perennial else ""
        print(f"reminder {reminder_id} edited: {condition!r}, {action!r}{every}", flush=True)
        active = self._reminders.get(reminder_id)
        if active is not None:
            old = active.reminder.revision
            # The same condition keeps its time, as in `core` (ADR-0020).
            if condition == old.condition:
                revision = replace(old, action=action, perennial=perennial)
            else:
                revision = self._revision(reminder_id, condition, action, perennial)
            reminder = replace(active.reminder, revision=revision)
            self._reminders[reminder_id] = ActiveReminder(reminder)
        QTimer.singleShot(0, self._show_reminders)

    def complete(self, reminder_id: int) -> None:
        print(f"reminder {reminder_id} completed", flush=True)
        active = self._reminders.pop(reminder_id, None)
        if active is not None:
            now = self._clock.now()
            self._completed[reminder_id] = replace(active.reminder, completed_at=now)
        QTimer.singleShot(0, self._show_reminders)

    def reopen(self, reminder_id: int) -> None:
        print(f"reminder {reminder_id} reopened", flush=True)
        reminder = self._completed.pop(reminder_id, None)
        if reminder is not None:
            self._reminders[reminder_id] = ActiveReminder(replace(reminder, completed_at=None))
        QTimer.singleShot(0, self._show_reminders)

    def delete(self, reminder_id: int) -> None:
        print(f"reminder {reminder_id} deleted", flush=True)
        self._reminders.pop(reminder_id, None)
        self._completed.pop(reminder_id, None)
        QTimer.singleShot(0, self._show_reminders)

    def here(self) -> None:
        reminders = sorted(self._reminders.values(), key=lambda a: a.reminder.id, reverse=True)
        quiet = itertools.cycle(QUIET)
        view = (
            HereView(HERE, tuple(HereReminder(a.reminder, next(quiet)) for a in reminders))
            if self._placed
            else HereView(None)
        )
        QTimer.singleShot(0, lambda: self._show_here(view))

    def remind_here(self, reminder_id: int, context: Context) -> None:
        print(f"reminder {reminder_id}: remind here, in {context.title}", flush=True)
        active = self._reminders.get(reminder_id)
        if active is None:
            return
        self._say(active, context, Here.YES)
        now = self._clock.now()
        revision = active.reminder.revision
        alert_id = next(self._ids)
        self._visible.append(
            Alert(
                alert_id, reminder_id, revision, None, context, None, now, now, now, requested=True
            )
        )
        QTimer.singleShot(0, self._show_alerts)

    def withdraw(self, reminder_id: int, context: Context) -> None:
        print(f"reminder {reminder_id}: forgotten in {context.title}", flush=True)
        active = self._reminders.get(reminder_id)
        if active is not None:
            self._say(active, context, None)

    def withdraw_all(self, reminder_id: int) -> None:
        print(f"reminder {reminder_id}: everything forgotten", flush=True)
        active = self._reminders.get(reminder_id)
        if active is not None:
            self._reminders[reminder_id] = ActiveReminder(active.reminder)
            QTimer.singleShot(0, self._show_reminders)

    def restart_engine(self) -> None:
        print("retry, on the engine", flush=True)
        assert self.interface is not None
        self.interface.show_engine(TrayList.Engine.WORKING)

    def fetch_model(self) -> None:
        if self._download is not None:
            self._download.fetch()

    def keep_material(self, material: Material) -> None:
        print(f"material {material.value}", flush=True)

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        where = ", ".join(f"{name} {x},{y}" for name, (x, y) in places.items())
        print(f"places {where}", flush=True)

    def keep_return_pause(self, seconds: int) -> None:
        print(f"return pause {seconds} s", flush=True)

    def keep_networks(self, labels: Mapping[str, str]) -> None:
        print(f"network labels {sorted(labels.values()) or 'none'}", flush=True)

    def pause(self, pause: Pause) -> None:
        now = self._clock.now()
        self._paused_until = now + HOUR_MS if pause is Pause.HOUR else tomorrow(self._clock, now)
        print(f"paused until {self._clock.local(self._paused_until):%d/%m %H:%M}", flush=True)
        QTimer.singleShot(0, self._show_reminders)

    def resume(self) -> None:
        print("resume", flush=True)
        self._paused_until = None
        QTimer.singleShot(0, self._show_reminders)

    def _revision(
        self,
        reminder_id: int,
        condition: str,
        action: str,
        perennial: bool,
        written_at: int | None = None,
    ) -> Revision:
        """As `core` makes one: its time read when written, now unless said."""
        written_at = self._clock.now() if written_at is None else written_at
        reading = read(condition, self._clock.local(written_at))
        return Revision(
            reminder_id,
            reminder_id,
            1,
            condition,
            action,
            reading.remainder,
            schedule=reading.schedule,
            written_at=written_at,
            perennial=perennial,
        )

    def _say(self, active: ActiveReminder, context: Context, here: Here | None) -> None:
        """The answer in a place, the last answered first; None forgets it. Two Remind here
        make the reminder more attentive, as near the cut in `core`."""
        others = tuple(place for place in active.places if place.context != context)
        places = others if here is None else (Place(context, here), *others)
        attentive = sum(place.here is Here.YES for place in places) >= 2
        self._reminders[active.reminder.id] = ActiveReminder(active.reminder, places, attentive)
        QTimer.singleShot(0, self._show_reminders)

    def _answered(self, alert_id: int, what: str) -> None:
        print(f"alert {alert_id}: {what}", flush=True)
        self._visible = [alert for alert in self._visible if alert.id != alert_id]
        self._unseen = [alert for alert in self._unseen if alert.id != alert_id]
        QTimer.singleShot(0, self._show_alerts)
        QTimer.singleShot(NEXT_MS, self._another)

    def _another(self) -> None:
        self._visible.append(self._alert())
        self._show_alerts()

    def _show_alerts(self) -> None:
        assert self.interface is not None
        self.interface.show_alerts(AlertsView(tuple(self._visible), 0, tuple(self._unseen)))

    def _show_reminders(self) -> None:
        assert self.interface is not None
        newest_first = sorted(self._reminders.values(), key=lambda a: a.reminder.id, reverse=True)
        completed = sorted(
            self._completed.values(), key=lambda r: (r.completed_at, r.id), reverse=True
        )
        self.interface.show_reminders(
            RemindersView(tuple(newest_first), self._paused_until, tuple(completed))
        )

    def _show_here(self, view: HereView) -> None:
        assert self.interface is not None
        self.interface.show_here(view)

    def _alert(self) -> Alert:
        alert_id = next(self._ids)
        condition, action, perennial = next(self._texts)
        revision = self._revision(alert_id, condition, action, perennial)
        context = Context("code.exe", "changelog.md - rossi", None)
        now = self._clock.now()
        return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, now, now, shown_at=now)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m jiffin.ui", description=__doc__)
    parser.add_argument("--alerts", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--material",
        choices=[material.value for material in Material],
        default=Material.MENU_ACRYLIC.value,
        help="a: Acrylic, b: Acrylic with the menus' veil, c: Mica, d: Mica Alt",
    )
    parser.add_argument(
        "--creation", action="store_true", help="open the creation window at the start"
    )
    parser.add_argument(
        "--no-place",
        action="store_true",
        help="the card of Remind here with no place judged yet",
    )
    parser.add_argument(
        "--unreadable",
        nargs="+",
        choices=BROWSERS,
        default=(),
        help="browsers whose address cannot be read: the '!' and the banner",
    )
    parser.add_argument(
        "--model",
        choices=["ready", "download", *PROBLEMS],
        default="ready",
        help="a first run: the download, or a problem first; ready shows nothing",
    )
    parser.add_argument(
        "--engine",
        choices=[engine.name.lower() for engine in TrayList.Engine],
        default=TrayList.Engine.WORKING.name.lower(),
        help="what the tray list says of the engine; Riprova brings it back",
    )
    args = parser.parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # Qt's warnings, in the terminal: on Windows they go to the debugger when stderr is a pipe.
    os.environ.setdefault("QT_FORCE_STDERR_LOGGING", "1")
    app = QGuiApplication(sys.argv[:1])
    download = Download(args.model)
    preview = Preview(args.alerts, download, placed=not args.no_place)
    interface = Interface(app, preview, preview, MODEL)
    interface.look.material = Material(args.material)
    for key in (hotkey.NEW, hotkey.HERE):
        if key not in interface.hotkeys.registered:
            print(f"Win+Shift+{chr(key)} is taken by another app", flush=True)
    preview.start(interface)
    download.begin(interface)
    interface.show_unreadable(frozenset(args.unreadable))
    interface.show_engine(TrayList.Engine[args.engine.upper()])
    if args.creation:
        interface.creation.new()
    code = app.exec()
    interface.close()  # as in the app: an answer waiting with Undo is printed now
    sys.exit(code)


if __name__ == "__main__":
    main()
