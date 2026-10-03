"""Win32 against Windows itself, on windows that never show."""

import ctypes
import threading
from collections.abc import Iterator
from ctypes import wintypes
from typing import Any

import pytest

from jiffin.platform import win32

_WindowProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WindowClass(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WindowProc),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


# name -> (result, arguments)
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
    "RegisterClassW": (wintypes.ATOM, [ctypes.POINTER(_WindowClass)]),
    "UnregisterClassW": (wintypes.BOOL, [wintypes.LPCWSTR, wintypes.HINSTANCE]),
    "CreateWindowExW": (
        wintypes.HWND,
        [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ],
    ),
    "DestroyWindow": (wintypes.BOOL, [wintypes.HWND]),
    "SetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]),
    "DefWindowProcW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "FindWindowExW": (
        wintypes.HWND,
        [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR],
    ),
    "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, wintypes.LPVOID]),
    "SendMessageW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
}
_user32 = ctypes.WinDLL("user32", use_last_error=True)
for _name, (_result, _arguments) in _USER32.items():
    _function = getattr(_user32, _name)
    _function.restype, _function.argtypes = _result, _arguments

_SM_CXSCREEN, _SM_CYSCREEN = 0, 1
_GWL_STYLE, _GWL_EXSTYLE = -16, -20
_WS_POPUP, _WS_CAPTION, _WS_THICKFRAME = 0x80000000, 0x00C00000, 0x00040000
_WS_SYSMENU, _WS_MINIMIZEBOX, _WS_MAXIMIZEBOX = 0x00080000, 0x00020000, 0x00010000
_WS_EX_TOOLWINDOW = 0x00000080
_HWND_MESSAGE = -3
_WM_POWERBROADCAST, _WM_WTSSESSION_CHANGE = 0x0218, 0x02B1
_WTS_CONSOLE_CONNECT, _WTS_SESSION_LOCK, _WTS_SESSION_UNLOCK = 0x1, 0x7, 0x8
_PBT_APMSUSPEND, _PBT_APMRESUMESUSPEND, _PBT_APMRESUMEAUTOMATIC = 0x4, 0x7, 0x12
_TASK_VIEW = "MultitaskingViewFrame"
"""A class of the shell's, registered here for a window of the test's own."""

_procedure = _WindowProc(lambda *message: _user32.DefWindowProcW(*message))


@pytest.fixture(scope="module")
def task_view_class() -> Iterator[str]:
    kind = _WindowClass(lpfnWndProc=_procedure, lpszClassName=_TASK_VIEW)
    assert _user32.RegisterClassW(ctypes.byref(kind))
    yield _TASK_VIEW
    _user32.UnregisterClassW(_TASK_VIEW, None)


def screen() -> tuple[int, int]:
    """The primary monitor's size; it starts at (0, 0)."""
    return _user32.GetSystemMetrics(_SM_CXSCREEN), _user32.GetSystemMetrics(_SM_CYSCREEN)


def full_screen(style: int, extended: int = 0, grow: int = 0, kind: str = "Static") -> bool:
    """Whether a window that never shows, over the primary monitor and `grow` pixels more on
    each side, with these styles, is in full screen."""
    width, height = screen()
    hwnd = _user32.CreateWindowExW(
        extended,
        kind,
        "",
        style,
        -grow,
        -grow,
        width + 2 * grow,
        height + 2 * grow,
        None,
        None,
        None,
        None,
    )
    assert hwnd, ctypes.WinError(ctypes.get_last_error())
    try:
        # Windows gives an overlapped window a caption: the styles are set again, as Chromium
        # does when it goes to full screen.
        _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style)
        _user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, extended)
        return win32.full_screen(hwnd)
    finally:
        _user32.DestroyWindow(hwnd)


def test_a_window_without_a_frame_over_its_whole_monitor_is_in_full_screen() -> None:
    assert full_screen(_WS_POPUP)  # a game, a slide show
    # Chromium's video and F11: caption and sizing frame taken away, the boxes kept.
    assert full_screen(_WS_SYSMENU | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX)
    assert full_screen(_WS_POPUP, grow=8)


def test_a_window_one_pixel_short_of_its_monitor_is_not_in_full_screen() -> None:
    assert not full_screen(_WS_POPUP, grow=-1)


@pytest.mark.parametrize(
    ("style", "extended"),
    [(_WS_POPUP | _WS_CAPTION, 0), (_WS_POPUP | _WS_THICKFRAME, 0), (_WS_POPUP, _WS_EX_TOOLWINDOW)],
    ids=["caption", "sizing frame", "tool window, as the desktop"],
)
def test_a_window_with_a_frame_over_its_monitor_is_not_in_full_screen(
    style: int, extended: int
) -> None:
    """A maximized window overhangs its monitor when the taskbar hides, with its frame."""
    assert not full_screen(style, extended, grow=8)


def test_a_window_of_the_shell_over_its_monitor_is_not_in_full_screen(
    task_view_class: str,
) -> None:
    assert not full_screen(_WS_POPUP, kind=task_view_class)


def own_message_window() -> int:
    """The message-only window of the calling thread."""
    thread = threading.get_native_id()
    window = None
    while window := _user32.FindWindowExW(_HWND_MESSAGE, window, None, None):
        if _user32.GetWindowThreadProcessId(window, None) == thread:
            return int(window)
    raise AssertionError("no message-only window on this thread")


def test_the_notices_of_a_lock_and_of_sleep_reach_the_handler() -> None:
    """Windows' messages, sent as Windows would, on a thread whose only message-only window is the
    notices'."""
    seen: list[win32.Notice] = []

    def run() -> None:
        notices = win32.Notices(seen.append)
        try:
            window = own_message_window()
            for message, kind in (
                (_WM_WTSSESSION_CHANGE, _WTS_CONSOLE_CONNECT),
                # It follows the automatic one when the user wakes the PC: no notice of its own.
                (_WM_POWERBROADCAST, _PBT_APMRESUMESUSPEND),
                (_WM_WTSSESSION_CHANGE, _WTS_SESSION_LOCK),
                (_WM_POWERBROADCAST, _PBT_APMSUSPEND),
                (_WM_POWERBROADCAST, _PBT_APMRESUMEAUTOMATIC),
                (_WM_WTSSESSION_CHANGE, _WTS_SESSION_UNLOCK),
            ):
                _user32.SendMessageW(window, message, kind, 0)
        finally:
            notices.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert seen == [
        win32.Notice.LOCKED,
        win32.Notice.SLEEPING,
        win32.Notice.AWAKE,
        win32.Notice.UNLOCKED,
    ]


def test_notices_closed_on_one_thread_can_be_made_again() -> None:
    for _ in range(2):
        win32.Notices(lambda notice: None).close()


def test_a_title_cut_inside_an_emoji_can_still_reach_the_engine() -> None:
    cut = "Piano \U0001f5d3"[:-1] + "\ud83d"  # the first half of a surrogate pair
    assert win32.clean(cut) == "Piano �"
    assert win32.clean(cut).encode()
    assert win32.clean("Piano \U0001f5d3 fatto") == "Piano \U0001f5d3 fatto"
