"""The composition root (ADR-0012): it makes the adapters, connects the ports, and starts the
threads and Qt. `python -m jiffin` in a checkout, `Jiffin.exe` once packaged (ADR-0015).

The start goes in this order: in the packaged app, Velopack's hooks and a newer release, applied
before anything opens; the database, migrated and cleaned up; the model file, checked or
downloaded; the engine; then the context capture. Esci shuts down in order: the capture, the
engine with `shutdown` and its input closed, then the database with a last checkpoint.
"""

import logging
import logging.handlers
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication

from jiffin.app import updates, win32
from jiffin.app.model import ModelFetch
from jiffin.app.relay import Relay
from jiffin.app.worker import QueuedCore, Source, Worker
from jiffin.client.model_file import MODEL, PinnedFile
from jiffin.core.clock import Clock, SystemClock
from jiffin.core.context import Observation
from jiffin.platform.capture import Capture
from jiffin.store.folders import Folders
from jiffin.ui.first_run import ModelFile
from jiffin.ui.interface import Interface
from jiffin.ui.look import Material

log = logging.getLogger(__name__)

INSTANCE = "Local\\devfrx.Jiffin"
"""The mutex that keeps a second Jiffin from starting in the same session: two would share the
database, the GPU's memory and the shortcut."""
LOG_FILE = "jiffin.log"
LOG_BYTES = 1 << 20
LOG_BACKUPS = 4
"""The log turns over at 1 MiB and keeps four old files."""
CANNOT_START = "Jiffin non è riuscito a partire.\n\nIl motivo è scritto nel log:\n{log}"

type MakeCapture = Callable[
    [Clock, Callable[[Observation], None], Callable[[frozenset[str]], None]], Source
]


class Jiffin:
    """The app put together on the interface thread: the interface, and the worker with `core`,
    the store and the engine, the model file's thread and the context capture. It is the
    interface's upkeep too."""

    def __init__(
        self,
        app: QGuiApplication,
        folders: Folders,
        clock: Clock,
        *,
        model: PinnedFile = MODEL,
        engine: Sequence[str] | None = None,
        capture: MakeCapture = Capture,
    ) -> None:
        relay = Relay()
        self._worker = Worker(
            clock,
            folders.database,
            folders.models / model.name,
            model.sha256,
            relay.alerts.emit,
            relay.reminders.emit,
            relay.engine.emit,
            lambda observe: capture(clock, observe, relay.unreadable.emit),
            engine=engine,
        )
        self._fetch = ModelFetch(model, folders.models, relay.model.emit, self._worker.model_ready)
        self.interface = Interface(
            app,
            QueuedCore(self._worker),
            self,
            ModelFile(model.name, model.url, model.size, model.sha256, folders.models),
            clock,
        )
        relay.deliver(self.interface)
        self._relay = relay

    def start(self) -> None:
        """Open the database and put on the material it kept, before any window shows; then the
        model file. Raise what opening the database raised."""
        kept = self._worker.start()
        if kept is not None:
            try:
                self.interface.look.material = Material(kept)
            except ValueError:  # from a later version, after a downgrade
                log.warning("the kept material %r is unknown: the default stays", kept)
        self._fetch.fetch()

    def close(self) -> None:
        """Once Qt has quit."""
        self.interface.hotkey.close()
        self._worker.close()

    # The interface's upkeep

    def restart_engine(self) -> None:
        self._worker.restart_engine()

    def fetch_model(self) -> None:
        self._fetch.fetch()

    def keep_material(self, material: Material) -> None:
        self._worker.keep_material(material.value)


def main() -> None:
    updates.hooks()
    if not win32.first_instance(INSTANCE):
        return
    folders = Folders.app()
    folders.logs.mkdir(parents=True, exist_ok=True)
    keep_log(folders.logs)
    updates.update()
    # Ctrl+C in the terminal ends it at once, as it does the interface's preview.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QGuiApplication(sys.argv)
    jiffin = Jiffin(app, folders, SystemClock())
    try:
        jiffin.start()
    except Exception:
        log.exception("Jiffin cannot start")
        jiffin.close()
        win32.show_error(CANNOT_START.format(log=folders.logs / LOG_FILE))
        sys.exit(1)
    try:
        code = app.exec()
    finally:
        jiffin.close()
    sys.exit(code)


def keep_log(folder: Path) -> None:
    """The app log, with ids and numbers only (ADR-0013): in `folder`, and in the terminal when
    there is one. Uncaught exceptions and Qt's own messages go there too, since the packaged app
    has no console."""
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            folder / LOG_FILE, maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s",
        handlers=handlers,
    )
    sys.excepthook = _uncaught
    threading.excepthook = _uncaught_in_thread
    qInstallMessageHandler(_qt_message)


def _uncaught(
    kind: type[BaseException], exception: BaseException, traceback: TracebackType | None
) -> None:
    log.critical("uncaught", exc_info=exception)


def _uncaught_in_thread(hook: threading.ExceptHookArgs) -> None:
    log.critical("uncaught", exc_info=hook.exc_value)


_QT_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def _qt_message(kind: QtMsgType, context: QMessageLogContext, message: str) -> None:
    logging.getLogger("qt").log(_QT_LEVELS.get(kind, logging.WARNING), "%s", message)
