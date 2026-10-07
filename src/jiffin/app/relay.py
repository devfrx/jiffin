"""What the worker, the context capture and the model file's thread say to the interface: Qt
signals emitted on their threads, connected to the slots of an object on the interface thread,
where Qt runs them (ADR-0012)."""

from PySide6.QtCore import QObject, Signal, Slot

from jiffin.client.supervisor import State, Status, StopReason
from jiffin.core.alerts import AlertsView
from jiffin.core.reminders import RemindersView
from jiffin.ui.first_run import ModelState
from jiffin.ui.interface import Interface
from jiffin.ui.tray_list import TrayList

_STOPPED = {
    StopReason.FAILURES: TrayList.Engine.FAILURES,
    StopReason.MODEL: TrayList.Engine.MODEL,
    StopReason.GPU_MEMORY: TrayList.Engine.GPU_MEMORY,
    StopReason.MISMATCH: TrayList.Engine.MISMATCH,
}


def engine_line(status: Status) -> TrayList.Engine:
    """What the tray list says of the engine: working, unless it is down (#43), or asleep after
    a wake the GPU's memory refused (ADR-0027). Asleep, it is ready to the user."""
    match status:
        case Status(State.RESTARTING):
            return TrayList.Engine.RESTARTING
        case Status(State.STOPPED, reason) if reason is not None:
            return _STOPPED[reason]
        case Status(State.ASLEEP, StopReason.GPU_MEMORY):
            return TrayList.Engine.GPU_MEMORY
        case _:
            return TrayList.Engine.WORKING


class Relay(QObject):
    """Make it on the interface thread, and deliver it to the interface before the other threads
    start: a signal emitted before reaches no one."""

    alerts = Signal(object)
    reminders = Signal(object)
    unreadable = Signal(object)
    engine = Signal(object)
    """The supervisor's `Status`."""
    model = Signal(object)

    _interface: Interface

    def deliver(self, interface: Interface) -> None:
        self._interface = interface
        self.alerts.connect(self._show_alerts)
        self.reminders.connect(self._show_reminders)
        self.unreadable.connect(self._show_unreadable)
        self.engine.connect(self._show_engine)
        self.model.connect(self._show_model)

    @Slot(object)
    def _show_alerts(self, view: AlertsView) -> None:
        self._interface.show_alerts(view)

    @Slot(object)
    def _show_reminders(self, view: RemindersView) -> None:
        self._interface.show_reminders(view)

    @Slot(object)
    def _show_unreadable(self, apps: frozenset[str]) -> None:
        self._interface.show_unreadable(apps)

    @Slot(object)
    def _show_engine(self, status: Status) -> None:
        self._interface.show_engine(engine_line(status))

    @Slot(object)
    def _show_model(self, state: ModelState) -> None:
        self._interface.show_model(state)
