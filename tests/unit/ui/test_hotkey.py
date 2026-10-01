import ctypes
import logging
from collections.abc import Iterator
from ctypes import wintypes

import pytest
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from jiffin.ui import win32
from jiffin.ui.hotkey import KEY, MODIFIERS, Hotkey

_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
_user32.PostThreadMessageW.restype = wintypes.BOOL
TAKEN = 1409
"""ERROR_HOTKEY_ALREADY_REGISTERED."""


class Keys:
    """What the hotkey asks of Windows, recorded instead of done, and what Windows answers."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error = 0

    def register(self, hotkey_id: int, modifiers: int, key: int) -> int:
        self.calls.append(("register", hotkey_id, modifiers, key))
        return self.error

    def unregister(self, hotkey_id: int) -> None:
        self.calls.append(("unregister", hotkey_id))


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> Keys:
    keys = Keys()
    monkeypatch.setattr(win32, "register_hotkey", keys.register)
    monkeypatch.setattr(win32, "unregister_hotkey", keys.unregister)
    return keys


@pytest.fixture
def presses(qapp: QGuiApplication, keys: Keys) -> Iterator[list[str]]:
    """The shortcut, installed on the interface thread; each press is recorded."""
    pressed: list[str] = []
    hotkey = Hotkey(lambda: pressed.append("pressed"))
    qapp.installNativeEventFilter(hotkey)
    hotkey.register()
    yield pressed
    qapp.removeNativeEventFilter(hotkey)


def post(wparam: int) -> None:
    """A WM_HOTKEY to this thread, as Windows posts it when the keys are pressed."""
    thread = _kernel32.GetCurrentThreadId()
    assert _user32.PostThreadMessageW(thread, win32.WM_HOTKEY, wparam, 0)


def test_the_shortcut_is_win_shift_n(keys: Keys) -> None:
    hotkey = Hotkey(lambda: None)
    hotkey.register()
    assert hotkey.registered
    assert keys.calls == [("register", 1, win32.MOD_WIN | win32.MOD_SHIFT, ord("N"))]
    assert (MODIFIERS, KEY) == (win32.MOD_WIN | win32.MOD_SHIFT, ord("N"))
    hotkey.close()
    assert keys.calls[1:] == [("unregister", 1)]
    assert not hotkey.registered


def test_a_shortcut_another_app_holds_is_reported(
    keys: Keys, caplog: pytest.LogCaptureFixture
) -> None:
    keys.error = TAKEN
    hotkey = Hotkey(lambda: None)
    with caplog.at_level(logging.WARNING):
        hotkey.register()
    assert not hotkey.registered
    assert "1409" in caplog.text
    hotkey.close()
    assert keys.calls == [("register", 1, MODIFIERS, KEY)]


def test_each_press_calls_back_on_the_interface_thread(qtbot: QtBot, presses: list[str]) -> None:
    post(1)
    qtbot.waitUntil(lambda: presses == ["pressed"])
    post(1)
    qtbot.waitUntil(lambda: presses == ["pressed", "pressed"])


def test_another_shortcut_of_the_thread_is_not_ours(qtbot: QtBot, presses: list[str]) -> None:
    post(2)
    post(1)
    qtbot.waitUntil(lambda: presses == ["pressed"])
    qtbot.wait(100)
    assert presses == ["pressed"]
