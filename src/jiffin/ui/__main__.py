"""`python -m jiffin.ui`: made-up alerts on screen, to look at the interface without the app.

Answering an alert, or letting it vanish, prints what happened; a new alert comes 2 s later.
Win+Shift+N opens the creation window, and Salva prints the reminder. No model and no data are
needed. Ctrl+C in the terminal ends it.
"""

import argparse
import itertools
import os
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from jiffin.core.alerts import AlertsView
from jiffin.core.context import Context
from jiffin.core.records import Alert, Revision
from jiffin.core.reminders import Snooze
from jiffin.ui.interface import Interface
from jiffin.ui.look import Material

SAMPLES = (
    ("quando lavoro al progetto Rossi", "aggiornare il changelog prima del rilascio"),
    ("quando apro il gestionale delle fatture", "controllare la scadenza dell'F24"),
    ("quando scrivo una mail a Giulia", "allegare il preventivo firmato"),
)
NEXT_MS = 2000


class Preview:
    """Plays `core`'s part: the alerts on screen, a new one after each answer, and the reminders
    saved, printed."""

    def __init__(self, count: int) -> None:
        self._ids = itertools.count(1)
        self._texts = itertools.cycle(SAMPLES)
        self._visible = [self._alert() for _ in range(count)]
        self.interface: Interface | None = None

    def start(self, interface: Interface) -> None:
        self.interface = interface
        self._show()

    def done(self, alert_id: int) -> None:
        self._answered(alert_id, "Fatto")

    def useful(self, alert_id: int) -> None:
        self._answered(alert_id, "Utile")

    def not_here(self, alert_id: int) -> None:
        self._answered(alert_id, "Non qui")

    def snooze(self, alert_id: int, snooze: Snooze) -> None:
        self._answered(alert_id, f"Rimanda, {snooze.name.lower()}")

    def vanished(self, alert_id: int) -> None:
        self._answered(alert_id, "sparito dopo 10 s")

    def create(self, condition: str, action: str) -> None:
        print(f"nuovo promemoria: {condition!r}, {action!r}", flush=True)

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        print(f"promemoria {reminder_id} modificato: {condition!r}, {action!r}", flush=True)

    def _answered(self, alert_id: int, what: str) -> None:
        print(f"avviso {alert_id}: {what}", flush=True)
        self._visible = [alert for alert in self._visible if alert.id != alert_id]
        QTimer.singleShot(0, self._show)
        QTimer.singleShot(NEXT_MS, self._another)

    def _another(self) -> None:
        self._visible.append(self._alert())
        self._show()

    def _show(self) -> None:
        assert self.interface is not None
        self.interface.overlay.show(AlertsView(tuple(self._visible), 0, ()))

    def _alert(self) -> Alert:
        alert_id = next(self._ids)
        condition, action = next(self._texts)
        revision = Revision(alert_id, alert_id, 1, condition, action)
        context = Context("code.exe", "changelog.md - rossi", None)
        return Alert(alert_id, alert_id, revision, alert_id, context, 2.0, 0, shown_at=0)


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
    args = parser.parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # Qt's warnings, in the terminal: on Windows they go to the debugger when stderr is a pipe.
    os.environ.setdefault("QT_FORCE_STDERR_LOGGING", "1")
    app = QGuiApplication(sys.argv[:1])
    preview = Preview(args.alerts)
    interface = Interface(app, preview, preview)
    interface.look.material = Material(args.material)
    if not interface.hotkey.registered:
        print("Win+Maiusc+N è già usata da un'altra app", flush=True)
    preview.start(interface)
    if args.creation:
        interface.creation.new()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
