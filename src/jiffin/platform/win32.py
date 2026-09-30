"""Win32 without Qt: the foreground window, its program and title, and WinEvent hooks (ADR-0005).

Nothing here needs a permission. Signatures are transcribed from the Windows SDK headers
`winuser.h`, `processthreadsapi.h` and `winbase.h`.
"""

import ctypes
from collections.abc import Callable
from ctypes import POINTER, wintypes
from pathlib import PureWindowsPath
from typing import Any

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_NAMECHANGE = 0x800C
OBJID_WINDOW = 0
CHILDID_SELF = 0
_WINEVENT_OUTOFCONTEXT = 0x0000
_WM_QUIT = 0x0012
_PM_NOREMOVE = 0x0000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PATH_CHARS = 32_768
_CLASS_CHARS = 256
_FRAME_HOST = "applicationframehost.exe"
_UWP_CORE_WINDOW = "Windows.UI.Core."
"""The class prefix of the window a UWP app draws in, inside ApplicationFrameHost's frame."""

_WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
_EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_Message = POINTER(wintypes.MSG)

# name -> (result, arguments)
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "SetWinEventHook": (
        wintypes.HANDLE,
        [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HMODULE,
            _WinEventProc,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ],
    ),
    "UnhookWinEvent": (wintypes.BOOL, [wintypes.HANDLE]),
    "GetMessageW": (wintypes.BOOL, [_Message, wintypes.HWND, wintypes.UINT, wintypes.UINT]),
    "PeekMessageW": (
        wintypes.BOOL,
        [_Message, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT],
    ),
    "TranslateMessage": (wintypes.BOOL, [_Message]),
    "DispatchMessageW": (wintypes.LPARAM, [_Message]),
    "PostThreadMessageW": (
        wintypes.BOOL,
        [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "GetForegroundWindow": (wintypes.HWND, []),
    "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, POINTER(wintypes.DWORD)]),
    "GetWindowTextLengthW": (ctypes.c_int, [wintypes.HWND]),
    "GetWindowTextW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    "EnumChildWindows": (wintypes.BOOL, [wintypes.HWND, _EnumChildProc, wintypes.LPARAM]),
    "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, POINTER(wintypes.RECT)]),
    "IsWindow": (wintypes.BOOL, [wintypes.HWND]),
}
_KERNEL32: dict[str, tuple[Any, list[Any]]] = {
    "OpenProcess": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
    "QueryFullProcessImageNameW": (
        wintypes.BOOL,
        [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, POINTER(wintypes.DWORD)],
    ),
    "CloseHandle": (wintypes.BOOL, [wintypes.HANDLE]),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for _library, _signatures in ((_user32, _USER32), (_kernel32, _KERNEL32)):
    for _name, (_result, _arguments) in _signatures.items():
        _function = getattr(_library, _name)
        _function.restype, _function.argtypes = _result, _arguments


class Hook:
    """A WinEvent hook, out of context: Windows calls `handler(event, hwnd, object, child)` on the
    thread that set it, from inside that thread's message loop."""

    def __init__(
        self,
        event: int,
        handler: Callable[[int, int | None, int, int], None],
        process: int = 0,
    ) -> None:
        # ctypes frees a callback nobody references: it lives as long as the hook.
        self._callback = _WinEventProc(
            lambda _hook, event, hwnd, id_object, id_child, _thread, _time: handler(
                event, hwnd, id_object, id_child
            )
        )
        handle = _user32.SetWinEventHook(
            event, event, None, self._callback, process, 0, _WINEVENT_OUTOFCONTEXT
        )
        if not handle:  # it sets no last error
            raise OSError(f"SetWinEventHook refused the event {event:#06x}")
        self._handle: int | None = handle

    def close(self) -> None:
        if self._handle is not None:
            _user32.UnhookWinEvent(self._handle)
            self._handle = None


def make_queue() -> None:
    """Give the calling thread its message queue now, so that `post_quit` reaches it."""
    message = wintypes.MSG()
    _user32.PeekMessageW(ctypes.byref(message), None, 0, 0, _PM_NOREMOVE)


def run_messages() -> None:
    """Run the calling thread's message loop, and the hooks' handlers with it, until WM_QUIT."""
    message = wintypes.MSG()
    while result := _user32.GetMessageW(ctypes.byref(message), None, 0, 0):
        if result == -1:
            raise ctypes.WinError(ctypes.get_last_error())
        _user32.TranslateMessage(ctypes.byref(message))
        _user32.DispatchMessageW(ctypes.byref(message))


def post_quit(thread: int) -> None:
    """End the message loop of another thread, given its native id."""
    if not _user32.PostThreadMessageW(thread, _WM_QUIT, 0, 0):
        raise ctypes.WinError(ctypes.get_last_error())


def foreground() -> int | None:
    """The window in the foreground; None when there is none, as while the screen is locked."""
    hwnd: int | None = _user32.GetForegroundWindow()
    return hwnd


def process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return clean(buffer.value)


def clean(text: str) -> str:
    """Turn each lone surrogate into U+FFFD.

    A title is UTF-16 and can end halfway through an emoji; the half left over could not be
    encoded as UTF-8, and the engine would never see the request.
    """
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def program(hwnd: int) -> str | None:
    """The file name of the program behind the window, as `vivaldi.exe`; None when unknown.

    A UWP app draws inside a frame of ApplicationFrameHost: the name is the app's own.
    """
    pid = process_id(hwnd)
    path = _image(pid)
    if path is not None and PureWindowsPath(path).name.lower() == _FRAME_HOST:
        hosted = _hosted_process(hwnd, pid)
        if hosted is not None:
            path = _image(hosted) or path
    return None if path is None else PureWindowsPath(path).name


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Left, top, right and bottom, in screen coordinates."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def is_window(hwnd: int) -> bool:
    return bool(_user32.IsWindow(hwnd))


def _image(pid: int) -> str | None:
    """The executable of a process; None when it cannot be opened, as for protected ones."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(_PATH_CHARS)
        size = wintypes.DWORD(_PATH_CHARS)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def _hosted_process(frame: int, frame_pid: int) -> int | None:
    """The process of the UWP app in an ApplicationFrameHost frame."""
    found: list[int] = []

    def visit(child: int, _: int) -> bool:
        buffer = ctypes.create_unicode_buffer(_CLASS_CHARS)
        _user32.GetClassNameW(child, buffer, _CLASS_CHARS)
        pid = process_id(child)
        if buffer.value.startswith(_UWP_CORE_WINDOW) and pid != frame_pid:
            found.append(pid)
            return False
        return True

    _user32.EnumChildWindows(frame, _EnumChildProc(visit), 0)
    return found[0] if found else None
