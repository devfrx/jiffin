import gc
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QWindow
from PySide6.QtQml import QQmlEngine, QQmlProperty, qmlContext, qmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from jiffin.core.clock import SimulatedClock
from jiffin.lang.texts import TEXTS
from jiffin.ui import win32
from jiffin.ui.first_run import FirstRun, ModelFile, ModelState
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Settings
from jiffin.ui.places import Places

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)
NAME = "spark-x2.5-4b-rizzo-flow-lora-q4_k_m.gguf"
URL = f"https://huggingface.co/rizzoaiacademy/rizzo-flow/resolve/55633c8/{NAME}"
SIZE = 2_600_224_416
SHA256 = "79de5cb8dbfd1a1f5cb3037252251594352841fe5e3dc1ae8cead053010fcd54"
GIB = 1 << 30
Stage = FirstRun.Stage
WAIT = [
    "Benvenuto in Jiffin",
    "Jiffin lavora solo su questo PC: niente esce da qui.",
]
STEPS_AFTER_DOWNLOAD = ["2", "Controllo il file", "3", "Pronto"]
MEANWHILE = "Intanto puoi già scrivere i promemoria: premi Win+Maiusc+N."


def items(item: QQuickItem) -> Iterator[QQuickItem]:
    for child in item.childItems():
        yield child
        yield from items(child)


def accessible(item: QQuickItem, name: str) -> object:
    """None for the items a control makes on its own, which QML never sees."""
    context = qmlContext(item)
    return None if context is None else QQmlProperty(item, f"Accessible.{name}", context).read()


def in_button(item: QQuickItem) -> bool:
    parent = item.parentItem()
    while parent is not None:
        if parent.inherits("QQuickAbstractButton"):
            return True
        parent = parent.parentItem()
    return False


class Screen:
    """The first-run window on the offscreen screen, with the Retry it was asked and the
    places it kept."""

    def __init__(self, qtbot: QtBot, folder: Path) -> None:
        self._qtbot = qtbot
        self.look = Look(lambda: DARK)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.clock = SimulatedClock(0)
        self.fetches = 0
        self.folder = folder
        self.placed: list[dict[str, tuple[int, int]]] = []
        self.places = Places(lambda places: self.placed.append(dict(places)))
        model = ModelFile(NAME, URL, SIZE, SHA256, folder)
        self.first_run = FirstRun(
            self.engine, model, self._fetch, Glass(self.look), self.places, self.clock
        )
        (window,) = (w for w in QGuiApplication.topLevelWindows() if qmlEngine(w) is self.engine)
        assert isinstance(window, QQuickWindow)
        self.window = window

    def show(self, stage: FirstRun.Stage, done: int = 0, missing: int = 0) -> None:
        self.first_run.show(ModelState(stage, done, SIZE, missing))

    def opened(self) -> None:
        """The window opened by itself: ready once it has the focus."""
        self._qtbot.waitUntil(self.window.isActive)

    def lines(self) -> list[str]:
        """What the window reads, top to bottom and left to right, without its buttons and
        icons. By their middle: a step's number is centred on its name."""
        found = []
        for item in self._shown():
            text = str(item.property("text")) if item.inherits("QQuickText") else ""
            if text and not in_button(item) and not "" <= text[0] <= "":
                middle = item.mapToScene(QPointF(0, item.height() / 2))
                found.append((round(middle.y()), middle.x(), text))
        return [text for _, _, text in sorted(found)]

    def button(self, name: str) -> QQuickItem:
        return next(
            item
            for item in self._shown()
            if item.inherits("QQuickAbstractButton") and accessible(item, "name") == name
        )

    def x(self) -> QQuickItem:
        """The X: Close too, as the button at the bottom while the model is on its way."""
        return next(
            item
            for item in self._shown()
            if item.inherits("QQuickAbstractButton") and item.property("glyph") == ""
        )

    def click(self, name: str) -> None:
        """Once the window's scene holds the button: it grows through the event queue, which
        QTest's click skips (see the tray list's tests)."""
        self.click_on(self.button(name))

    def click_on(self, button: QQuickItem) -> None:
        def centre() -> QPointF:
            return button.mapToScene(QPointF(button.width() / 2, button.height() / 2))

        scene = self.window.contentItem()
        self._qtbot.waitUntil(lambda: scene.boundingRect().contains(centre()))
        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            centre().toPoint(),
        )

    def press(self, key: Qt.Key) -> None:
        QTest.keyClick(self.window, key)

    def bars(self) -> list[float]:
        return [
            float(item.property("value"))
            for item in self._shown()
            if item.inherits("QQuickProgressBar")
        ]

    def _shown(self) -> list[QQuickItem]:
        # Layouts place what they show only when polished, before the next frame.
        for item in items(self.window.contentItem()):
            item.ensurePolished()
        return [item for item in items(self.window.contentItem()) if item.isVisible()]

    def _fetch(self) -> None:
        self.fetches += 1


@pytest.fixture
def screen(qtbot: QtBot, tmp_path: Path, dwm: list[tuple[object, ...]]) -> Iterator[Screen]:
    screen = Screen(qtbot, tmp_path / "models")
    yield screen
    screen.first_run.close()


def centred(window: QWindow) -> bool:
    area = QGuiApplication.primaryScreen().availableGeometry()
    frame = window.frameGeometry()
    return (frame.x(), frame.y()) == (
        area.x() + (area.width() - frame.width()) // 2,
        area.y() + (area.height() - frame.height()) // 2,
    )


def test_a_download_opens_the_window_centred_with_the_focus_and_three_steps(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.show(Stage.DOWNLOADING, int(0.8 * GIB))
    screen.opened()
    # It moves when Windows says it grew, after height() reads the new height.
    qtbot.waitUntil(lambda: centred(screen.window))
    assert screen.window.title() == "Benvenuto in Jiffin"
    assert screen.lines() == [
        *WAIT,
        "1",
        "Scarico il modello",
        "0,8 GB di 2,4 GB",
        *STEPS_AFTER_DOWNLOAD,
        MEANWHILE,
    ]
    assert screen.bars() == [pytest.approx(0.8 * GIB / SIZE)]


def test_the_window_is_a_card_on_the_alerts_glass(
    screen: Screen, dwm: list[tuple[object, ...]]
) -> None:
    flags = screen.window.flags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert not flags & Qt.WindowType.WindowDoesNotAcceptFocus
    hwnd = int(screen.window.winId())
    assert dwm == [("set_backdrop", hwnd, True, win32.DWMSBT_TRANSIENTWINDOW)]


def test_the_check_at_every_start_opens_nothing(screen: Screen) -> None:
    screen.show(Stage.CHECKING, SIZE // 2)
    screen.show(Stage.CHECKING, SIZE)
    screen.show(Stage.READY, SIZE)
    assert not screen.window.isVisible()


def test_the_steps_go_from_the_download_to_the_check_to_ready(screen: Screen) -> None:
    screen.show(Stage.DOWNLOADING, SIZE - 1)
    screen.opened()
    screen.show(Stage.CHECKING, SIZE // 4)
    assert screen.lines() == [*WAIT, "Scarico il modello", *STEPS_AFTER_DOWNLOAD, MEANWHILE]
    assert screen.bars() == [pytest.approx(0.25)]
    screen.show(Stage.READY, SIZE)
    assert screen.window.title() == "Jiffin è pronto"
    assert screen.lines() == [
        "Jiffin è pronto",
        "Premi Win+Maiusc+N, da qualsiasi app, per un nuovo promemoria.",
        (
            "L'icona di Jiffin nella barra apre l'elenco. Windows la mette sotto ^: trascinala "
            "sulla barra per vederla sempre."
        ),
    ]
    screen.click(TEXTS.first_run.start)
    assert not screen.window.isVisible()


def test_the_time_left_comes_from_the_downloads_pace(screen: Screen) -> None:
    screen.show(Stage.DOWNLOADING, 0)
    screen.clock.advance(4_000)
    screen.show(Stage.DOWNLOADING, SIZE // 20)
    assert "0,1 GB di 2,4 GB" in screen.lines()  # too soon to tell
    screen.clock.advance(6_000)
    screen.show(Stage.DOWNLOADING, SIZE // 10)
    # A tenth in 10 s: 90 s left.
    assert "0,2 GB di 2,4 GB · circa 2 min" in screen.lines()
    screen.clock.advance(60_000)
    screen.show(Stage.DOWNLOADING, SIZE * 9 // 10)
    assert "2,2 GB di 2,4 GB · meno di un minuto" in screen.lines()


@pytest.mark.parametrize("close", ["Esc", "the X"])
def test_closed_it_stays_closed_and_the_tray_lists_dettagli_opens_it(
    screen: Screen, close: str
) -> None:
    screen.show(Stage.DOWNLOADING, SIZE // 3)
    screen.opened()
    if close == "Esc":
        screen.press(Qt.Key.Key_Escape)
    else:
        screen.click_on(screen.x())
    assert not screen.window.isVisible()
    screen.show(Stage.DOWNLOADING, SIZE // 2)
    screen.show(Stage.NETWORK, SIZE // 2)
    assert not screen.window.isVisible()
    screen.first_run.open()
    screen.opened()
    assert "Il download si è fermato" in " ".join(screen.lines())


def test_the_window_drags_from_any_empty_point_but_not_from_its_controls(
    screen: Screen, drags: Callable[[QQuickWindow, QPoint], bool]
) -> None:
    screen.show(Stage.DOWNLOADING, SIZE // 3)
    screen.opened()
    window = screen.window
    assert drags(window, QPoint(8, window.height() - 8))
    for control in (screen.x(), screen.button(TEXTS.command.close)):
        middle = QPointF(control.width() / 2, control.height() / 2)
        assert not drags(window, control.mapToScene(middle).toPoint())


def test_the_window_opens_again_where_it_was_left_and_stays_there_as_it_grows(
    screen: Screen, qtbot: QtBot
) -> None:
    screen.show(Stage.DOWNLOADING, SIZE // 3)
    screen.opened()
    # Where the user drags it: the offscreen platform has no system move.
    screen.window.setFramePosition(QPoint(30, 40))
    screen.press(Qt.Key.Key_Escape)
    screen.first_run.open()
    screen.opened()
    assert screen.window.framePosition() == QPoint(30, 40)
    assert screen.placed == [{"first_run": (30, 40)}]
    screen.show(Stage.NETWORK, SIZE // 3)
    # Qt says the window grew from its window-system queue, where it would move a centred one.
    with qtbot.waitSignal(screen.window.heightChanged):
        screen.click(TEXTS.first_run.by_hand_offline)
    assert screen.window.framePosition() == QPoint(30, 40)


@pytest.mark.parametrize(
    ("stage", "missing", "message", "detail"),
    [
        (
            Stage.NETWORK,
            0,
            (
                "Il download si è fermato: controlla la connessione. Riprova riprende da dove "
                "era rimasto."
            ),
            "0,8 GB di 2,4 GB · fermo",
        ),
        (
            Stage.SPACE,
            3 * GIB // 2,
            "Il disco è pieno: libera altri 1,5 GB, poi riprova.",
            "0,8 GB di 2,4 GB · fermo",
        ),
        (
            Stage.SPACE,
            3 * GIB // 2 + 1,
            "Il disco è pieno: libera altri 1,6 GB, poi riprova.",
            "0,8 GB di 2,4 GB · fermo",
        ),
        (
            Stage.DISK,
            0,
            (
                "Non riesco a scrivere nella cartella dei modelli, o a leggerla. Controlla il "
                "disco, poi riprova."
            ),
            "0,8 GB di 2,4 GB · fermo",
        ),
    ],
)
def test_a_problem_with_the_download_opens_the_window_with_riprova(
    screen: Screen, stage: FirstRun.Stage, missing: int, message: str, detail: str
) -> None:
    screen.show(stage, int(0.8 * GIB), missing)
    screen.opened()
    lines = screen.lines()
    assert lines[: len(WAIT) + 3] == [*WAIT, "1", "Scarico il modello", detail]
    assert message in lines
    assert MEANWHILE not in lines
    screen.click(TEXTS.command.retry)
    assert screen.fetches == 1
    assert not screen.button(TEXTS.command.retrying).isEnabled()
    screen.show(Stage.DOWNLOADING, GIB)
    assert message not in screen.lines()
    assert screen.button(TEXTS.command.close).isEnabled()


def test_a_wrong_file_stops_the_check(screen: Screen) -> None:
    screen.show(Stage.CHECKING, SIZE)
    screen.show(Stage.MISMATCH, SIZE)
    screen.opened()
    message = (
        "Il file del modello non è quello giusto. Se l'hai messo tu, sostituiscilo o "
        "eliminalo; poi premi Riprova."
    )
    assert screen.lines() == [*WAIT, "Scarico il modello", *STEPS_AFTER_DOWNLOAD, message]
    screen.button(TEXTS.first_run.by_hand)


def test_a_disk_problem_in_the_check_stops_the_check(screen: Screen) -> None:
    screen.show(Stage.DOWNLOADING, SIZE)
    screen.show(Stage.CHECKING, SIZE // 2)
    screen.show(Stage.DISK)
    screen.opened()
    assert screen.lines()[: len(WAIT) + 3] == [
        *WAIT,
        "Scarico il modello",
        "2",
        "Controllo il file",
    ]


def test_by_hand_says_where_to_get_the_file_and_where_to_put_it(
    screen: Screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[QUrl] = []

    def open_url(url: QUrl) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    screen.show(Stage.NETWORK, SIZE // 3)
    screen.opened()
    steps = [
        "1. Scarica il file da questo indirizzo, anche da un altro PC:",
        URL,
        f"2. Mettilo nella cartella dei modelli, con il nome {NAME}:",
        str(screen.folder),
        (f"3. Premi Riprova: lo controllo. Deve pesare 2.600.224.416 byte, con sha256 {SHA256}."),
    ]
    assert steps[0] not in screen.lines()
    screen.click(TEXTS.first_run.by_hand_offline)
    assert screen.lines()[-len(steps) :] == steps
    screen.click(TEXTS.first_run.copy_address)
    assert QGuiApplication.clipboard().text() == URL
    screen.click(TEXTS.first_run.open_folder)
    assert screen.folder.is_dir()
    assert opened == [QUrl.fromLocalFile(str(screen.folder))]
    # Opened again, the window starts with the steps closed.
    screen.first_run.close()
    screen.first_run.open()
    screen.opened()
    assert steps[0] not in screen.lines()


def test_without_the_shortcut_the_window_says_where_to_write(screen: Screen) -> None:
    screen.first_run.shortcut = False
    screen.show(Stage.DOWNLOADING, SIZE // 3)
    screen.opened()
    assert screen.lines()[-1] == (
        "Intanto puoi già scrivere i promemoria: Nuovo, nell'elenco dell'icona di Jiffin."
    )
    screen.show(Stage.READY, SIZE)
    assert screen.lines()[1] == (
        "Win+Maiusc+N è già di un'altra app: un nuovo promemoria si scrive da Nuovo, nell'elenco."
    )


def test_the_first_run_goes_with_the_engine_and_no_binding_reads_it_gone(
    qtbot: QtBot, tmp_path: Path, dwm: list[tuple[object, ...]]
) -> None:
    """On quitting, Python lets go of the interface in any order: the first run stays until the
    engine goes, and then none of its window's bindings reads it gone (a warning fails)."""
    look = Look(lambda: DARK)
    engine = QQmlEngine()
    look.provide(engine)
    model = ModelFile(NAME, URL, SIZE, SHA256, tmp_path)
    first_run = FirstRun(
        engine, model, lambda: None, Glass(look), Places(lambda places: None), SimulatedClock(0)
    )
    first_run.show(ModelState(Stage.DOWNLOADING, SIZE // 3, SIZE))
    gone: list[str] = []
    first_run.destroyed.connect(lambda: gone.append("first run"))
    del first_run
    gc.collect()
    assert gone == []
    del engine
    gc.collect()
    assert gone == ["first run"]
