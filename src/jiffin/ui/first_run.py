"""The first run: the window that shows the model file on its way, and the state the tray list
shows of it (#43, ADR-0015).

The installer does not ship the model: at the first start the app downloads it, for minutes, and
checks it; then the engine can start. The window opens by itself when the model needs the user
to wait or to act, for a download or a problem, and shows three steps: the download, the check,
and ready, with how to start. The plain check at every start opens nothing. Once the user closes
it, it stays closed for this run: the tray list shows the download and the problems, and its
Dettagli opens the window again. Offline, the window says where to get the file and where to put
it, and Riprova checks it as it checks a download. It opens at the centre of the screen, or where
the user left it (ADR-0023).
"""

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Property, QEnum, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

from jiffin.core.clock import Clock
from jiffin.ui.glass import Glass
from jiffin.ui.places import Places

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

QML = Path(__file__).with_name("qml")
PACE_MS = 30_000
"""The download's pace is measured over this much of its recent past."""
FIRST_PACE_MS = 5_000
"""How much of the download it takes before the time left means anything."""


@dataclass(frozen=True, slots=True)
class ModelFile:
    """The model file as the user may fetch it by hand: the app gives `client.model_file`'s pin
    and its folder, since the interface does not import `client` (ADR-0012)."""

    name: str
    url: str
    size: int
    sha256: str
    folder: Path


@dataclass(frozen=True, slots=True)
class ModelState:
    """What the app says of the model file: `client.model_file`'s progress, or its problem."""

    stage: "FirstRun.Stage"
    done: int = 0
    """Bytes downloaded, or checked."""
    total: int = 0
    missing: int = 0
    """For SPACE: the bytes to free on the disk."""


@QmlElement
@QmlUncreatable("The interface makes it.")
class FirstRun(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread with its window; `show` takes what the app says of the model
    file, `fetch` gets it again."""

    @QEnum
    class Stage(Enum):
        """Where the model file is: app maps `model_file`'s progress and problems to it (#44)."""

        CHECKING = 0
        """Read for its sha256: at every start, and after a download."""
        DOWNLOADING = 1
        READY = 2
        """Checked: the engine can start."""
        NETWORK = 3
        """The download stopped: what arrived is kept, and Riprova resumes it."""
        SPACE = 4
        DISK = 5
        """The models folder or the file cannot be written or read."""
        MISMATCH = 6
        """The file is not the pinned one."""

    changed = Signal()
    opened = Signal()
    """The window shows again: what it had open closes."""

    def __init__(
        self,
        engine: QQmlEngine,
        model: ModelFile,
        fetch: Callable[[], None],
        glass: Glass,
        places: Places,
        clock: Clock,
    ) -> None:
        # The engine owns this object, as the creation window's: the windows' bindings never
        # read it gone.
        super().__init__(engine)
        self._model = model
        self._fetch = fetch
        self._glass = glass
        self._clock = clock
        self._state = ModelState(FirstRun.Stage.CHECKING)
        self._step = 1
        """The step of the last progress: a problem with the disk belongs to it."""
        self._pace: deque[tuple[int, int]] = deque()
        """The download's recent progress: (when, bytes done)."""
        self._retrying = False
        self._dismissed = False
        """The user closed the window during this run: it opens again only from the list."""
        self._shortcut = True
        # The window goes with its component, which lives as long as this object.
        self._component = QQmlComponent(engine, QUrl.fromLocalFile(QML / "FirstRunWindow.qml"))
        if self._component.isError():
            raise RuntimeError(self._component.errorString())
        window = self._component.createWithInitialProperties({"firstRun": self})
        if not isinstance(window, QQuickWindow):
            raise TypeError(f"no first-run window: {self._component.errorString()}")
        self._window = window
        self._place = places.follow("first_run", window)
        # Steps come and go, and lines wrap once the layout gives them their width: a centred
        # window stays centred.
        window.heightChanged.connect(self._place.resized)
        glass.add(int(window.winId()))

    def show(self, state: ModelState) -> None:
        stage = state.stage
        if stage is FirstRun.Stage.DOWNLOADING:
            self._step = 1
            self._pace.append((self._clock.now(), state.done))
            while self._pace[-1][0] - self._pace[0][0] > PACE_MS and len(self._pace) > 2:
                self._pace.popleft()
        else:
            self._pace.clear()
            if stage is FirstRun.Stage.CHECKING:
                self._step = 2
            elif stage is FirstRun.Stage.READY:
                self._step = 3
        self._state = state
        self._retrying = False
        self.changed.emit()
        if self._waits() and not self._dismissed and not self._window.isVisible():
            self._open()

    def open(self) -> None:
        """Dettagli, in the tray list: the window again, even once closed."""
        self._open()

    @property
    def shortcut(self) -> bool:
        return self._shortcut

    @shortcut.setter
    def shortcut(self, registered: bool) -> None:
        """Whether Win+Shift+N is Jiffin's: another app may hold it."""
        if registered != self._shortcut:
            self._shortcut = registered
            self.changed.emit()

    @Property(int, notify=changed)
    def stage(self) -> int:
        return self._state.stage.value

    @Property(int, notify=changed)
    def step(self) -> int:
        """1 the download, 2 the check, 3 ready; a problem keeps the step it stopped."""
        if self._state.stage is FirstRun.Stage.MISMATCH:
            return 2
        if self._state.stage in (FirstRun.Stage.NETWORK, FirstRun.Stage.SPACE):
            return 1
        return self._step

    @Property(bool, notify=changed)
    def problem(self) -> bool:
        return self._state.stage in _PROBLEMS

    @Property(bool, notify=changed)
    def waiting(self) -> bool:
        """A download or a problem: the tray list shows a line for it."""
        return self._waits()

    @Property(bool, notify=changed)
    def retrying(self) -> bool:
        """Riprova was pressed, and the app has not answered yet."""
        return self._retrying

    # Floats: a QML int has 32 bits, and the model has 2.6 billion bytes.
    @Property(float, notify=changed)
    def done(self) -> float:
        return float(self._state.done)

    @Property(float, notify=changed)
    def total(self) -> float:
        return float(self._total())

    @Property(float, notify=changed)
    def missing(self) -> float:
        return float(self._state.missing)

    @Property(int, notify=changed)
    def minutes(self) -> int:
        """The download's time left: -1 while unknown, 0 for less than a minute."""
        if len(self._pace) < 2:
            return -1
        (start, first), (end, last) = self._pace[0], self._pace[-1]
        if end - start < FIRST_PACE_MS or last <= first:
            return -1
        left = (self._total() - last) * (end - start) / (last - first) / 1000
        return 0 if left < 60 else math.ceil(left / 60)

    @Property(bool, notify=changed)
    def hasShortcut(self) -> bool:
        return self._shortcut

    @Property(str, notify=changed)
    def address(self) -> str:
        return self._model.url

    @Property(str, notify=changed)
    def folder(self) -> str:
        return str(self._model.folder)

    @Property(str, notify=changed)
    def fileName(self) -> str:
        return self._model.name

    @Property(float, notify=changed)
    def size(self) -> float:
        return float(self._model.size)

    @Property(str, notify=changed)
    def sha256(self) -> str:
        return self._model.sha256

    @Slot()
    def retry(self) -> None:
        self._retrying = True
        self.changed.emit()
        self._fetch()

    @Slot()
    def copyAddress(self) -> None:
        QGuiApplication.clipboard().setText(self._model.url)

    @Slot()
    def openFolder(self) -> None:
        """In Explorer: made first, since the download may not have made it yet."""
        try:
            self._model.folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._model.folder)))

    @Slot()
    def close(self) -> None:
        if not self._window.isVisible():
            return
        self._window.hide()
        if self._state.stage is not FirstRun.Stage.READY:
            self._dismissed = True

    def _waits(self) -> bool:
        return self._state.stage is FirstRun.Stage.DOWNLOADING or self._state.stage in _PROBLEMS

    def _total(self) -> int:
        return self._state.total or self._model.size

    def _open(self) -> None:
        window = self._window
        if not window.isVisible():
            self._place.open()
            self.opened.emit()
        window.show()
        self._glass.shown(int(window.winId()))
        # On Windows, activating the window also brings it to the front.
        window.requestActivate()


# After the class: inside its body, PySide's QEnum has not made the enum yet.
_PROBLEMS = frozenset(
    (FirstRun.Stage.NETWORK, FirstRun.Stage.SPACE, FirstRun.Stage.DISK, FirstRun.Stage.MISMATCH)
)
