"""The pieces of the interface that share one QML engine: the look, the glass, the windows'
places, the overlay, the creation window and its shortcut, the tray icon and its list, the
settings window and the first-run window."""

from collections.abc import Mapping
from typing import Protocol

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock, SystemClock
from jiffin.core.reminders import RemindersView
from jiffin.ui.alert import Answers
from jiffin.ui.creation import Changes, Creation
from jiffin.ui.first_run import FirstRun, ModelFile, ModelState
from jiffin.ui.glass import Glass
from jiffin.ui.hotkey import Hotkey
from jiffin.ui.look import Look, Material
from jiffin.ui.overlay import Overlay
from jiffin.ui.places import Places
from jiffin.ui.preferences import Preferences
from jiffin.ui.tray import Tray
from jiffin.ui.tray_list import Commands, TrayList


class Core(Answers, Changes, Commands, Protocol):
    """What the interface asks of `core.Reminders`, through the worker's queue."""


class Upkeep(Protocol):
    """What the interface asks of the app around `core`: each named, since a swap of two of them
    would go unnoticed."""

    def restart_engine(self) -> None:
        """Riprova, on the engine's trouble in the tray list."""
        ...

    def fetch_model(self) -> None:
        """Riprova, on a problem with the model file: `model_file.ensure` again."""
        ...

    def keep_material(self, material: Material) -> None:
        """The material the user chose, to set on `look.material` at the next start."""
        ...

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        """Where the user left the windows, by name, to give `places.restore` at the next
        start."""
        ...


class Interface:
    """Make it on the interface thread, after the application and before any window, and set
    the kept material on `look.material` and the kept places on `places` before anything shows.
    The `show_` methods take, on this thread, what `core`, the context capture, the engine and the
    model file say."""

    def __init__(
        self,
        app: QGuiApplication,
        core: Core,
        upkeep: Upkeep,
        model: ModelFile,
        clock: Clock | None = None,
    ) -> None:
        clock = clock or SystemClock()
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
        self.places = Places(upkeep.keep_places)
        self.overlay = Overlay(self.engine, core, self.glass)
        self.creation = Creation(self.engine, core, self.glass, self.places, clock)
        self.first_run = FirstRun(
            self.engine, model, upkeep.fetch_model, self.glass, self.places, clock
        )
        self.tray_list = TrayList(
            self.engine,
            core,
            self.creation,
            upkeep.restart_engine,
            self.first_run,
            self.glass,
            clock,
        )
        self.preferences = Preferences(
            self.engine, self.look, upkeep.keep_material, self.glass, self.places
        )
        self.tray = Tray(self.engine, self.look, self.tray_list.toggle, self.preferences.open)
        self.tray.install()
        self.hotkey = Hotkey(self.creation.new)
        app.installNativeEventFilter(self.hotkey)
        self.hotkey.register()
        self.first_run.shortcut = self.hotkey.registered

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

    def show_model(self, state: ModelState) -> None:
        """At every start, before the engine starts: the check, a download, a problem, then
        ready. A download or a problem opens the first-run window."""
        self.first_run.show(state)
