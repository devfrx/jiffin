"""Win32 for the app: one Jiffin at a time, and a message from Windows itself when it cannot
start.

Signatures are transcribed from the Windows SDK headers `synchapi.h` and `winuser.h`.
"""

import ctypes
from ctypes import wintypes
from typing import Any

_ERROR_ALREADY_EXISTS = 183
_MB_ICONERROR = 0x00000010

_KERNEL32: dict[str, tuple[Any, list[Any]]] = {
    "CreateMutexW": (wintypes.HANDLE, [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]),
}
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "MessageBoxW": (
        ctypes.c_int,
        [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT],
    ),
}

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
for _library, _signatures in ((_kernel32, _KERNEL32), (_user32, _USER32)):
    for _name, (_result, _arguments) in _signatures.items():
        _function = getattr(_library, _name)
        _function.restype, _function.argtypes = _result, _arguments


def first_instance(name: str) -> bool:
    """Whether this process is the first in the session to hold the mutex `name`. It holds it
    until it ends: the handle is never closed."""
    ctypes.set_last_error(0)
    if not _kernel32.CreateMutexW(None, False, name):
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.get_last_error() != _ERROR_ALREADY_EXISTS


def show_error(text: str) -> None:
    """Windows' own message box, with the error icon; it returns once the user closes it."""
    _user32.MessageBoxW(None, text, "Jiffin", _MB_ICONERROR)
