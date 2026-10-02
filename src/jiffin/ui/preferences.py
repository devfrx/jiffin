"""The settings window: the material of Jiffin's windows (#43, ADR-0010).

A card like the creation window, with the four materials as radio buttons. The tray icon's menu
opens it, centred on the screen, and it takes the focus. A click on a material changes every
window at once, as Windows' own Settings, and the choice goes to be kept; Chiudi or Esc hides
it.
"""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QObject, QPoint, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Material

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")


@QmlElement
@QmlUncreatable("The interface makes it.")
class Preferences(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window. `keep` takes each new choice, for the app
    to store; the app sets the stored one on the look at the start."""

    changed = Signal()
    opened = Signal()
    """The window shows again: the focus goes to the material in use."""

    def __init__(
        self, engine: QQmlEngine, look: Look, keep: Callable[[Material], None], glass: Glass
    ) -> None:
        # The engine owns this object, as the creation window's: the window's bindings never
        # read it gone.
        super().__init__(engine)
        self._look = look
        self._keep = keep
        self._glass = glass
        look.changed.connect(self.changed)
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "PreferencesWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"preferences": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no settings window: {self._component.errorString()}")
        self._window = window
        glass.add(int(window.winId()))

    def open(self) -> None:
        """Centred on the screen, with the focus; an open window comes to the front."""
        window = self._window
        if not window.isVisible():
            area = QGuiApplication.primaryScreen().availableGeometry()
            frame = window.frameMargins()
            width = window.width() + frame.left() + frame.right()
            height = window.height() + frame.top() + frame.bottom()
            window.setFramePosition(
                QPoint(
                    area.x() + (area.width() - width) // 2,
                    area.y() + (area.height() - height) // 2,
                )
            )
            self.opened.emit()
        window.show()
        self._glass.shown(int(window.winId()))
        # On Windows, activating the window also brings it to the front.
        window.requestActivate()

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
        self._window.hide()
