"""`python -m jiffin.ui`: made-up alerts on screen and made-up reminders in the tray list, to look
at the interface without the app.

Answering an alert, or letting it vanish, prints what happened; a new alert comes 2 s later,
and one that vanished waits in the tray list. Win+Shift+N opens the creation window, and the
tray icon the list; what they change is printed and kept until the end. No model and no data
are needed. Esci in the tray icon's menu, or Ctrl+C in the terminal, ends it.
"""

import argparse
import itertools
import os
import signal
import sys
from dataclasses import replace

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import SystemClock
from jiffin.core.context import Context
from jiffin.core.records import Alert, Reminder, Revision
from jiffin.core.reminders import MINUTE_MS, ActiveReminder, RemindersView, Snooze
from jiffin.ui.interface import Interface
from jiffin.ui.look import Material
from jiffin.ui.tray_list import TrayList

SAMPLES = (
    ("quando lavoro al progetto Rossi", "aggiornare il changelog prima del rilascio"),
    ("quando apro il gestionale delle fatture", "controllare la scadenza dell'F24"),
    ("quando scrivo una mail a Giulia", "allegare il preventivo firmato"),
)
REMINDERS = (
    ("quando lavoro al progetto Rossi", "aggiornare il changelog prima del rilascio", 12, 0),
    ("quando apro la posta", "rispondere a Giulia sul preventivo", 0, 2),
    ("quando prenoto un viaggio", "controllare la scadenza del passaporto", 0, 0),
)
"""Condition, action, minutes until the snooze ends, and silences."""
NEXT_MS = 2000
BROWSERS = ("vivaldi.exe", "chrome.exe", "brave.exe")


class Preview:
    """Plays `core`'s part: the alerts on screen, a new one after each answer, those that
    vanished in the tray list, and the reminders, printed and kept in memory."""

    def __init__(self, count: int) -> None:
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
                Revision(reminder_id, reminder_id, 1, condition, action),
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

    def useful(self, alert_id: int) -> None:
        self._answered(alert_id, "Utile")

    def not_here(self, alert_id: int) -> None:
        self._answered(alert_id, "Non qui")

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._answered(alert_id, f"Rimanda, {snooze.name.lower()}")

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

    def create(self, condition: str, action: str) -> None:
        print(f"nuovo promemoria: {condition!r}, {action!r}", flush=True)
        reminder_id = next(self._ids)
        revision = Revision(reminder_id, reminder_id, 1, condition, action)
        reminder = Reminder(reminder_id, self._clock.now(), revision)
        self._reminders[reminder_id] = ActiveReminder(reminder, 0)
        QTimer.singleShot(0, self._show_reminders)

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        print(f"promemoria {reminder_id} modificato: {condition!r}, {action!r}", flush=True)
        active = self._reminders.get(reminder_id)
        if active is not None:
            revision = replace(active.reminder.revision, condition=condition, action=action)
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

    def retry(self) -> None:
        print("Riprova", flush=True)
        assert self.interface is not None
        self.interface.show_engine(TrayList.Engine.WORKING)

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
        condition, action = next(self._texts)
        revision = Revision(alert_id, alert_id, 1, condition, action)
        context = Context("code.exe", "changelog.md - rossi", None)
        now = self._clock.now()
        return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, now, shown_at=now)


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
    preview = Preview(args.alerts)
    interface = Interface(app, preview, preview.retry)
    interface.look.material = Material(args.material)
    if not interface.hotkey.registered:
        print("Win+Maiusc+N è già usata da un'altra app", flush=True)
    preview.start(interface)
    interface.show_unreadable(frozenset(args.unreadable))
    interface.show_engine(TrayList.Engine[args.engine.upper()])
    if args.creation:
        interface.creation.new()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
