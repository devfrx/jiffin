"""The address bar of Vivaldi, Chrome and Brave, read through UI Automation (ADR-0005).

It runs on the context thread, in the multithreaded apartment. Chromium exposes its web content,
and so all of Vivaldi's interface, only to clients that look like assistive technology: hence a
focus listener that does nothing and, while Vivaldi's address bar is not exposed yet, a hit test
into the window. A private window has the same title as any other; UI Automation tells them
apart. The bar and the private flag of a window never change, so they are kept per window.

The ways to find the bar and the private marks were checked on 2026-09-30 with Vivaldi 8.2 (in
Italian), Chrome 154 and Brave 1.96.
"""

import logging
import re
import time
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, ClassVar

import comtypes
import comtypes.client

from jiffin.platform import win32

log = logging.getLogger(__name__)

_UIA: Any = comtypes.client.GetModule("UIAutomationCore.dll")
TIMEOUT_MS = 2000
"""How long UI Automation waits for a browser that does not answer."""
_WAKES = 4
_WAKE_SECONDS = 0.25
_IGNORE_CASE_SUBSTRING = 1 | 2  # PropertyConditionFlags_IgnoreCase | _MatchSubstring
_PRIVATE_NAME = re.compile(r"\(([^()]*)\)\s*$")
_PRIVATE_WORDS = ("incognit", "privat")
"""In the name of Chromium's root view: "(In incognito)", "(Privato)", "(Incognito)"."""


@dataclass(frozen=True, slots=True)
class _Browser:
    bar: tuple[int, str]
    """The property, and its value, that find the address bar."""
    web_ui: bool
    """Vivaldi draws its interface as a web page: the bar shows up only after a hit test, and
    the private mark sits beside it."""


BROWSERS = {
    "vivaldi.exe": _Browser((_UIA.UIA_AutomationIdPropertyId, "urlFieldInput"), web_ui=True),
    "chrome.exe": _Browser((_UIA.UIA_ClassNamePropertyId, "OmniboxViewViews"), web_ui=False),
    "brave.exe": _Browser((_UIA.UIA_ClassNamePropertyId, "BraveOmniboxViewViews"), web_ui=False),
}
"""The supported browsers, by app."""


class Outcome(Enum):
    ADDRESS = auto()
    """Read: the address is the bar's text, None when the bar is empty."""
    TYPING = auto()
    """The user is typing in the bar: its text is not an address."""
    PRIVATE = auto()
    """A private or incognito window: not a context."""
    FAILED = auto()
    """Not private, but the bar was not found, or could not be read."""
    UNSURE = auto()
    """Whether the window is private cannot be told: not a context."""


@dataclass(frozen=True, slots=True)
class Reading:
    outcome: Outcome
    address: str | None = None

    @property
    def contextual(self) -> bool:
        """Whether the window is a context: only when it is known not to be private."""
        return self.outcome not in (Outcome.PRIVATE, Outcome.UNSURE)

    @property
    def readable(self) -> bool:
        """Whether UI Automation could see the bar, or the private mark."""
        return self.outcome not in (Outcome.FAILED, Outcome.UNSURE)


class _FocusListener(comtypes.COMObject):  # type: ignore[misc]  # comtypes has no types
    """Does nothing: being registered is what makes Chromium expose its web content."""

    _com_interfaces_: ClassVar[list[Any]] = [_UIA.IUIAutomationFocusChangedEventHandler]

    def HandleFocusChangedEvent(self, sender: Any) -> int:
        return 0  # S_OK


class AddressBars:
    """Reads the address bars of the supported browsers, on the thread that created it."""

    def __init__(self) -> None:
        self._uia = comtypes.client.CreateObject(_UIA.CUIAutomation8, interface=_UIA.IUIAutomation2)
        self._uia.ConnectionTimeout = TIMEOUT_MS
        self._uia.TransactionTimeout = TIMEOUT_MS
        self._listener = _FocusListener()
        self._uia.AddFocusChangedEventHandler(None, self._listener)
        self._windows: dict[int, tuple[Any, bool]] = {}
        """The bar and the private flag of the windows seen so far."""

    def close(self) -> None:
        self._windows.clear()
        self._uia.RemoveAllEventHandlers()
        self._uia = None

    def read(self, hwnd: int, app: str) -> Reading:
        """What the bar of a window of `app`, one of BROWSERS, shows now."""
        known = self._windows.get(hwnd)
        if known is None:
            try:
                located = self._locate(hwnd, BROWSERS[app])
            except comtypes.COMError as error:
                log.info("%s: UI Automation failed, error %#010x", app, error.hresult & 0xFFFFFFFF)
                return Reading(Outcome.UNSURE)
            if isinstance(located, Outcome):
                return Reading(located)
            self._forget_closed()
            known = self._windows[hwnd] = located
        bar, private = known
        if private:
            return Reading(Outcome.PRIVATE)
        try:
            # While the bar has the focus, its text is what the user types, not an address.
            if bar.CurrentHasKeyboardFocus:
                return Reading(Outcome.TYPING)
            value = bar.GetCurrentPropertyValue(_UIA.UIA_ValueValuePropertyId)
        except comtypes.COMError as error:
            del self._windows[hwnd]
            log.info("%s: the bar could not be read, error %#010x", app, error.hresult & 0xFFFFFFFF)
            return Reading(Outcome.FAILED)
        return Reading(Outcome.ADDRESS, value or None)

    def _locate(self, hwnd: int, browser: _Browser) -> tuple[Any, bool] | Outcome:
        """The bar and the private flag, to keep; the outcome when there is nothing to keep."""
        root = self._uia.ElementFromHandle(hwnd)
        if browser.web_ui:
            bar = self._find_bar(hwnd, root, browser)
            private = self._vivaldi_private(bar) if bar else None
            return Outcome.UNSURE if private is None else (bar, private)
        private = self._chromium_private(root)
        if private is None:
            return Outcome.UNSURE
        if private:
            return None, True
        bar = self._find_bar(hwnd, root, browser)
        return (bar, False) if bar else Outcome.FAILED  # not kept: it may show up later

    def _find_bar(self, hwnd: int, root: Any, browser: _Browser) -> Any:
        condition = self._uia.CreatePropertyCondition(*browser.bar)
        bar = root.FindFirst(_UIA.TreeScope_Descendants, condition)
        for _ in range(_WAKES if browser.web_ui else 0):
            if bar:
                break
            self._hit_test(hwnd)
            time.sleep(_WAKE_SECONDS)
            bar = root.FindFirst(_UIA.TreeScope_Descendants, condition)
        return bar

    def _vivaldi_private(self, bar: Any) -> bool | None:
        """A private window has a PrivateWindowIndicator in the toolbar of the address bar."""
        toolbar = self._uia.ControlViewWalker.GetParentElement(bar)
        if not toolbar:
            return None
        mark = self._uia.CreatePropertyConditionEx(
            _UIA.UIA_ClassNamePropertyId, "PrivateWindowIndicator", _IGNORE_CASE_SUBSTRING
        )
        return bool(toolbar.FindFirst(_UIA.TreeScope_Subtree, mark))

    def _chromium_private(self, root: Any) -> bool | None:
        """Chrome and Brave end the name of the root view with "(In incognito)" or "(Privato)"."""
        view = root.FindFirst(
            _UIA.TreeScope_Children,
            self._uia.CreatePropertyConditionEx(
                _UIA.UIA_ClassNamePropertyId, "RootView", _IGNORE_CASE_SUBSTRING
            ),
        )
        if not view:
            return None
        mark = _PRIVATE_NAME.search(view.CurrentName)
        return mark is not None and any(word in mark[1].lower() for word in _PRIVATE_WORDS)

    def _hit_test(self, hwnd: int) -> None:
        """Ask for the element under two points of the window: Vivaldi then builds its tree."""
        rect = win32.window_rect(hwnd)
        if rect is None:
            return
        left, top, right, bottom = rect
        for y in ((top + bottom) // 2, top + 80):
            try:
                self._uia.ElementFromPoint(wintypes.POINT((left + right) // 2, y))
            except comtypes.COMError:
                pass

    def _forget_closed(self) -> None:
        for hwnd in [hwnd for hwnd in self._windows if not win32.is_window(hwnd)]:
            del self._windows[hwnd]
