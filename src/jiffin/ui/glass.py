"""The glass under our windows, and the Windows messages that change the look (ADR-0010).

The recipe for the alerts, verified with the prototype of #31: the window gets a frame and never
shows it (WM_NCCALCSIZE answered with 0), and DWM is always told the frame is active
(WM_NCACTIVATE passed as TRUE to DefWindowProcW, never to Qt), since the backdrop of a window
that is never active is solid otherwise. After a change of theme, accent or colours, DWM draws
it solid again until it is recreated: once, a while after the last message of the change. A
change of the animation effects is only read again; other setting changes are not the look's.

The creation window keeps Windows' own frame and title bar, and is active like any window: it
only gets Mica under it, and its frame messages are left to Windows.

The filter sees every message of the interface thread; it reads the code first, and the rest
of the message only for the few codes it handles.
"""

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QTimer

from jiffin.ui import win32
from jiffin.ui.look import Look, Material

SETTLE_MS = 1000
"""How long after the last message of a change the look is read again and the glass recreated."""
_CODE_OFFSET = wintypes.MSG.message.offset
_COLOURS = "ImmersiveColorSet"
"""The WM_SETTINGCHANGE of a change of theme, accent or transparency."""
_COLOUR_MESSAGES = frozenset((win32.WM_THEMECHANGED, win32.WM_DWMCOLORIZATIONCOLORCHANGED))


class Glass(QAbstractNativeEventFilter):
    """Install it with `QCoreApplication.installNativeEventFilter` before any window is shown."""

    def __init__(self, look: Look) -> None:
        super().__init__()
        self._look = look
        self._windows: set[int] = set()
        """Without a frame: the alerts."""
        self._framed: set[int] = set()
        """With Windows' own frame: the creation window."""
        self._nudged: set[int] = set()
        self._recreate = False
        """The change that is settling changed the colours."""
        self._settle = QTimer(singleShot=True, interval=SETTLE_MS)
        self._settle.timeout.connect(self._settled)
        look.changed.connect(self._apply)

    def add(self, hwnd: int) -> None:
        """A window of ours: its frame is never shown, and the glass goes under it."""
        self._windows.add(hwnd)
        win32.set_backdrop(hwnd, self._look.settings.dark, self._look.backdrop)

    def add_framed(self, hwnd: int) -> None:
        """A window with Windows' own frame: Mica goes under it."""
        self._framed.add(hwnd)
        win32.set_backdrop(hwnd, self._look.settings.dark, self._look.backdrop_for(Material.MICA))

    def shown(self, hwnd: int) -> None:
        win32.activate_frame(hwnd)
        if hwnd not in self._nudged:
            self._nudged.add(hwnd)
            win32.nudge(hwnd)

    def nativeEventFilter(
        self, event_type: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        address = int(message)
        code = ctypes.c_uint.from_address(address + _CODE_OFFSET).value
        if code in _COLOUR_MESSAGES:
            self._changed(recreate=True)
            return False, 0
        if code == win32.WM_SETTINGCHANGE:
            msg = wintypes.MSG.from_address(address)
            if win32.setting_name(msg.lParam) == _COLOURS:
                self._changed(recreate=True)
            elif msg.wParam == win32.SPI_SETCLIENTAREAANIMATION:
                self._changed(recreate=False)
            return False, 0
        if code not in (win32.WM_NCCALCSIZE, win32.WM_NCACTIVATE):
            return False, 0
        msg = wintypes.MSG.from_address(address)
        hwnd = msg.hWnd or 0
        if hwnd not in self._windows:
            return False, 0
        if code == win32.WM_NCACTIVATE:
            return True, win32.active_frame_answer(hwnd, msg.lParam)
        if msg.wParam:  # WM_NCCALCSIZE: the whole window is client area
            return True, 0
        return False, 0

    def _changed(self, recreate: bool) -> None:
        self._recreate |= recreate
        self._settle.start()

    def _apply(self) -> None:
        dark = self._look.settings.dark
        for hwnd in self._windows:
            win32.set_backdrop(hwnd, dark, self._look.backdrop)
            win32.activate_frame(hwnd)
        for hwnd in self._framed:
            win32.set_backdrop(hwnd, dark, self._look.backdrop_for(Material.MICA))

    def _settled(self) -> None:
        recreate, self._recreate = self._recreate, False
        self._look.refresh()
        backdrop = self._look.backdrop
        if not recreate or backdrop == win32.DWMSBT_NONE:
            return
        for hwnd in self._windows:
            win32.recreate_backdrop(hwnd, backdrop)
