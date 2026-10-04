"""The alerts on screen: up to three windows at the top centre of the screen (#12, ADR-0010),
each with Rimanda's menu, a window of its own (#83).

`core` says which alerts are on screen; the overlay gives each one a window, stacked from the
top in the order they came, and the others move up once one has left. An alert answered here
never comes back, even if a view from before the answer arrives after its window has left.

Alerts and menus come uninvited, so they are kept out of screen capture while they show
(ADR-0024). A menu never takes the focus, and hears of no click elsewhere: while one is open the
mouse buttons are read, and a press outside it and its alert closes it.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import MAX_VISIBLE, AlertsView
from jiffin.core.clock import Clock
from jiffin.ui import win32
from jiffin.ui.alert import AlertSlot, Answers
from jiffin.ui.glass import Glass

log = logging.getLogger(__name__)

QML = Path(__file__).with_name("qml")
TOP = 12
"""From the top of the work area to the first alert."""
GAP = 8
"""Between two alerts."""
WATCH_MS = 20
"""How often the mouse buttons are read while a menu is open: a click lasts longer."""


class Overlay(QObject):
    """Lives on the interface thread; `show` takes each new view of `core`."""

    def __init__(self, engine: QQmlEngine, answers: Answers, glass: Glass, clock: Clock) -> None:
        super().__init__()
        self._glass = glass
        self._windows: dict[AlertSlot, QQuickWindow] = {}
        self._menus: dict[AlertSlot, QQuickWindow] = {}
        self._order: list[AlertSlot] = []
        """The slots with an alert, oldest first."""
        self._view = AlertsView((), 0, ())
        self._finished: set[int] = set()
        """Alerts answered or vanished here, until `core` stops showing them."""
        self._watch = QTimer(self, interval=WATCH_MS)
        self._watch.timeout.connect(self._watched)
        self._pressed = False
        """A mouse button was down at the last reading."""
        # The windows go with their component, which lives as long as the overlay.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "AlertWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        for _ in range(MAX_VISIBLE):
            # Made now and hidden: each has its window handle, and hears Windows' broadcasts.
            slot = AlertSlot(answers, clock, self._left)
            window = self._component.createWithInitialProperties({"slot": slot})
            if not isinstance(window, QQuickWindow):
                raise TypeError(f"no alert window: {self._component.errorString()}")
            menu = window.property("menu")
            if not isinstance(menu, QQuickWindow):
                raise TypeError("no menu in the alert window")
            # The slot goes with its window, after the bindings of the window and of its menu,
            # which goes with it: none reads a null slot.
            slot.setParent(window)
            window.heightChanged.connect(self._layout)
            slot.leaving.connect(lambda slot=slot: self._leaving(slot))
            slot.changed.connect(lambda slot=slot: self._menu(slot))
            glass.add(int(window.winId()))
            glass.add(int(menu.winId()))
            self._windows[slot] = window
            self._menus[slot] = menu

    @Slot(object)
    def show(self, view: AlertsView) -> None:
        self._view = view
        shown = {alert.id for alert in view.visible}
        self._finished &= shown
        for slot in self._order:
            if slot.alert_id not in shown:
                slot.withdraw()
        self._place()

    def _place(self) -> None:
        placed = {slot.alert_id for slot in self._order}
        for alert in self._view.visible:
            if alert.id in placed or alert.id in self._finished:
                continue
            slot = next((slot for slot in self._windows if slot.free), None)
            if slot is None:
                return  # a window is still leaving: the alert comes once it has left
            slot.present(alert)
            self._order.append(slot)
            self._layout()
            self._appear(self._windows[slot])

    def _leaving(self, slot: AlertSlot) -> None:
        if slot.alert_id is not None:
            self._finished.add(slot.alert_id)

    def _left(self, slot: AlertSlot) -> None:
        self._vanish(self._windows[slot])
        self._order.remove(slot)
        self._layout()
        self._place()

    def _layout(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        y = screen.y() + TOP
        for slot in self._order:
            window = self._windows[slot]
            window.setPosition(screen.x() + (screen.width() - window.width()) // 2, y)
            y += window.height() + GAP

    def _menu(self, slot: AlertSlot) -> None:
        """The menu shows while its slot has it open: one at a time, as Windows' menus."""
        menu = self._menus[slot]
        if slot.menu_open == menu.isVisible():
            return
        if not slot.menu_open:
            self._vanish(menu)
            if not any(other.isVisible() for other in self._menus.values()):
                self._watch.stop()
            return
        for other in self._menus:
            if other is not slot:
                other.close_menu()
        self._appear(menu)
        if not self._watch.isActive():
            self._pressed = win32.mouse_pressed()
            self._watch.start()

    def _watched(self) -> None:
        """A press outside an open menu and its alert closes the menu."""
        pressed = win32.mouse_pressed()
        if pressed and not self._pressed:
            point = QCursor.pos()
            for slot, menu in self._menus.items():
                alert = self._windows[slot]
                if menu.isVisible() and not (
                    menu.geometry().contains(point) or alert.geometry().contains(point)
                ):
                    slot.close_menu()
        self._pressed = pressed

    def _appear(self, window: QQuickWindow) -> None:
        # Out of screen capture before it shows, so that no frame of it is captured.
        self._capture(window, exclude=True)
        window.show()
        self._glass.shown(int(window.winId()))
        # Shown without activation, a window keeps its old place among those always on top,
        # maybe under an alert shown later: it goes over them all, and an open menu over it.
        win32.bring_to_front(int(window.winId()))
        for menu in self._menus.values():
            if menu.isVisible() and menu is not window:
                win32.bring_to_front(int(menu.winId()))

    def _vanish(self, window: QQuickWindow) -> None:
        window.hide()
        self._capture(window, exclude=False)

    def _capture(self, window: QQuickWindow, exclude: bool) -> None:
        error = win32.exclude_from_capture(int(window.winId()), exclude)
        if error:
            # The mistake that shows: an alert in a shared screen (ADR-0024).
            what = "kept out of" if exclude else "let back into"
            log.warning(
                "an alert's window was not %s screen capture: Windows error %d", what, error
            )
