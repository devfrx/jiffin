"""The pieces of the interface that share one QML engine: the look, the glass, the overlay, the
creation window and its shortcut, the tray icon and its list."""

from collections.abc import Callable
from typing import Protocol

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock, SystemClock
from jiffin.core.reminders import RemindersView
from jiffin.ui.alert import Answers
from jiffin.ui.creation import Changes, Creation
from jiffin.ui.glass import Glass
from jiffin.ui.hotkey import Hotkey
from jiffin.ui.look import Look
from jiffin.ui.overlay import Overlay
from jiffin.ui.tray import Tray
from jiffin.ui.tray_list import Commands, TrayList


class Core(Answers, Changes, Commands, Protocol):
    """What the interface asks of `core.Reminders`, through the worker's queue."""


class Interface:
    """Make it on the interface thread, after the application and before any window. The
    `show_` methods take, on this thread, what `core`, the context capture and the engine say;
    `retry` starts the engine again."""

    def __init__(
        self,
        app: QGuiApplication,
        core: Core,
        retry: Callable[[], None],
        clock: Clock | None = None,
    ) -> None:
        # The app lives in the tray: hiding its last window must not end it.
        app.setQuitOnLastWindowClosed(False)
        # The glass shows only where the QML is transparent (ADR-0010).
        QQuickWindow.setDefaultAlphaBuffer(True)
        self.look = Look()
        self.look.follow(app)
        self.glass = Glass(self.look)
        app.installNativeEventFilter(self.glass)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.overlay = Overlay(self.engine, core, self.glass)
        self.creation = Creation(self.engine, core, self.glass)
        self.tray_list = TrayList(
            self.engine, core, self.creation, retry, self.glass, clock or SystemClock()
        )
        self.tray = Tray(self.engine, self.look, self.tray_list.toggle)
        self.tray.install()
        self.hotkey = Hotkey(self.creation.new)
        app.installNativeEventFilter(self.hotkey)
        self.hotkey.register()

    def show_alerts(self, view: AlertsView) -> None:
        self.overlay.show(view)
        self.tray_list.show_alerts(view)
        self.tray.show_alerts(view)

    def show_reminders(self, view: RemindersView) -> None:
        self.tray_list.show_reminders(view)

    def show_unreadable(self, apps: frozenset[str]) -> None:
        self.tray_list.show_unreadable(apps)
        self.tray.show_unreadable(apps)

    def show_engine(self, engine: TrayList.Engine) -> None:
        self.tray_list.show_engine(engine)
