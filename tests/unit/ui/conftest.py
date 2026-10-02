"""The interface's tests run on Qt's offscreen platform: the windows lay out, animate and take
the mouse without showing on the screen. Any Qt warning fails a test (`qt_log_level_fail`)."""

import gc
import os
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication

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
def collected() -> None:
    """Earlier tests' engines go, with their windows, when the garbage collector runs: at any
    moment, even while a test reads `topLevelWindows()`, whose windows then raise "already
    deleted". Collected before each test, they go now."""
    gc.collect()


@pytest.fixture
def dwm(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """What the glass asks of DWM, recorded instead of done: (function, *arguments)."""
    calls: list[tuple[object, ...]] = []
    for name in ("set_backdrop", "recreate_backdrop", "activate_frame", "nudge"):
        monkeypatch.setattr(win32, name, lambda *args, name=name: calls.append((name, *args)))
    return calls
