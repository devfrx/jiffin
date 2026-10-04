"""`python -m jiffin.ui`: made-up alerts on screen and made-up reminders in the tray list, to look
at the interface without the app.

Answering an alert, or letting it vanish, prints what happened; a new alert comes 2 s later,
and one that vanished waits in the tray list. Win+Shift+N opens the creation window, the tray
icon the list, and Impostazioni in its menu the settings; what they change is printed and kept
until the end. `--model` plays a first run: a download of a minute and its check, or a problem
first, which Riprova mends. No model and no data are needed. Esci in the tray icon's menu, or
Ctrl+C in the terminal, ends it.
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
from jiffin.core.records import Alert, Reminder, Revision, Snooze
from jiffin.core.reminders import MINUTE_MS, ActiveReminder, RemindersView
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
    ("quando lavoro al progetto Rossi", "aggiornare il changelog prima del rilascio", 12, 0),
    ("quando apro la posta", "rispondere a Giulia sul preventivo", 0, 2),
    ("quando prenoto un viaggio", "controllare la scadenza del passaporto", 0, 0),
)
"""Condition, action, minutes until the snooze ends, and silences."""
NEXT_MS = 2000
BROWSERS = ("vivaldi.exe", "chrome.exe", "brave.exe")
_NAME = "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
MODEL = ModelFile(
    name=_NAME,
    url=f"https://huggingface.co/rizzoaiacademy/rizzo-flow/resolve/55633c8cbd2b826bd3eefdeb05310450996649df/{_NAME}",
    size=2_600_224_416,
    sha256="79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54",
    folder=Path(tempfile.gettempdir()) / "jiffin-preview" / "models",
)
"""The real pin's look, since the interface does not import `client` (ADR-0012), in a folder of
its own: Apri la cartella never makes the app's."""
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
    problem first, which Riprova mends."""

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
        print("Riprova, sul modello", flush=True)
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

    def __init__(self, count: int, download: "Download | None" = None) -> None:
        self._download = download
        self._clock = SystemClock()
        self._ids = itertools.count(1)
        self._texts = itertools.cycle(SAMPLES)
        self._visible = [self._alert() for _ in range(count)]
        self._unseen: list[Alert] = []
        self._reminders: dict[int, ActiveReminder] = {}
        now = self._clock.now()
        for condition, action, minutes, silences in reversed(REMINDERS):
            reminder_id = next(self._ids)
            reminder = Reminder(
                reminder_id,
                now,
                Revision(reminder_id, reminder_id, 1, condition, action, condition),
                snoozed_until=now + minutes * MINUTE_MS if minutes else None,
            )
            self._reminders[reminder_id] = ActiveReminder(reminder, silences)
        self.interface: Interface | None = None

    def start(self, interface: Interface) -> None:
        self.interface = interface
        self._show_alerts()
        self._show_reminders()

    def done(self, alert_id: int) -> None:
        self._answered(alert_id, "Fatto")

    def not_here(self, alert_id: int) -> None:
        self._answered(alert_id, "Non qui")

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._answered(alert_id, f"Rimanda, {snooze.name.lower()}")

    def close(self, alert_id: int) -> None:
        self._answered(alert_id, "chiuso con la X")

    def vanished(self, alert_id: int) -> None:
        print(f"avviso {alert_id}: sparito dopo 10 s", flush=True)
        now = self._clock.now()
        for alert in self._visible:
            if alert.id == alert_id:
                self._unseen.insert(0, replace(alert, vanished_at=now))
        self._visible = [alert for alert in self._visible if alert.id != alert_id]
        QTimer.singleShot(0, self._show_alerts)
        QTimer.singleShot(NEXT_MS, self._another)

    def seen(self) -> None:
        now = self._clock.now()
        self._unseen = [
            alert if alert.seen_at is not None else replace(alert, seen_at=now)
            for alert in self._unseen
        ]
        QTimer.singleShot(0, self._show_alerts)

    def create(self, condition: str, action: str, perennial: bool) -> None:
        every = ", ogni volta" if perennial else ""
        print(f"nuovo promemoria: {condition!r}, {action!r}{every}", flush=True)
        reminder_id = next(self._ids)
        revision = self._revision(reminder_id, condition, action, perennial)
        reminder = Reminder(reminder_id, self._clock.now(), revision)
        self._reminders[reminder_id] = ActiveReminder(reminder, 0)
        QTimer.singleShot(0, self._show_reminders)

    def edit(self, reminder_id: int, condition: str, action: str, perennial: bool) -> None:
        every = ", ogni volta" if perennial else ""
        print(f"promemoria {reminder_id} modificato: {condition!r}, {action!r}{every}", flush=True)
        active = self._reminders.get(reminder_id)
        if active is not None:
            old = active.reminder.revision
            # The same condition keeps its time, as in `core` (ADR-0020).
            if condition == old.condition:
                revision = replace(old, action=action, perennial=perennial)
            else:
                revision = self._revision(reminder_id, condition, action, perennial)
            reminder = replace(active.reminder, revision=revision)
            self._reminders[reminder_id] = ActiveReminder(reminder, 0)
        QTimer.singleShot(0, self._show_reminders)

    def complete(self, reminder_id: int) -> None:
        print(f"promemoria {reminder_id} completato", flush=True)
        self._reminders.pop(reminder_id, None)
        QTimer.singleShot(0, self._show_reminders)

    def delete(self, reminder_id: int) -> None:
        print(f"promemoria {reminder_id} eliminato", flush=True)
        self._reminders.pop(reminder_id, None)
        QTimer.singleShot(0, self._show_reminders)

    def restart_engine(self) -> None:
        print("Riprova", flush=True)
        assert self.interface is not None
        self.interface.show_engine(TrayList.Engine.WORKING)

    def fetch_model(self) -> None:
        if self._download is not None:
            self._download.fetch()

    def keep_material(self, material: Material) -> None:
        print(f"materiale {material.value}", flush=True)

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        where = ", ".join(f"{name} {x},{y}" for name, (x, y) in places.items())
        print(f"posizioni {where}", flush=True)

    def _revision(self, reminder_id: int, condition: str, action: str, perennial: bool) -> Revision:
        """As `core` makes one: its time read now."""
        now = self._clock.now()
        reading = read(condition, self._clock.local(now))
        return Revision(
            reminder_id,
            reminder_id,
            1,
            condition,
            action,
            reading.remainder,
            schedule=reading.schedule,
            written_at=now,
            perennial=perennial,
        )

    def _answered(self, alert_id: int, what: str) -> None:
        print(f"avviso {alert_id}: {what}", flush=True)
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
        self.interface.show_reminders(RemindersView(tuple(newest_first)))

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
    preview = Preview(args.alerts, download)
    interface = Interface(app, preview, preview, MODEL)
    interface.look.material = Material(args.material)
    if not interface.hotkey.registered:
        print("Win+Maiusc+N è già usata da un'altra app", flush=True)
    preview.start(interface)
    download.begin(interface)
    interface.show_unreadable(frozenset(args.unreadable))
    interface.show_engine(TrayList.Engine[args.engine.upper()])
    if args.creation:
        interface.creation.new()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
