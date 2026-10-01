"""Win32 for the interface: the glass under a window that is never active, the Windows settings
Qt does not expose (ADR-0010), and the global shortcut, which Qt does not have (#43).

Signatures are transcribed from the Windows SDK headers `winuser.h`, `wingdi.h` and `dwmapi.h`.
"""

import ctypes
import winreg
from ctypes import POINTER, wintypes
from typing import Any

WM_ERASEBKGND = 0x0014
WM_SETTINGCHANGE = 0x001A
WM_NCCALCSIZE = 0x0083
WM_NCACTIVATE = 0x0086
WM_THEMECHANGED = 0x031A
WM_HOTKEY = 0x0312
WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320
SPI_SETCLIENTAREAANIMATION = 0x1043
"""The wParam of the WM_SETTINGCHANGE that Windows' animation effects changed."""

MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000

DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
"""Mica."""
DWMSBT_TRANSIENTWINDOW = 3
"""Desktop Acrylic."""
DWMSBT_TABBEDWINDOW = 4
"""Mica Alt."""

_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOZORDER, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
_SWP_FRAMECHANGED = 0x0020
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWCP_ROUND = 2
_BLACK_BRUSH = 4
_SPI_GETCLIENTAREAANIMATION = 0x1042
_PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


class _Margins(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    )


# name -> (result, arguments)
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "GetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int]),
    "SetWindowLongPtrW": (ctypes.c_ssize_t, [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]),
    "SetWindowPos": (
        wintypes.BOOL,
        [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ],
    ),
    "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, POINTER(wintypes.RECT)]),
    "GetClientRect": (wintypes.BOOL, [wintypes.HWND, POINTER(wintypes.RECT)]),
    "FillRect": (ctypes.c_int, [wintypes.HDC, POINTER(wintypes.RECT), wintypes.HBRUSH]),
    "MoveWindow": (
        wintypes.BOOL,
        [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.BOOL],
    ),
    "SendMessageW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "DefWindowProcW": (
        wintypes.LPARAM,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
    "SystemParametersInfoW": (
        wintypes.BOOL,
        [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT],
    ),
    "RegisterHotKey": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]),
    "UnregisterHotKey": (wintypes.BOOL, [wintypes.HWND, ctypes.c_int]),
}
_DWMAPI: dict[str, tuple[Any, list[Any]]] = {
    "DwmSetWindowAttribute": (
        ctypes.HRESULT,
        [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD],
    ),
    "DwmExtendFrameIntoClientArea": (ctypes.HRESULT, [wintypes.HWND, POINTER(_Margins)]),
}
_GDI32: dict[str, tuple[Any, list[Any]]] = {
    "GetStockObject": (wintypes.HGDIOBJ, [ctypes.c_int]),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi")
_gdi32 = ctypes.WinDLL("gdi32")
for _library, _signatures in ((_user32, _USER32), (_dwmapi, _DWMAPI), (_gdi32, _GDI32)):
    for _name, (_result, _arguments) in _signatures.items():
        _function = getattr(_library, _name)
        _function.restype, _function.argtypes = _result, _arguments


def set_backdrop(hwnd: int, dark: bool, backdrop: int) -> None:
    """Put a system backdrop under the window, or take it away with DWMSBT_NONE.

    DWM draws a backdrop only under a window with a frame: the window gets WS_CAPTION, and the
    native event filter answers WM_NCCALCSIZE with 0, so no title bar shows (PowerToys). The
    frame extends into the client area from the left only, which keeps the accent colour off
    the edges (QWindowKit).
    """
    style = _user32.GetWindowLongPtrW(hwnd, _GWL_STYLE)
    if not style & _WS_CAPTION:
        _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, style | _WS_CAPTION)
    _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(_Margins(65536, 0, 0, 0)))
    _attribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))
    _attribute(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
    _attribute(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, backdrop)
    flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags)


def erase_to_glass(hwnd: int, hdc: int) -> None:
    """Fill the client area black on the device context of a WM_ERASEBKGND: where the window is
    black, DWM shows the backdrop of a frame extended into the client area."""
    rect = wintypes.RECT()
    if _user32.GetClientRect(hwnd, ctypes.byref(rect)):
        _user32.FillRect(hdc, ctypes.byref(rect), _gdi32.GetStockObject(_BLACK_BRUSH))


def recreate_backdrop(hwnd: int, backdrop: int) -> None:
    """Take the backdrop away and put it back: after a change of theme or accent, DWM draws it
    as if the window were inactive, and solid, until transparency is toggled."""
    _attribute(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    _attribute(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, backdrop)
    activate_frame(hwnd)


def activate_frame(hwnd: int) -> None:
    """Tell DWM the frame is active: the backdrop of a window never active is solid otherwise."""
    _user32.SendMessageW(hwnd, WM_NCACTIVATE, 1, 0)


def active_frame_answer(hwnd: int, lparam: int) -> int:
    """What Windows answers to a WM_NCACTIVATE that says the frame is active."""
    result: int = _user32.DefWindowProcW(hwnd, WM_NCACTIVATE, 1, lparam)
    return result


def nudge(hwnd: int) -> None:
    """Shrink the window to one pixel and back, once after its first show: QWindowKit's
    workaround for Qt Quick windows whose backdrop does not appear."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return
    _user32.MoveWindow(hwnd, rect.left, rect.top, 1, 1, False)
    _user32.MoveWindow(hwnd, rect.right - 1, rect.bottom - 1, 1, 1, False)
    width, height = rect.right - rect.left, rect.bottom - rect.top
    _user32.MoveWindow(hwnd, rect.left, rect.top, width, height, False)


def setting_name(lparam: int) -> str | None:
    """The name a WM_SETTINGCHANGE carries, as "ImmersiveColorSet"; None when it has none."""
    return ctypes.wstring_at(lparam) if lparam else None


def transparency() -> bool:
    """Windows' transparency effects. In the prototype of #31 they also went off with energy
    saver, and the alert went solid with them."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE) as key:
            value = winreg.QueryValueEx(key, "EnableTransparency")[0]
    except OSError:
        return True  # no value: Windows' default, on
    return bool(value)


def animations() -> bool:
    """Windows' animation effects."""
    enabled = wintypes.BOOL()
    if not _user32.SystemParametersInfoW(_SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0):
        return True
    return bool(enabled.value)


def register_hotkey(hotkey_id: int, modifiers: int, key: int) -> int:
    """Have Windows post WM_HOTKEY with `hotkey_id` to this thread whenever the keys are pressed,
    whatever app has the focus; holding them down posts it once. Return 0, or Windows' error:
    1409 when another app has the keys."""
    if _user32.RegisterHotKey(None, hotkey_id, modifiers | _MOD_NOREPEAT, key):
        return 0
    return ctypes.get_last_error()


def unregister_hotkey(hotkey_id: int) -> None:
    _user32.UnregisterHotKey(None, hotkey_id)


def _attribute(hwnd: int, attribute: int, value: int) -> None:
    data = ctypes.c_int(value)
    _dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data))
