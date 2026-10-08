import threading
from typing import cast

import pytest
from pytestqt.qtbot import QtBot

from jiffin.app.relay import Relay, engine_line
from jiffin.client.supervisor import State, Status, StopReason
from jiffin.core.alerts import AlertsView
from jiffin.core.reminders import HereView, RemindersView
from jiffin.ui.first_run import FirstRun, ModelState
from jiffin.ui.interface import Interface
from jiffin.ui.tray_list import TrayList


class Shown:
    """The interface's `show_` methods: what each got, and on which thread."""

    def __init__(self) -> None:
        self.got: list[tuple[str, object, str]] = []

    def show_alerts(self, view: AlertsView) -> None:
        self._got("alerts", view)

    def show_reminders(self, view: RemindersView) -> None:
        self._got("reminders", view)

    def show_here(self, view: HereView) -> None:
        self._got("here", view)

    def show_unreadable(self, apps: frozenset[str]) -> None:
        self._got("unreadable", apps)

    def show_engine(self, engine: TrayList.Engine) -> None:
        self._got("engine", engine)

    def show_model(self, state: ModelState) -> None:
        self._got("model", state)

    def _got(self, what: str, value: object) -> None:
        self.got.append((what, value, threading.current_thread().name))


def test_what_other_threads_say_reaches_the_interface_on_its_thread(qtbot: QtBot) -> None:
    shown = Shown()
    relay = Relay()
    relay.deliver(cast(Interface, shown))
    alerts, reminders, here = AlertsView((), 0, ()), RemindersView(()), HereView(None)
    model = ModelState(FirstRun.Stage.CHECKING, 1, 2)

    def speak() -> None:
        relay.alerts.emit(alerts)
        relay.reminders.emit(reminders)
        relay.here.emit(here)
        relay.unreadable.emit(frozenset({"chrome.exe"}))
        relay.engine.emit(Status(State.RESTARTING))
        relay.model.emit(model)

    thread = threading.Thread(target=speak, name="worker")
    thread.start()
    thread.join()
    qtbot.waitUntil(lambda: len(shown.got) == 6)
    main = threading.main_thread().name
    assert shown.got == [
        ("alerts", alerts, main),
        ("reminders", reminders, main),
        ("here", here, main),
        ("unreadable", frozenset({"chrome.exe"}), main),
        ("engine", TrayList.Engine.RESTARTING, main),
        ("model", model, main),
    ]


@pytest.mark.parametrize(
    ("status", "line"),
    [
        (Status(State.OFF), TrayList.Engine.WORKING),
        (Status(State.STARTING), TrayList.Engine.WORKING),
        (Status(State.READY), TrayList.Engine.WORKING),
        (Status(State.ASLEEP), TrayList.Engine.WORKING),
        (Status(State.ASLEEP, StopReason.GPU_MEMORY), TrayList.Engine.GPU_MEMORY),
        (Status(State.RESTARTING), TrayList.Engine.RESTARTING),
        (Status(State.STOPPED, StopReason.FAILURES), TrayList.Engine.FAILURES),
        (Status(State.STOPPED, StopReason.MODEL), TrayList.Engine.MODEL),
        (Status(State.STOPPED, StopReason.GPU_MEMORY), TrayList.Engine.GPU_MEMORY),
        (Status(State.STOPPED, StopReason.MISMATCH), TrayList.Engine.MISMATCH),
    ],
)
def test_the_tray_list_says_what_the_supervisor_says(status: Status, line: TrayList.Engine) -> None:
    assert engine_line(status) == line
