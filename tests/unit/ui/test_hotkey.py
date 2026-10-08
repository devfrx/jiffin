import ctypes
import logging
from collections.abc import Iterator
from ctypes import wintypes

import pytest
from PySide6.QtGui import QGuiApplication
from pytestqt.qtbot import QtBot

from jiffin.ui import win32
from jiffin.ui.hotkey import HERE, MODIFIERS, NEW, Hotkeys

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
    """What the shortcuts ask of Windows, recorded instead of done, and what Windows answers."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error: dict[int, int] = {}
        """By key; 0 for the others."""

    def register(self, hotkey_id: int, modifiers: int, key: int) -> int:
        self.calls.append(("register", hotkey_id, modifiers, key))
        return self.error.get(key, 0)

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
    """The two shortcuts, installed on the interface thread; each press is recorded."""
    pressed: list[str] = []
    hotkeys = Hotkeys({NEW: lambda: pressed.append("new"), HERE: lambda: pressed.append("here")})
    qapp.installNativeEventFilter(hotkeys)
    hotkeys.register()
    yield pressed
    qapp.removeNativeEventFilter(hotkeys)


def post(wparam: int) -> None:
    """A WM_HOTKEY to this thread, as Windows posts it when the keys are pressed."""
    thread = _kernel32.GetCurrentThreadId()
    assert _user32.PostThreadMessageW(thread, win32.WM_HOTKEY, wparam, 0)


def test_the_shortcuts_are_win_shift_n_and_win_shift_q(keys: Keys) -> None:
    hotkeys = Hotkeys({NEW: lambda: None, HERE: lambda: None})
    hotkeys.register()
    assert hotkeys.registered == {NEW, HERE}
    win_shift = win32.MOD_WIN | win32.MOD_SHIFT
    assert keys.calls == [
        ("register", ord("N"), win_shift, ord("N")),
        ("register", ord("Q"), win_shift, ord("Q")),
    ]
    assert MODIFIERS == win_shift
    hotkeys.close()
    assert keys.calls[2:] == [("unregister", ord("N")), ("unregister", ord("Q"))]
    assert not hotkeys.registered


def test_a_shortcut_another_app_holds_is_reported_and_the_other_works(
    keys: Keys, caplog: pytest.LogCaptureFixture
) -> None:
    keys.error = {HERE: TAKEN}
    hotkeys = Hotkeys({NEW: lambda: None, HERE: lambda: None})
    with caplog.at_level(logging.WARNING):
        hotkeys.register()
    assert hotkeys.registered == {NEW}
    assert "Win+Shift+Q" in caplog.text
    assert "1409" in caplog.text
    hotkeys.close()
    assert keys.calls[2:] == [("unregister", NEW)]


def test_each_press_calls_its_function_on_the_interface_thread(
    qtbot: QtBot, presses: list[str]
) -> None:
    post(NEW)
    qtbot.waitUntil(lambda: presses == ["new"])
    post(HERE)
    qtbot.waitUntil(lambda: presses == ["new", "here"])
    post(HERE)
    qtbot.waitUntil(lambda: presses == ["new", "here", "here"])


def test_another_shortcut_of_the_thread_is_not_ours(qtbot: QtBot, presses: list[str]) -> None:
    post(1)
    post(NEW)
    qtbot.waitUntil(lambda: presses == ["new"])
    qtbot.wait(100)
    assert presses == ["new"]
