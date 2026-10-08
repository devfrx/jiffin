import logging
from typing import Any

import comtypes
import comtypes.client
import pytest

from jiffin.core.context import BROWSER_SUFFIXES
from jiffin.platform import win32
from jiffin.platform.address import BROWSERS, CALL_MARKS, AddressBars, Outcome, Reading

WINDOW = 7
GONE = comtypes.COMError(0x80040201 - 2**32, None, None)  # UIA_E_ELEMENTNOTAVAILABLE
SILENT = comtypes.COMError(0x80131505 - 2**32, None, None)  # UIA_E_TIMEOUT
TAB_LIST, GROUP = 50018, 50026  # UIA_TabControlTypeId, UIA_GroupControlTypeId


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

    def CreateCacheRequest(self) -> "Automation":
        return self

    def AddProperty(self, property_id: int) -> None:
        pass

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


class Tab:
    """A tab, by the name UI Automation gives it with the search."""

    def __init__(self, name: str) -> None:
        self.CachedName = name


class Found:
    """The tabs a search found."""

    def __init__(self, *tabs: Tab) -> None:
        self.tabs = tabs
        self.Length = len(tabs)

    def GetElement(self, index: int) -> Tab:
        return self.tabs[index]


class Strip:
    """Chrome's list of tabs, until it is gone."""

    CurrentControlType = TAB_LIST

    def __init__(self, chrome: "Chrome") -> None:
        self._chrome = chrome
        self.error: comtypes.COMError | None = None
        self.searches = 0

    def FindAllBuildCache(self, scope: int, condition: Any, cache: Any) -> Found:
        self.searches += 1
        if self.error is not None:
            raise self.error
        return Found(*self._chrome.tabs)


class Group:
    """The tabs of a group, inside the list."""

    CurrentControlType = GROUP


class Chrome(Automation):
    """UI Automation over a Chrome window titled "Riunione": its list holds `tabs`, and the page
    shows its own `page_tabs` first. A tab is in a group when `grouped`."""

    def __init__(self) -> None:
        super().__init__()
        self.tabs = [Tab("Posta in arrivo - Microphone recording"), Tab("Riunione")]
        self.page_tabs: list[Tab] = []
        self.grouped = False
        self.error: comtypes.COMError | None = None
        self.searches = 0
        self.strips: list[Strip] = []

    def ElementFromHandle(self, hwnd: int) -> Any:
        return self

    def FindAllBuildCache(self, scope: int, condition: Any, cache: Any) -> Found:
        self.searches += 1
        if self.error is not None:
            raise self.error
        return Found(*self.page_tabs, *self.tabs)

    def GetParentElement(self, element: Any) -> Any:
        if isinstance(element, Tab) and self.grouped:
            return Group()
        self.strips.append(Strip(self))
        return self.strips[-1]


@pytest.fixture
def chrome(monkeypatch: pytest.MonkeyPatch) -> Chrome:
    chrome = Chrome()
    monkeypatch.setattr(comtypes.client, "CreateObject", lambda *args, **kwargs: chrome)
    monkeypatch.setattr(win32, "is_window", lambda hwnd: True)
    monkeypatch.setattr(win32, "title", lambda hwnd: "Riunione - Google Chrome")
    return chrome


@pytest.mark.parametrize(
    ("name", "records"),
    [
        ("Riunione", False),
        ("Riunione - Microphone recording", True),
        ("Riunione - Fissata - Registrazione con microfono - Utilizzo memoria - 210 MB", True),
        ("Riunione - Riproduzione audio in corso", False),
        ("Riunione - Tab content shared", False),  # another tab shares this one
        ("Riunione - Registrazione con videocamera", False),  # no microphone
        ("Riunione - Microphone recording quiz", False),
    ],
)
def test_a_tab_that_records_says_so_in_its_name(chrome: Chrome, name: str, records: bool) -> None:
    chrome.tabs[-1] = Tab(name)
    assert AddressBars().records(WINDOW, "chrome.exe") is records


def test_the_marks_of_a_tab_that_records_are_whole_parts_of_its_name(chrome: Chrome) -> None:
    for mark in CALL_MARKS:
        chrome.tabs[-1] = Tab(f"Riunione - {mark}")
        assert AddressBars().records(WINDOW, "chrome.exe") is True


def test_the_tab_in_front_is_the_one_that_bears_the_title_of_its_window(chrome: Chrome) -> None:
    chrome.page_tabs = [Tab("Partecipanti - Microphone recording")]  # one of the page's own
    chrome.tabs.insert(0, Tab("Riunione di ieri - Microphone recording"))
    assert AddressBars().records(WINDOW, "chrome.exe") is False


def test_the_list_of_tabs_is_kept_and_looked_up_again_once_gone(chrome: Chrome) -> None:
    bars = AddressBars()
    bars.records(WINDOW, "chrome.exe")
    chrome.tabs[-1] = Tab("Riunione - Microphone recording")
    assert bars.records(WINDOW, "chrome.exe") is True
    [strip] = chrome.strips
    assert (chrome.searches, strip.searches) == (1, 1)
    strip.error = GONE  # Chrome built its list again
    assert bars.records(WINDOW, "chrome.exe") is True
    assert (chrome.searches, len(chrome.strips)) == (2, 2)


def test_the_list_holds_the_tabs_of_every_group(chrome: Chrome) -> None:
    chrome.grouped = True
    bars = AddressBars()
    bars.records(WINDOW, "chrome.exe")
    bars.records(WINDOW, "chrome.exe")
    [strip] = chrome.strips  # above the group
    assert (chrome.searches, strip.searches) == (1, 1)


def test_a_name_that_does_not_follow_the_title_yet_cannot_tell(chrome: Chrome) -> None:
    bars = AddressBars()
    bars.records(WINDOW, "chrome.exe")
    chrome.tabs[-1] = Tab("Pagina precedente")  # the title changed first
    assert bars.records(WINDOW, "chrome.exe") is None
    chrome.tabs[-1] = Tab("Riunione - Registrazione con microfono")
    assert bars.records(WINDOW, "chrome.exe") is True
    assert chrome.searches == 1


def test_tabs_that_do_not_bear_the_title_are_searched_again_once_it_changes(
    chrome: Chrome, monkeypatch: pytest.MonkeyPatch
) -> None:
    chrome.tabs = [Tab("Posta in arrivo")]
    bars = AddressBars()
    assert bars.records(WINDOW, "chrome.exe") is None
    assert bars.records(WINDOW, "chrome.exe") is None
    assert chrome.searches == 1
    monkeypatch.setattr(win32, "title", lambda hwnd: "Posta in arrivo - Google Chrome")
    assert bars.records(WINDOW, "chrome.exe") is False
    assert chrome.searches == 2


def test_vivaldi_and_windows_that_are_not_of_tabs_cannot_tell(
    chrome: Chrome, monkeypatch: pytest.MonkeyPatch
) -> None:
    bars = AddressBars()
    monkeypatch.setattr(win32, "title", lambda hwnd: "Riunione - Vivaldi")
    assert bars.records(WINDOW, "vivaldi.exe") is None  # its tabs never show it
    monkeypatch.setattr(win32, "title", lambda hwnd: "DevTools - meet.google.com/abc")
    assert bars.records(WINDOW, "chrome.exe") is None
    assert chrome.searches == 0


def test_a_tab_that_cannot_be_read_cannot_tell(
    chrome: Chrome, caplog: pytest.LogCaptureFixture
) -> None:
    chrome.error = SILENT
    with caplog.at_level(logging.INFO):
        assert AddressBars().records(WINDOW, "chrome.exe") is None
    assert "chrome.exe: the tab could not be read, error 0x80131505" in caplog.text
