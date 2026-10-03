from typing import Any

import comtypes
import comtypes.client
import pytest

from jiffin.core.context import BROWSER_SUFFIXES
from jiffin.platform import win32
from jiffin.platform.address import BROWSERS, AddressBars, Outcome, Reading

WINDOW = 7
GONE = comtypes.COMError(0x80040201 - 2**32, None, None)  # UIA_E_ELEMENTNOTAVAILABLE
SILENT = comtypes.COMError(0x80131505 - 2**32, None, None)  # UIA_E_TIMEOUT


class Bar:
    """Vivaldi's address bar, until it is gone or stops answering."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.error: comtypes.COMError | None = None

    @property
    def CurrentHasKeyboardFocus(self) -> bool:
        if self.error is not None:
            raise self.error
        return False

    def GetCurrentPropertyValue(self, property_id: int) -> str:
        if self.error is not None:
            raise self.error
        return self.address


class Element:
    """A window, or the toolbar of its bar: a search finds what it holds."""

    def __init__(self, holds: Bar | None) -> None:
        self.holds = holds
        self.searches = 0

    def FindFirst(self, scope: int, condition: Any) -> Bar | None:
        self.searches += 1
        return self.holds


class Automation:
    """UI Automation over one Vivaldi window that is not private."""

    def __init__(self) -> None:
        self.window = Element(Bar("fatture.example.it/elenco"))
        self.ControlViewWalker = self
        self.ConnectionTimeout = self.TransactionTimeout = 0

    def AddFocusChangedEventHandler(self, cache: Any, handler: Any) -> None:
        pass

    def ElementFromHandle(self, hwnd: int) -> Element:
        return self.window

    def CreatePropertyCondition(self, property_id: int, value: str) -> Any:
        return property_id, value

    def CreatePropertyConditionEx(self, property_id: int, value: str, flags: int) -> Any:
        return property_id, value

    def GetParentElement(self, element: Bar) -> Element:
        return Element(None)  # a toolbar without the private mark


@pytest.fixture
def automation(monkeypatch: pytest.MonkeyPatch) -> Automation:
    automation = Automation()
    monkeypatch.setattr(comtypes.client, "CreateObject", lambda *args, **kwargs: automation)
    monkeypatch.setattr(win32, "is_window", lambda hwnd: True)
    return automation


def test_every_supported_browser_has_its_title_suffix() -> None:
    assert BROWSERS.keys() == BROWSER_SUFFIXES.keys()


def test_a_bar_that_is_gone_is_looked_up_again(automation: Automation) -> None:
    bars = AddressBars()
    assert bars.read(WINDOW, "vivaldi.exe") == Reading(Outcome.ADDRESS, "fatture.example.it/elenco")
    # Vivaldi builds a new bar when a page leaves full screen.
    assert automation.window.holds is not None
    automation.window.holds.error = GONE
    automation.window.holds = Bar("fatture.example.it/elenco")
    assert bars.read(WINDOW, "vivaldi.exe") == Reading(Outcome.ADDRESS, "fatture.example.it/elenco")


def test_a_bar_gone_as_soon_as_found_is_looked_up_once(automation: Automation) -> None:
    bars = AddressBars()
    bars.read(WINDOW, "vivaldi.exe")
    assert automation.window.holds is not None
    automation.window.holds.error = GONE  # and so is the one the next search finds
    searches = automation.window.searches
    assert bars.read(WINDOW, "vivaldi.exe") == Reading(Outcome.FAILED)
    assert automation.window.searches == searches + 1


def test_a_bar_that_does_not_answer_is_not_looked_up_again(automation: Automation) -> None:
    bars = AddressBars()
    bars.read(WINDOW, "vivaldi.exe")
    assert automation.window.holds is not None
    automation.window.holds.error = SILENT
    searches = automation.window.searches
    assert bars.read(WINDOW, "vivaldi.exe") == Reading(Outcome.FAILED)
    assert automation.window.searches == searches


@pytest.mark.parametrize(
    ("outcome", "contextual", "readable"),
    [
        (Outcome.ADDRESS, True, True),
        (Outcome.TYPING, True, True),
        (Outcome.PRIVATE, False, True),
        (Outcome.FAILED, True, False),
        (Outcome.UNSURE, False, False),
    ],
)
def test_a_window_is_a_context_only_when_known_not_to_be_private(
    outcome: Outcome, contextual: bool, readable: bool
) -> None:
    assert (Reading(outcome).contextual, Reading(outcome).readable) == (contextual, readable)
