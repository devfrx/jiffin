"""The alerts on screen: up to three windows at the top centre of the screen (#12, ADR-0010).

`core` says which alerts are on screen; the overlay gives each one a window, stacked from the
top in the order they came, and the others move up once one has left. An alert answered here
never comes back, even if a view from before the answer arrives after its window has left.
"""

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.alerts import MAX_VISIBLE, AlertsView
from jiffin.ui.alert import AlertSlot, Answers
from jiffin.ui.glass import Glass

QML = Path(__file__).with_name("qml")
TOP = 12
"""From the top of the work area to the first alert."""
GAP = 8
"""Between two alerts."""


class Overlay(QObject):
    """Lives on the interface thread; `show` takes each new view of `core`."""

    def __init__(self, engine: QQmlEngine, answers: Answers, glass: Glass) -> None:
        super().__init__()
        self._glass = glass
        self._windows: dict[AlertSlot, QQuickWindow] = {}
        self._order: list[AlertSlot] = []
        """The slots with an alert, oldest first."""
        self._view = AlertsView((), 0, ())
        self._finished: set[int] = set()
        """Alerts answered or vanished here, until `core` stops showing them."""
        # The windows go with their component, which lives as long as the overlay.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "AlertWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        for _ in range(MAX_VISIBLE):
            # Made now and hidden: each has its window handle, and hears Windows' broadcasts.
            slot = AlertSlot(answers, self._left)
            window = self._component.createWithInitialProperties({"slot": slot})
            if not isinstance(window, QQuickWindow):
                raise TypeError(f"no alert window: {self._component.errorString()}")
            # The slot goes with its window, after the window's bindings: none reads a null slot.
            slot.setParent(window)
            window.heightChanged.connect(self._layout)
            slot.leaving.connect(lambda slot=slot: self._leaving(slot))
            glass.add(int(window.winId()))
            self._windows[slot] = window

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
            slot.present(alert.id, alert.revision.condition, alert.revision.action)
            self._order.append(slot)
            self._layout()
            window = self._windows[slot]
            window.show()
            self._glass.shown(int(window.winId()))

    def _leaving(self, slot: AlertSlot) -> None:
        if slot.alert_id is not None:
            self._finished.add(slot.alert_id)

    def _left(self, slot: AlertSlot) -> None:
        self._windows[slot].hide()
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
