"""The whole app on Qt's offscreen platform: a reminder written in the creation window alerts in
a context judged true, its answer is given on the alert, and the database keeps it all (#44).

The engine is the client's fake, which judges every statement true; the model file is a small
one pinned by the test; the contexts are played by the test, as the harness replays a day; the
clock is simulated.
"""

import hashlib
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, qmlEngine
from PySide6.QtQuick import QQuickWindow
from pytestqt.qtbot import QtBot

from jiffin.app.root import Jiffin
from jiffin.client.model_file import PinnedFile
from jiffin.core.clock import Clock, SimulatedClock
from jiffin.core.context import Context, Observation
from jiffin.core.debounce import DEBOUNCE_MS
from jiffin.core.records import Answer, Outcome
from jiffin.store.folders import Folders
from jiffin.store.store import Log, Store
from jiffin.ui import win32
from jiffin.ui.alert import AlertSlot
from jiffin.ui.tray import Tray

FAKE_ENGINE = [sys.executable, str(Path(__file__).parents[1] / "client" / "fake_engine.py")]
START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
CONTENT = b"Not a model: the file this test pins."
MODEL = PinnedFile(
    "model.gguf",
    "https://example.org/model.gguf",
    len(CONTENT),
    hashlib.sha256(CONTENT).hexdigest(),
)
FIGMA = Context("figma.exe", "Icone - Figma", None)


class Contexts:
    """The context port, played by the test: what it enters reaches the app as the capture's
    observations do."""

    def __init__(
        self,
        clock: Clock,
        on_observation: Callable[[Observation], None],
        on_unreadable: Callable[[frozenset[str]], None],
    ) -> None:
        self._clock = clock
        self._on_observation = on_observation
        self.started = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        pass

    def enter(self, context: Context | None) -> None:
        self._on_observation(Observation(self._clock.now(), context))


class Desk:
    """The app on a data folder of its own, with the model file already in place."""

    def __init__(self, app: QGuiApplication, folder: Path) -> None:
        self.clock = SimulatedClock(START)
        self.folders = Folders(folder)
        self.folders.models.mkdir(parents=True)
        (self.folders.models / MODEL.name).write_bytes(CONTENT)
        self.jiffin = Jiffin(
            app, self.folders, self.clock, model=MODEL, engine=FAKE_ENGINE, capture=self._capture
        )
        self.engine: QQmlEngine = self.jiffin.interface.engine

    def _capture(
        self,
        clock: Clock,
        on_observation: Callable[[Observation], None],
        on_unreadable: Callable[[frozenset[str]], None],
    ) -> Contexts:
        self.contexts = Contexts(clock, on_observation, on_unreadable)
        return self.contexts

    def alert(self) -> AlertSlot | None:
        """The alert on screen, if any."""
        for window in QGuiApplication.topLevelWindows():
            if isinstance(window, QQuickWindow) and qmlEngine(window) is self.engine:
                slot = window.findChild(AlertSlot)
                if window.isVisible() and slot is not None and slot.alert_id is not None:
                    return slot
        return None

    def window(self, title: str) -> QQuickWindow:
        (window,) = (
            w
            for w in QGuiApplication.topLevelWindows()
            if qmlEngine(w) is self.engine and w.title() == title
        )
        assert isinstance(window, QQuickWindow)
        return window

    def statement_written(self) -> bool:
        """Whether the reminder has its statement, read through a second connection."""
        with closing(sqlite3.connect(self.folders.database)) as db:
            row = db.execute("SELECT statement FROM revision").fetchone()
        return row is not None and row[0] is not None

    def log(self) -> Log:
        """What the database keeps, once the app has closed."""
        store = Store.open(self.folders.database)
        try:
            return store.log()
        finally:
            store.close()


@pytest.fixture
def desk(
    qapp: QGuiApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dwm: list[tuple[object, ...]],
) -> Iterator[Desk]:
    # The offscreen platform has no tray, and its windows no handle Windows knows; the test
    # leaves the machine's shortcut alone.
    monkeypatch.setattr(Tray, "install", lambda tray: None)
    monkeypatch.setattr(win32, "exclude_from_capture", lambda hwnd, exclude: 0)
    monkeypatch.setattr(win32, "bring_to_front", lambda hwnd: None)
    monkeypatch.setattr(win32, "register_hotkey", lambda hotkey_id, modifiers, key: 0)
    monkeypatch.setattr(win32, "unregister_hotkey", lambda hotkey_id: None)
    desk = Desk(qapp, tmp_path)
    yield desk
    desk.jiffin.close()
    qapp.processEvents()  # what the worker said last reaches the interface now
    # What the interface set on the application, for the tests after this one.
    interface = desk.jiffin.interface
    qapp.removeNativeEventFilter(interface.glass)
    qapp.removeNativeEventFilter(interface.hotkey)
    qapp.setQuitOnLastWindowClosed(True)
    QQuickWindow.setDefaultAlphaBuffer(False)


def test_a_reminder_alerts_in_its_context_and_its_answer_is_kept(qtbot: QtBot, desk: Desk) -> None:
    desk.jiffin.start()
    creation = desk.jiffin.interface.creation
    creation.new()
    creation.setCondition("quando apro Figma")
    creation.setAction("esportare le icone")
    creation.save()
    # The capture starts with the worker; the engine once the model file is checked, and it
    # writes the statement. A context judged before then would only fail.
    qtbot.waitUntil(desk.statement_written)
    desk.contexts.enter(FIGMA)
    desk.clock.advance(DEBOUNCE_MS)
    desk.contexts.enter(None)
    qtbot.waitUntil(lambda: desk.alert() is not None)
    slot = desk.alert()
    assert slot is not None
    assert (slot.property("line"), slot.property("action")) == (
        "Quando apro Figma",
        "Esportare le icone",
    )
    slot.done()
    qtbot.waitUntil(lambda: desk.alert() is None)
    desk.jiffin.close()

    log = desk.log()
    [reminder] = log.reminders
    assert reminder.completed_at == START + DEBOUNCE_MS
    assert reminder.revision.statement == "The user: quando apro Figma."
    [evaluation] = log.evaluations
    assert (evaluation.context, evaluation.context_since) == (FIGMA, START)
    assert evaluation.build is not None and evaluation.build.model_sha256 == MODEL.sha256
    assert [candidate.outcome for candidate in evaluation.candidates] == [Outcome.ALERT]
    [alert] = log.alerts
    assert (alert.evaluation_id, alert.answer) == (evaluation.id, Answer.DONE)


def test_the_windows_places_are_kept_and_put_back_at_the_start(qtbot: QtBot, desk: Desk) -> None:
    with closing(Store.open(desk.folders.database)) as store:
        store.set_setting("places", {"settings": [50, 60]})
    desk.jiffin.start()
    interface = desk.jiffin.interface
    interface.preferences.open()
    assert desk.window("Impostazioni").framePosition() == QPoint(50, 60)
    interface.creation.new()
    # Where the user drags it: the offscreen platform has no system move.
    desk.window("Nuovo promemoria").setFramePosition(QPoint(30, 40))
    interface.creation.cancel()
    interface.creation.new()
    desk.jiffin.close()

    with closing(Store.open(desk.folders.database)) as store:
        assert store.setting("places") == {"settings": [50, 60], "creation": [30, 40]}


def test_the_return_pause_is_kept_and_put_back_at_the_start(desk: Desk) -> None:
    with closing(Store.open(desk.folders.database)) as store:
        store.set_setting("return_pause", 300)
    desk.jiffin.start()
    preferences = desk.jiffin.interface.preferences
    assert preferences.return_pause == 300
    preferences.open()
    preferences.setPause(10)  # five minutes show as minutes: ten of them
    desk.jiffin.close()

    with closing(Store.open(desk.folders.database)) as store:
        assert store.setting("return_pause") == 600
