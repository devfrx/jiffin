"""The global shortcut, Win+Shift+N, which opens the creation window from any app (#12, #43).

Qt has no global shortcuts: `RegisterHotKey` has Windows post WM_HOTKEY to the interface thread
whenever the keys are pressed, whatever app has the focus, and a native event filter picks it
up. The thread that gets WM_HOTKEY may also bring its own window to the front.
"""

import ctypes
import logging
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray

from jiffin.ui import win32

log = logging.getLogger(__name__)

MODIFIERS = win32.MOD_WIN | win32.MOD_SHIFT
KEY = ord("N")
"""Win+Shift+N, chosen by the owner in #43: N for "Nuovo". Apps rarely use Win combinations."""
_ID = 1
_CODE_OFFSET = wintypes.MSG.message.offset


class Hotkey(QAbstractNativeEventFilter):
    """Install it with `QCoreApplication.installNativeEventFilter`, then `register` it on the
    interface thread; `on_pressed` is called there."""

    def __init__(self, on_pressed: Callable[[], None]) -> None:
        super().__init__()
        self._on_pressed = on_pressed
        self.registered = False
        """Windows gave us the keys: another app may hold them."""

    def register(self) -> None:
        error = win32.register_hotkey(_ID, MODIFIERS, KEY)
        self.registered = error == 0
        if error:
            log.warning("the shortcut is not registered: Windows error %d", error)

    def close(self) -> None:
        if self.registered:
            win32.unregister_hotkey(_ID)
            self.registered = False

    def nativeEventFilter(
        self, event_type: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        address = int(message)
        if ctypes.c_uint.from_address(address + _CODE_OFFSET).value != win32.WM_HOTKEY:
            return False, 0
        # Posted to the thread, not to a window: only Qt's event loop sees it, once.
        msg = wintypes.MSG.from_address(address)
        if msg.hWnd or msg.wParam != _ID:
            return False, 0
        self._on_pressed()
        return True, 0
