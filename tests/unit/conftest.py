"""The tests that show windows run on Qt's offscreen platform: the windows lay out, animate and
take the mouse without showing on the screen. Any Qt warning fails a test (`qt_log_level_fail`)."""

import gc
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from jiffin.ui import win32


@pytest.fixture(scope="session")
def qapp_args() -> list[str]:
    # The offscreen platform looks for fonts in Qt's own folder, which PySide6 leaves empty.
    os.environ["QT_QPA_FONTDIR"] = str(Path(os.environ["WINDIR"], "Fonts"))
    return ["jiffin", "-platform", "offscreen"]


@pytest.fixture(scope="session")
def qapp_cls() -> type[QGuiApplication]:
    return QGuiApplication


@pytest.fixture(autouse=True)
def collected(request: pytest.FixtureRequest) -> None:
    """Earlier tests' engines go, with their windows, when the garbage collector runs: at any
    moment, even while a test reads `topLevelWindows()`, whose windows then raise "already
    deleted". Collected before each test with Qt, they go now."""
    if "qapp" in request.fixturenames:
        gc.collect()


@pytest.fixture
def dwm(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """What the glass asks of DWM, recorded instead of done: (function, *arguments)."""
    calls: list[tuple[object, ...]] = []
    for name in ("set_backdrop", "recreate_backdrop", "activate_frame", "nudge"):
        monkeypatch.setattr(win32, name, lambda *args, name=name: calls.append((name, *args)))
    return calls


def drag_handlers(item: QQuickItem) -> Iterator[QObject]:
    """Item by item: `findChildren(QObject)` on a QML window wraps every object in it, and at the
    next garbage collection the window's bindings read their ids as null, which warns."""
    for child in item.childItems():
        yield from (o for o in child.children() if o.inherits("QQuickDragHandler"))
        yield from drag_handlers(child)


@pytest.fixture
def drags() -> Callable[[QQuickWindow, QPoint], bool]:
    """Whether a drag with the mouse from a point of a window moves the window: its DragHandler
    takes the drag and hands it to Windows, with `startSystemMove`. The offscreen platform has no
    system move, so the window itself stays where it is."""

    def drags(window: QQuickWindow, point: QPoint) -> bool:
        (handler,) = drag_handlers(window.contentItem())
        left, none = Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
        QTest.mousePress(window, left, none, point)
        # Past the distance where a press becomes a drag, a step at a time, towards the middle:
        # QTest warns of a mouse outside the window.
        step = QPoint(10 if point.x() < window.width() // 2 else -10, 0)
        end = point
        for _ in range(5):
            end = end + step
            QTest.mouseMove(window, end)
        moving = bool(handler.property("active"))
        QTest.mouseRelease(window, left, none, end)
        return moving

    return drags
