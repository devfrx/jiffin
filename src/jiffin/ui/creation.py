"""The creation window: a new reminder, or one being edited (#12, #43).

Two boxes, "Quando" and "Ricordami di", the sentence they make, and Salva and Annulla. The
shortcut and the tray list open it; it shows centred on the screen and takes the focus, and
saving or cancelling hides it. The texts go to `core` as written, with their spaces tidied: the
judge gets exactly the "Quando" box (#12).
"""

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Property, QObject, QPoint, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.ui.glass import Glass
from jiffin.ui.words import sentence, tidy

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
_ENDINGS = " .!?…;:,"
"""Left off the end of the action in the sentence, which ends with a full stop."""


class Changes(Protocol):
    """Where the changes go: `core.Reminders`' own methods, through the worker's queue."""

    def create(self, condition: str, action: str) -> None: ...
    def edit(self, reminder_id: int, condition: str, action: str) -> None: ...


@QmlElement
@QmlUncreatable("The interface makes it.")
class Creation(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window."""

    changed = Signal()
    opened = Signal(str, str)
    """Another reminder to show, with its condition and action: the boxes take them, and the
    first one the focus."""

    def __init__(self, engine: QQmlEngine, changes: Changes, glass: Glass) -> None:
        super().__init__()
        self._changes = changes
        self._reminder_id: int | None = None
        """The reminder being edited; None for a new one."""
        self._condition = ""
        self._action = ""
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "CreationWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"creation": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no creation window: {self._component.errorString()}")
        self._window = window
        glass.add_framed(int(window.winId()))

    def new(self) -> None:
        """A blank reminder; one already being written stays as it is."""
        if not (self._window.isVisible() and self._reminder_id is None):
            self._open(None, "", "")
        self._present()

    def edit(self, reminder_id: int, condition: str, action: str) -> None:
        if not (self._window.isVisible() and self._reminder_id == reminder_id):
            self._open(reminder_id, condition, action)
        self._present()

    @Property(bool, notify=changed)
    def editing(self) -> bool:
        return self._reminder_id is not None

    @Property(str, notify=changed)
    def conditionSentence(self) -> str:
        return sentence(tidy(self._condition))

    @Property(str, notify=changed)
    def actionWords(self) -> str:
        return tidy(self._action).rstrip(_ENDINGS)

    @Property(bool, notify=changed)
    def ready(self) -> bool:
        """Both boxes are written: Salva saves."""
        return self._ready()

    @Slot(str)
    def setCondition(self, text: str) -> None:
        if text != self._condition:
            self._condition = text
            self.changed.emit()

    @Slot(str)
    def setAction(self, text: str) -> None:
        if text != self._action:
            self._action = text
            self.changed.emit()

    @Slot()
    def save(self) -> None:
        if not self._ready():
            return
        condition, action = tidy(self._condition), tidy(self._action)
        if self._reminder_id is None:
            self._changes.create(condition, action)
        else:
            self._changes.edit(self._reminder_id, condition, action)
        self._window.hide()

    @Slot()
    def cancel(self) -> None:
        self._window.hide()

    def _ready(self) -> bool:
        return bool(tidy(self._condition)) and bool(tidy(self._action))

    def _open(self, reminder_id: int | None, condition: str, action: str) -> None:
        self._reminder_id = reminder_id
        self._condition, self._action = condition, action
        self.changed.emit()
        self.opened.emit(condition, action)

    def _present(self) -> None:
        window = self._window
        area = QGuiApplication.primaryScreen().availableGeometry()
        frame = window.frameMargins()
        width = window.width() + frame.left() + frame.right()
        height = window.height() + frame.top() + frame.bottom()
        window.setFramePosition(
            QPoint(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2)
        )
        window.show()
        # On Windows, activating the window also brings it to the front.
        window.requestActivate()
