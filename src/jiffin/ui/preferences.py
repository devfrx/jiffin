"""The settings window: the return pause, then the material of Jiffin's windows (#43, #84,
ADR-0010, ADR-0021).

A card like the creation window. The return pause is a number and its unit, secondi or minuti,
as WinUI's NumberBox and ComboBox; the combo box's list is a window of its own on the glass,
which never takes the focus, as Rimanda's menu. The four materials are radio buttons. The tray
icon's menu opens the window, and Cambia in the tray list, at the centre of the screen or where
the user left it (ADR-0023), and it takes the focus, on the pause. Each change applies at once,
as in Windows' own Settings, and goes to be kept; the X or Esc hides the window, as there, with
no Chiudi.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.reminders import (
    LONGEST_RETURN_PAUSE_MS,
    RETURN_PAUSE_MS,
    SHORTEST_RETURN_PAUSE_MS,
)
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Material
from jiffin.ui.places import Places

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
MINUTE = 60
SHORTEST_PAUSE = SHORTEST_RETURN_PAUSE_MS // 1000
LONGEST_PAUSE = LONGEST_RETURN_PAUSE_MS // 1000
"""The return pause's range, in seconds: 10 s to 2 hours (#84)."""
SHORTEST_MINUTES = -(-SHORTEST_PAUSE // MINUTE)
"""The shortest pause in whole minutes: 1."""


@QmlElement
@QmlUncreatable("The interface makes it.")
class Preferences(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window. `keep` takes each new material and
    `keep_return_pause` each new pause, in seconds, for the app to store; the app sets the stored
    ones on the look and on `return_pause` at the start."""

    changed = Signal()
    opened = Signal()
    """The window shows again: the focus goes to the pause."""

    def __init__(
        self,
        engine: QQmlEngine,
        look: Look,
        keep: Callable[[Material], None],
        keep_return_pause: Callable[[int], None],
        glass: Glass,
        places: Places,
    ) -> None:
        # The engine owns this object, as the creation window's: the window's bindings never
        # read it gone.
        super().__init__(engine)
        self._look = look
        self._keep = keep
        self._keep_return_pause = keep_return_pause
        self._glass = glass
        self._return_pause = RETURN_PAUSE_MS // 1000
        self._minutes = True
        self._units_open = False
        look.changed.connect(self.changed)
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "PreferencesWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"preferences": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no settings window: {self._component.errorString()}")
        units = window.property("units")
        if not isinstance(units, QQuickWindow):
            raise TypeError("no list of units in the settings window")
        self._window = window
        self._units = units
        self._place = places.follow("settings", window)
        # A line that wraps once the layout gives it its width, or the note on solid surfaces,
        # makes the window taller after it is placed: a centred one stays centred.
        window.heightChanged.connect(self._place.resized)
        glass.add(int(window.winId()))
        glass.add(int(units.winId()))

    @property
    def return_pause(self) -> int:
        """In seconds; the app sets the kept one at the start."""
        return self._return_pause

    @return_pause.setter
    def return_pause(self, seconds: int) -> None:
        self._return_pause = seconds
        self.changed.emit()

    def open(self) -> None:
        """With the focus; an open window comes to the front where it is. The pause shows in
        minutes when it is whole minutes, else in seconds, until the user picks the unit."""
        window = self._window
        if not window.isVisible():
            self._minutes = self._return_pause % MINUTE == 0
            self.changed.emit()
            self._place.open()
            self.opened.emit()
        window.show()
        self._glass.shown(int(window.winId()))
        # On Windows, activating the window also brings it to the front.
        window.requestActivate()

    @Property(int, notify=changed)
    def returnPause(self) -> int:
        """In seconds."""
        return self._return_pause

    @Property(bool, notify=changed)
    def minutes(self) -> bool:
        """The unit the pause shows in: minuti, or secondi."""
        return self._minutes

    @Property(int, notify=changed)
    def pauseValue(self) -> int:
        """The pause in its unit."""
        return self._return_pause // MINUTE if self._minutes else self._return_pause

    @Property(int, notify=changed)
    def pauseFrom(self) -> int:
        return self._range()[0]

    @Property(int, notify=changed)
    def pauseTo(self) -> int:
        return self._range()[1]

    @Slot(int)
    def setPause(self, value: int) -> None:
        """A number for the pause, in its unit, brought back within that unit's range: in
        minutes, never under one minute."""
        lowest, highest = self._range()
        value = max(lowest, min(highest, value))
        self._set_pause(value * MINUTE if self._minutes else value)
        # Also unchanged: the number box shows the pause again, in range.
        self.changed.emit()

    @Slot(bool)
    def setMinutes(self, minutes: bool) -> None:
        """Another unit: the pause converts, to the nearest minute, half up."""
        self.closeUnits()
        if minutes == self._minutes:
            return
        self._minutes = minutes
        if minutes:
            whole = (self._return_pause + MINUTE // 2) // MINUTE
            self._set_pause(max(SHORTEST_MINUTES, whole) * MINUTE)
        self.changed.emit()

    @Property(bool, notify=changed)
    def unitsOpen(self) -> bool:
        """The combo box's list shows, until a unit is picked, a press anywhere else in the
        window, Esc, or the focus leaving the combo box."""
        return self._units_open

    @Slot()
    def toggleUnits(self) -> None:
        if self._units_open:
            self.closeUnits()
            return
        self._units_open = True
        self.changed.emit()
        units = self._units
        units.show()
        self._glass.shown(int(units.winId()))

    @Slot()
    def closeUnits(self) -> None:
        if self._units_open:
            self._units_open = False
            self._units.hide()
            self.changed.emit()

    # A QStringList, as the tray list's browsers: Qt takes a type by its name, which the stub does
    # not know.
    @Property("QStringList", notify=changed)  # type: ignore[arg-type]
    def materials(self) -> list[str]:
        """The four, in order, by their letters; Texts names them."""
        return [material.value for material in Material]

    @Property(str, notify=changed)
    def material(self) -> str:
        return self._look.material.value

    @Slot(str)
    def choose(self, letter: str) -> None:
        material = Material(letter)
        if material != self._look.material:
            self._look.material = material
            self._keep(material)

    @Slot()
    def close(self) -> None:
        self.closeUnits()
        self._window.hide()

    def _range(self) -> tuple[int, int]:
        """The pause's range in its unit."""
        if self._minutes:
            return SHORTEST_MINUTES, LONGEST_PAUSE // MINUTE
        return SHORTEST_PAUSE, LONGEST_PAUSE

    def _set_pause(self, seconds: int) -> None:
        if seconds != self._return_pause:
            self._return_pause = seconds
            self._keep_return_pause(seconds)
