"""A stand-in for the app the user types in, for the overlay's focus test (#31, ADR-0009) and
for the context of the app's whole loop (#44).

A maximized window with a text box, in a process of its own like any other app; its title is
the first argument, when given. It prints its window handle and its text box's, then keeps the
focus in the box until it gets WM_CLOSE. Standard library only, so that it shares no code with
the app.
"""

import ctypes
import sys
from ctypes import POINTER, wintypes
from typing import Any

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
    "SetProcessDpiAwarenessContext": (wintypes.BOOL, [ctypes.c_void_p]),
    "RegisterClassW": (wintypes.ATOM, [POINTER(_WindowClass)]),
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
    "DefWindowProcW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "LoadCursorW": (wintypes.HANDLE, [wintypes.HINSTANCE, ctypes.c_void_p]),
    "ShowWindow": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
    "SetFocus": (wintypes.HWND, [wintypes.HWND]),
    "MoveWindow": (
        wintypes.BOOL,
        [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL],
    ),
    "GetMessageW": (
        wintypes.BOOL,
        [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT],
    ),
    "TranslateMessage": (wintypes.BOOL, [POINTER(wintypes.MSG)]),
    "DispatchMessageW": (wintypes.LPARAM, [POINTER(wintypes.MSG)]),
    "PostQuitMessage": (None, [ctypes.c_int]),
}
_KERNEL32: dict[str, tuple[Any, list[Any]]] = {
    "GetModuleHandleW": (wintypes.HMODULE, [wintypes.LPCWSTR]),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for _library, _signatures in ((_user32, _USER32), (_kernel32, _KERNEL32)):
    for _name, (_result, _arguments) in _signatures.items():
        _function = getattr(_library, _name)
        _function.restype, _function.argtypes = _result, _arguments

_WM_DESTROY, _WM_SIZE, _WM_SETFOCUS = 0x0002, 0x0005, 0x0007
_WS_OVERLAPPEDWINDOW, _WS_CHILD, _WS_VISIBLE = 0x00CF0000, 0x40000000, 0x10000000
_ES_MULTILINE, _ES_AUTOVSCROLL, _WS_EX_CLIENTEDGE = 0x0004, 0x0040, 0x00000200
_CW_USEDEFAULT, _SW_MAXIMIZE, _COLOR_WINDOW, _IDC_ARROW = -0x80000000, 3, 5, 32512
_PER_MONITOR_AWARE_V2 = -4
"""Physical pixels, as the test reads them."""
_CLASS = "JiffinTargetWindow"

box = 0
"""The text box, once made."""


def _procedure(hwnd: int, message: int, wparam: int, lparam: int) -> int:
    if message == _WM_SIZE and box:
        # In the lower half of the window, away from the alerts at the top of the screen.
        width, height = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
        _user32.MoveWindow(box, width // 8, height // 2, width * 3 // 4, height // 3, True)
        return 0
    if message == _WM_SETFOCUS and box:
        _user32.SetFocus(box)
        return 0
    if message == _WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    result: int = _user32.DefWindowProcW(hwnd, message, wparam, lparam)
    return result


_callback = _WindowProc(_procedure)  # alive as long as Windows may call it


def main() -> None:
    global box
    _user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
    instance = _kernel32.GetModuleHandleW(None)
    window_class = _WindowClass(
        lpfnWndProc=_callback,
        hInstance=instance,
        hCursor=_user32.LoadCursorW(None, _IDC_ARROW),
        hbrBackground=_COLOR_WINDOW + 1,
        lpszClassName=_CLASS,
    )
    _user32.RegisterClassW(ctypes.byref(window_class))
    window = _user32.CreateWindowExW(
        0,
        _CLASS,
        sys.argv[1] if len(sys.argv) > 1 else "Jiffin: finestra della prova dell'avviso",
        _WS_OVERLAPPEDWINDOW,
        _CW_USEDEFAULT,
        _CW_USEDEFAULT,
        1200,
        800,
        None,
        None,
        instance,
        None,
    )
    box = _user32.CreateWindowExW(
        _WS_EX_CLIENTEDGE,
        "EDIT",
        "",
        _WS_CHILD | _WS_VISIBLE | _ES_MULTILINE | _ES_AUTOVSCROLL,
        0,
        0,
        0,
        0,
        window,
        None,
        instance,
        None,
    )
    _user32.ShowWindow(window, _SW_MAXIMIZE)
    _user32.SetFocus(box)
    print(window, box, flush=True)
    message = wintypes.MSG()
    while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        _user32.TranslateMessage(ctypes.byref(message))
        _user32.DispatchMessageW(ctypes.byref(message))


if __name__ == "__main__":
    main()
