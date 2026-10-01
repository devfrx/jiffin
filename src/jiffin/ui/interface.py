"""The pieces of the interface that share one QML engine: the look, the glass and the overlay."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.ui.alert import Answers
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look
from jiffin.ui.overlay import Overlay


class Interface:
    """Make it on the interface thread, after the application and before any window."""

    def __init__(self, app: QGuiApplication, answers: Answers) -> None:
        # The glass shows only where the QML is transparent (ADR-0010).
        QQuickWindow.setDefaultAlphaBuffer(True)
        self.look = Look()
        self.look.follow(app)
        self.glass = Glass(self.look)
        app.installNativeEventFilter(self.glass)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.overlay = Overlay(self.engine, answers, self.glass)
