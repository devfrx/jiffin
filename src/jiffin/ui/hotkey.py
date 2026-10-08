"""The global shortcuts, which work from any app: Win+Shift+N opens the creation window (#12, #43),
Win+Shift+Q the card of Remind here (ADR-0029).

Qt has no global shortcuts: `RegisterHotKey` has Windows post WM_HOTKEY to the interface thread
whenever the keys are pressed, whatever app has the focus, and a native event filter picks it
up. The thread that gets WM_HOTKEY may also bring its own window to the front.
"""

import ctypes
import logging
from collections.abc import Callable, Mapping
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray

from jiffin.ui import win32

log = logging.getLogger(__name__)

MODIFIERS = win32.MOD_WIN | win32.MOD_SHIFT
NEW = ord("N")
"""Win+Shift+N, chosen by the owner in #43: N for "Nuovo". Apps rarely use Win combinations."""
HERE = ord("Q")
"""Win+Shift+Q, chosen by the owner in #126: Q for "qui"; free on the owner's PC on
2026-10-06."""
_CODE_OFFSET = wintypes.MSG.message.offset


class Hotkeys(QAbstractNativeEventFilter):
    """Install it with `QCoreApplication.installNativeEventFilter`, then `register` it on the
    interface thread; each key's function is called there. A key goes to Windows with its own
    code as its id."""

    def __init__(self, keys: Mapping[int, Callable[[], None]]) -> None:
        super().__init__()
        self._keys = dict(keys)
        self.registered: frozenset[int] = frozenset()
        """The keys Windows gave us: another app may hold the others."""

    def register(self) -> None:
        registered = set()
        for key in self._keys:
            error = win32.register_hotkey(key, MODIFIERS, key)
            if error:
                log.warning(
                    "the shortcut Win+Shift+%s is not registered: Windows error %d", chr(key), error
                )
            else:
                registered.add(key)
        self.registered = frozenset(registered)

    def close(self) -> None:
        for key in self._keys:
            if key in self.registered:
                win32.unregister_hotkey(key)
        self.registered = frozenset()

    def nativeEventFilter(
        self, event_type: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        address = int(message)
        if ctypes.c_uint.from_address(address + _CODE_OFFSET).value != win32.WM_HOTKEY:
            return False, 0
        # Posted to the thread, not to a window: only Qt's event loop sees it, once.
        msg = wintypes.MSG.from_address(address)
        pressed = self._keys.get(msg.wParam)
        if msg.hWnd or pressed is None:
            return False, 0
        pressed()
        return True, 0
