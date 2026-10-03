"""Where the creation window, the settings and the first-run window open (ADR-0023).

Each opens at the centre of the primary screen's work area until the user moves it; then where
they left it, also after a restart, as long as the whole window fits on a screen there. A place on
a monitor since unplugged opens it at the centre, and stays kept for when the monitor is back. The
interface stores nothing (ADR-0012): the places go to the app to keep, and come back at the next
start, before any window shows.

A move is any place Jiffin did not put the window at, whoever made it: the user's drag, or Windows
taking it off a screen that went. `framePosition()` reads the platform window at once, while Qt
emits its x and y signals later, from its window-system queue: the comparison holds whatever order
they come in.
"""

from collections.abc import Callable, Mapping

from PySide6.QtCore import QPoint, QRect, QSize, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickWindow

KEEP_AFTER_MS = 500
"""A moved window's place is kept this long after it last moved: once a drag ends, not at every
step of it."""


class Places:
    """Where the user left each window that keeps its place, by name. `keep` takes them all at
    every move, for the app to store; the app gives them back to `restore` at the start."""

    def __init__(self, keep: Callable[[Mapping[str, tuple[int, int]]], None]) -> None:
        self._keep = keep
        self._kept: dict[str, QPoint] = {}

    def restore(self, kept: Mapping[str, tuple[int, int]]) -> None:
        """The places of the last run: before any window shows."""
        self._kept = {name: QPoint(x, y) for name, (x, y) in kept.items()}

    def follow(self, name: str, window: QQuickWindow) -> "Place":
        return Place(self, name, window)

    def kept(self, name: str) -> QPoint | None:
        return self._kept.get(name)

    def keep(self, name: str, point: QPoint) -> None:
        self._kept[name] = point
        self._keep({name: (point.x(), point.y()) for name, point in self._kept.items()})


class Place:
    """One window's place: `open` puts the window before it shows. A window whose height changes
    while it shows calls `resized`, to stay centred."""

    def __init__(self, places: Places, name: str, window: QQuickWindow) -> None:
        self._places = places
        self._name = name
        self._window = window
        self._put_at: QPoint | None = None
        """Where Jiffin last put the window: None until it first opens."""
        self._centred = False
        """Jiffin put it at the centre, not where the user left it."""
        self._settle = QTimer(singleShot=True, interval=KEEP_AFTER_MS)
        self._settle.timeout.connect(self._keep_if_moved)
        window.xChanged.connect(self._moved)
        window.yChanged.connect(self._moved)

    def open(self) -> None:
        """Where the user left the window, if it fits on a screen there; at the centre
        otherwise. A move made just before it closed is kept first."""
        self._keep_if_moved()
        kept = self._places.kept(self._name)
        if kept is not None and self._fits(kept):
            self._put(kept, centred=False)
        else:
            self._put(self._centre(), centred=True)

    def resized(self) -> None:
        """A window Jiffin centred stays centred; one the user moved, or put back where they
        left it, keeps its top left corner, as Windows' own windows do."""
        if self._centred and self._window.framePosition() == self._put_at:
            self._put(self._centre(), centred=True)

    def _moved(self) -> None:
        self._settle.start()

    def _keep_if_moved(self) -> None:
        self._settle.stop()
        point = self._window.framePosition()
        if self._put_at is None or point == self._put_at:
            return
        if point != self._places.kept(self._name):
            self._places.keep(self._name, point)

    def _put(self, point: QPoint, centred: bool) -> None:
        self._window.setFramePosition(point)
        # Where the platform put it, rounding included: any other place is a move.
        self._put_at = self._window.framePosition()
        self._centred = centred

    def _fits(self, point: QPoint) -> bool:
        frame = QRect(point, self._frame_size())
        return any(
            screen.availableGeometry().contains(frame) for screen in QGuiApplication.screens()
        )

    def _centre(self) -> QPoint:
        area = QGuiApplication.primaryScreen().availableGeometry()
        size = self._frame_size()
        return QPoint(
            area.x() + (area.width() - size.width()) // 2,
            area.y() + (area.height() - size.height()) // 2,
        )

    def _frame_size(self) -> QSize:
        window, frame = self._window, self._window.frameMargins()
        return QSize(
            window.width() + frame.left() + frame.right(),
            window.height() + frame.top() + frame.bottom(),
        )
