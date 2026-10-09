"""The pieces of the interface that share one QML engine: the look, the glass, the windows'
places, the overlay, the card of Remind here, the creation window, their shortcuts, the tray icon
and its list, the settings window and the first-run window."""

from collections.abc import Mapping
from typing import Protocol

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import AlertsView
from jiffin.core.clock import Clock, SystemClock
from jiffin.core.reminders import HereView, Pause, RemindersView
from jiffin.ui import hotkey
from jiffin.ui.alert import Answers
from jiffin.ui.creation import Changes, Creation
from jiffin.ui.first_run import FirstRun, ModelFile, ModelState
from jiffin.ui.glass import Glass
from jiffin.ui.hotkey import Hotkeys
from jiffin.ui.look import Look, Material
from jiffin.ui.overlay import Overlay
from jiffin.ui.places import Places
from jiffin.ui.preferences import Preferences
from jiffin.ui.remind_here import RemindHere, Requests
from jiffin.ui.tray import Tray
from jiffin.ui.tray_list import Commands, TrayList


class Core(Answers, Changes, Commands, Requests, Protocol):
    """What the interface asks of `core.Reminders`, through the worker's queue."""


class Upkeep(Protocol):
    """What the interface asks of the app around `core`: each named, since a swap of two of them
    would go unnoticed."""

    def restart_engine(self) -> None:
        """Retry, on the engine's trouble in the tray list."""
        ...

    def fetch_model(self) -> None:
        """Retry, on a problem with the model file: `model_file.ensure` again."""
        ...

    def keep_material(self, material: Material) -> None:
        """The material the user chose, to set on `look.material` at the next start."""
        ...

    def keep_return_pause(self, seconds: int) -> None:
        """The return pause the user chose: in force at once, and set on
        `preferences.return_pause` at the next start (ADR-0021)."""
        ...

    def keep_places(self, places: Mapping[str, tuple[int, int]]) -> None:
        """Where the user left the windows, by name, to give `places.restore` at the next
        start."""
        ...

    def pause(self, pause: Pause) -> None:
        """Pause, in the tray icon's menu: in force at once, and kept through a restart until
        it ends (ADR-0024)."""
        ...

    def resume(self) -> None:
        """Resume, in the tray icon's menu or on the pause's line in its list."""
        ...


class Interface:
    """Make it on the interface thread, after the application and before any window, and set
    the kept material on `look.material`, the kept places on `places` and the kept return pause
    on `preferences.return_pause` before anything shows.
    The `show_` methods take, on this thread, what `core`, the context capture, the engine and the
    model file say. `close` once Qt has quit."""

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
        self.overlay = Overlay(self.engine, core, self.glass, clock)
        self.remind_here = RemindHere(self.engine, core, self.overlay, self.glass, clock)
        self.creation = Creation(self.engine, core, self.glass, self.places, clock)
        self.first_run = FirstRun(
            self.engine, model, upkeep.fetch_model, self.glass, self.places, clock
        )
        self.preferences = Preferences(
            self.engine,
            self.look,
            upkeep.keep_material,
            upkeep.keep_return_pause,
            self.glass,
            self.places,
        )
        self.tray_list = TrayList(
            self.engine,
            core,
            self.creation,
            self.remind_here,
            upkeep.restart_engine,
            upkeep.resume,
            self.first_run,
            self.preferences,
            self.glass,
            clock,
        )
        self.tray = Tray(
            self.engine,
            self.look,
            self.tray_list.toggle,
            self.preferences.open,
            upkeep.pause,
            upkeep.resume,
        )
        self.tray.install()
        # If another app holds Win+Shift+Q, the tray list's row still opens the card.
        self.hotkeys = Hotkeys({hotkey.NEW: self.creation.new, hotkey.HERE: self.remind_here.open})
        app.installNativeEventFilter(self.hotkeys)
        self.hotkeys.register()
        self.first_run.shortcut = hotkey.NEW in self.hotkeys.registered

    def close(self) -> None:
        """The answers still waiting with Undo, on the alerts and in the tray list, go to `core`
        at once (ADR-0030), before the worker stops; the shortcuts go back to Windows."""
        self.overlay.close()
        self.tray_list.close()
        self.hotkeys.close()

    def show_alerts(self, view: AlertsView) -> None:
        self.overlay.show(view)
        self.tray_list.show_alerts(view)
        self.tray.show_alerts(view)

    def show_reminders(self, view: RemindersView) -> None:
        self.tray_list.show_reminders(view)
        self.tray.show_reminders(view)

    def show_here(self, view: HereView) -> None:
        """`core`'s answer to the card of Remind here, or to the tray list's row."""
        self.remind_here.show(view)

    def show_unreadable(self, apps: frozenset[str]) -> None:
        self.tray_list.show_unreadable(apps)
        self.tray.show_unreadable(apps)

    def show_engine(self, engine: TrayList.Engine) -> None:
        self.tray_list.show_engine(engine)

    def show_model(self, state: ModelState) -> None:
        """At every start, before the engine starts: the check, a download, a problem, then
        ready. A download or a problem opens the first-run window."""
        self.first_run.show(state)
