"""Win32 without Qt: the foreground window, its program and title, whether it is in full screen,
WinEvent hooks (ADR-0005), and Windows' notices of the session and the power (ADR-0021).

Nothing here needs a permission. Signatures are transcribed from the Windows SDK headers
`winuser.h`, `processthreadsapi.h`, `winbase.h`, `libloaderapi.h` and `wtsapi32.h`.
"""

import ctypes
from collections.abc import Callable
from ctypes import POINTER, wintypes
from enum import Enum, auto
from pathlib import PureWindowsPath
from typing import Any

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C
OBJID_WINDOW = 0
CHILDID_SELF = 0
_WINEVENT_OUTOFCONTEXT = 0x0000
_WM_QUIT = 0x0012
_WM_POWERBROADCAST = 0x0218
_WM_WTSSESSION_CHANGE = 0x02B1
_WTS_SESSION_LOCK, _WTS_SESSION_UNLOCK = 0x7, 0x8
_PBT_APMSUSPEND, _PBT_APMRESUMEAUTOMATIC = 0x0004, 0x0012
_NOTIFY_FOR_THIS_SESSION = 0
_DEVICE_NOTIFY_WINDOW_HANDLE = 0
_HWND_MESSAGE = -3
_PM_NOREMOVE = 0x0000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MONITOR_DEFAULTTONEAREST = 0x00000002
_GWL_STYLE, _GWL_EXSTYLE = -16, -20
_WS_DLGFRAME, _WS_THICKFRAME = 0x00400000, 0x00040000
_WS_EX_TOOLWINDOW = 0x00000080
_PATH_CHARS = 32_768
_CLASS_CHARS = 256
_FRAME_HOST = "applicationframehost.exe"
_UWP_CORE_WINDOW = "Windows.UI.Core."
"""The class prefix of the window a UWP app draws in, inside ApplicationFrameHost's frame."""
_SHELL_WINDOWS = frozenset(
    name.lower()
    for name in (
        "Progman",
        "WorkerW",
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "ImmersiveLauncher",
        "ImmersiveSwitchList",
        "MultitaskingViewFrame",
        "ForegroundStaging",
        "ApplicationManager_DesktopShellWindow",
        "XamlExplorerHostIslandWindow",
    )
)
"""The classes of the desktop's and the shell's windows, which may cover a monitor as part of the
screen: LightBulb's list (`LightBulb.PlatformInterop/Window.cs`)."""

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
_WindowProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)
_Message = POINTER(wintypes.MSG)


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


class _MonitorInfo(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    )


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
    "GetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int]),
    "MonitorFromWindow": (wintypes.HMONITOR, [wintypes.HWND, wintypes.DWORD]),
    "GetMonitorInfoW": (wintypes.BOOL, [wintypes.HMONITOR, POINTER(_MonitorInfo)]),
    "RegisterClassW": (wintypes.ATOM, [POINTER(_WindowClass)]),
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
    "DefWindowProcW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "RegisterSuspendResumeNotification": (wintypes.HANDLE, [wintypes.HANDLE, wintypes.DWORD]),
    "UnregisterSuspendResumeNotification": (wintypes.BOOL, [wintypes.HANDLE]),
}
_KERNEL32: dict[str, tuple[Any, list[Any]]] = {
    "OpenProcess": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
    "QueryFullProcessImageNameW": (
        wintypes.BOOL,
        [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, POINTER(wintypes.DWORD)],
    ),
    "CloseHandle": (wintypes.BOOL, [wintypes.HANDLE]),
    "GetModuleHandleW": (wintypes.HMODULE, [wintypes.LPCWSTR]),
}
_WTSAPI32: dict[str, tuple[Any, list[Any]]] = {
    "WTSRegisterSessionNotification": (wintypes.BOOL, [wintypes.HWND, wintypes.DWORD]),
    "WTSUnRegisterSessionNotification": (wintypes.BOOL, [wintypes.HWND]),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
for _library, _signatures in (
    (_user32, _USER32),
    (_kernel32, _KERNEL32),
    (_wtsapi32, _WTSAPI32),
):
    for _name, (_result, _arguments) in _signatures.items():
        _function = getattr(_library, _name)
        _function.restype, _function.argtypes = _result, _arguments
_instance = _kernel32.GetModuleHandleW(None)


class Hook:
    """A WinEvent hook, out of context, on `event`, or on the events from `event` to `last`:
    Windows calls `handler(event, hwnd, object, child)` on the thread that set it, from inside
    that thread's message loop."""

    def __init__(
        self,
        event: int,
        handler: Callable[[int, int | None, int, int], None],
        process: int = 0,
        last: int | None = None,
    ) -> None:
        # ctypes frees a callback nobody references: it lives as long as the hook.
        self._callback = _WinEventProc(
            lambda _hook, event, hwnd, id_object, id_child, _thread, _time: handler(
                event, hwnd, id_object, id_child
            )
        )
        handle = _user32.SetWinEventHook(
            event,
            event if last is None else last,
            None,
            self._callback,
            process,
            0,
            _WINEVENT_OUTOFCONTEXT,
        )
        if not handle:  # it sets no last error
            raise OSError(f"SetWinEventHook refused the event {event:#06x}")
        self._handle: int | None = handle

    def close(self) -> None:
        if self._handle is not None:
            _user32.UnhookWinEvent(self._handle)
            self._handle = None


class Notice(Enum):
    """What Windows tells of the session and the power."""

    LOCKED = auto()
    UNLOCKED = auto()
    SLEEPING = auto()
    """The PC is about to sleep or hibernate: Windows waits about two seconds for the apps."""
    AWAKE = auto()
    """The PC woke, with the user or for a task of its own: Windows says so at every wake."""


_SESSION_NOTICES = {_WTS_SESSION_LOCK: Notice.LOCKED, _WTS_SESSION_UNLOCK: Notice.UNLOCKED}
_POWER_NOTICES = {_PBT_APMSUSPEND: Notice.SLEEPING, _PBT_APMRESUMEAUTOMATIC: Notice.AWAKE}


class Notices:
    """Windows' notices of the session and the power, to a message-only window of the thread that
    makes it: Windows calls `handler(notice)` there, from inside its message loop. `close` it on
    the same thread."""

    def __init__(self, handler: Callable[[Notice], None]) -> None:
        self._handler = handler
        # ctypes frees a callback nobody references: it lives as long as the window.
        self._procedure = _WindowProc(self._receive)
        self._name = f"Jiffin.Notices.{id(self):x}"
        self._registered = False
        self._window: int | None = None
        self._power: int | None = None
        try:
            kind = _WindowClass(
                lpfnWndProc=self._procedure, hInstance=_instance, lpszClassName=self._name
            )
            self._registered = bool(_user32.RegisterClassW(ctypes.byref(kind)))
            if not self._registered:
                raise ctypes.WinError(ctypes.get_last_error())
            self._window = _user32.CreateWindowExW(
                0, self._name, None, 0, 0, 0, 0, 0, _HWND_MESSAGE, None, _instance, None
            )
            if not self._window:
                raise ctypes.WinError(ctypes.get_last_error())
            if not _wtsapi32.WTSRegisterSessionNotification(self._window, _NOTIFY_FOR_THIS_SESSION):
                raise ctypes.WinError(ctypes.get_last_error())
            self._power = _user32.RegisterSuspendResumeNotification(
                self._window, _DEVICE_NOTIFY_WINDOW_HANDLE
            )
            if not self._power:
                raise ctypes.WinError(ctypes.get_last_error())
        except OSError:
            self.close()
            raise

    def close(self) -> None:
        if self._power is not None:
            _user32.UnregisterSuspendResumeNotification(self._power)
            self._power = None
        if self._window is not None:
            _wtsapi32.WTSUnRegisterSessionNotification(self._window)
            _user32.DestroyWindow(self._window)
            self._window = None
        if self._registered:
            _user32.UnregisterClassW(self._name, _instance)
            self._registered = False

    def _receive(self, hwnd: int, message: int, wparam: int, lparam: int) -> int:
        if message == _WM_WTSSESSION_CHANGE and wparam in _SESSION_NOTICES:
            self._handler(_SESSION_NOTICES[wparam])
        elif message == _WM_POWERBROADCAST and wparam in _POWER_NOTICES:
            self._handler(_POWER_NOTICES[wparam])
        result: int = _user32.DefWindowProcW(hwnd, message, wparam, lparam)
        return result


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


def full_screen(hwnd: int) -> bool:
    """Whether a window covers its whole monitor without a frame, as a video, F11, a slide show or
    a game do (ADR-0024). A maximized window keeps its frame, and the desktop and the shell's
    windows cover a monitor as part of the screen: Chromium tells them apart by the same
    rectangle and styles, LightBulb by the same classes of the shell. Chromium also looks at
    the raised edge, which Windows gives a window with a caption or a sizing frame, and only
    then: those two tell it."""
    rect = window_rect(hwnd)
    info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
    monitor = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if rect is None or not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    screen = info.rcMonitor
    left, top, right, bottom = rect
    if left > screen.left or top > screen.top or right < screen.right or bottom < screen.bottom:
        return False
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    extended = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
    if style & (_WS_DLGFRAME | _WS_THICKFRAME) or extended & _WS_EX_TOOLWINDOW:
        return False
    return _class_name(hwnd).lower() not in _SHELL_WINDOWS


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
        pid = process_id(child)
        if _class_name(child).startswith(_UWP_CORE_WINDOW) and pid != frame_pid:
            found.append(pid)
            return False
        return True

    _user32.EnumChildWindows(frame, _EnumChildProc(visit), 0)
    return found[0] if found else None


def _class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(_CLASS_CHARS)
    _user32.GetClassNameW(hwnd, buffer, _CLASS_CHARS)
    return buffer.value
