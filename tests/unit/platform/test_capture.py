import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from jiffin.core.clock import SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.platform import win32
from jiffin.platform.address import Outcome, Reading
from jiffin.platform.capture import (
    UNREADABLE_FAILURES,
    UNREADABLE_MS,
    Capture,
    Foreground,
    Unreadable,
)

START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
NOTEPAD, VIVALDI, POPUP, JIFFIN, SYSTEM, GAME = 1, 2, 3, 4, 5, 6
NOTES = Context("notepad.exe", "appunti.txt - Blocco note", None)
INVOICES = Context("vivaldi.exe", "Fatture", "fatture.example.it/elenco")


@dataclass
class Window:
    pid: int
    program: str | None
    title: str
    full_screen: bool = False


@dataclass
class FakeHook:
    event: int
    handler: Callable[[int, int | None, int, int], None]
    process: int
    last: int | None
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeNotices:
    handler: Callable[[win32.Notice], None]
    thread: str
    """Where it was made."""
    closed: bool = False

    def close(self) -> None:
        self.closed = True


class FakeBars:
    """Address bars that show what the test says."""

    def __init__(self) -> None:
        self.readings: dict[int, Reading] = {}
        self.reads: list[int] = []

    def read(self, hwnd: int, app: str) -> Reading:
        self.reads.append(hwnd)
        return self.readings[hwnd]


class Scene:
    """A Foreground over a desk of fake windows, on simulated time."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.windows = {
            NOTEPAD: Window(10, "Notepad.exe", "* appunti.txt - Blocco note"),
            VIVALDI: Window(20, "vivaldi.exe", "Fatture - Vivaldi"),
            POPUP: Window(20, "vivaldi.exe", "Salva con nome"),
            JIFFIN: Window(os.getpid(), "python.exe", "Jiffin"),
            SYSTEM: Window(30, None, "Protected"),
            GAME: Window(40, "Game.exe", "Game", full_screen=True),
        }
        self.front: int | None = NOTEPAD
        self.hooks: list[FakeHook] = []
        self.clock = SimulatedClock(START)
        self.bars = FakeBars()
        self.bars.readings = {
            VIVALDI: Reading(Outcome.ADDRESS, "https://fatture.example.it/elenco?anno=2026"),
            POPUP: Reading(Outcome.UNSURE),
        }
        self.observations: list[Observation] = []
        self.unreadable: list[frozenset[str]] = []
        monkeypatch.setattr(win32, "foreground", lambda: self.front)
        monkeypatch.setattr(win32, "process_id", lambda hwnd: self.windows[hwnd].pid)
        monkeypatch.setattr(win32, "program", lambda hwnd: self.windows[hwnd].program)
        monkeypatch.setattr(win32, "title", lambda hwnd: self.windows[hwnd].title)
        monkeypatch.setattr(win32, "full_screen", lambda hwnd: self.windows[hwnd].full_screen)
        monkeypatch.setattr(win32, "Hook", self._hook)
        self.foreground = Foreground(
            self.clock,
            self.bars,
            self.observations.append,
            Unreadable(self.clock, self.unreadable.append),
        )

    @property
    def contexts(self) -> list[Context | None]:
        return [observation.context for observation in self.observations]

    @property
    def changes(self) -> list[FakeHook]:
        """The hooks on changes of title, place and size still open."""
        return [
            hook
            for hook in self.hooks
            if (hook.event, hook.last)
            == (win32.EVENT_OBJECT_LOCATIONCHANGE, win32.EVENT_OBJECT_NAMECHANGE)
            and not hook.closed
        ]

    def switch(self, window: int | None) -> None:
        """Bring a window to the foreground, as Windows would report it."""
        self.front = window
        self.foreground.on_event(win32.EVENT_SYSTEM_FOREGROUND, window, 0, 0)

    def rename(self, window: int, title: str) -> None:
        """Change a window's title, as Windows would report it."""
        self.windows[window].title = title
        self.foreground.on_event(
            win32.EVENT_OBJECT_NAMECHANGE, window, win32.OBJID_WINDOW, win32.CHILDID_SELF
        )

    def resize(self, window: int, full_screen: bool) -> None:
        """Move or resize a window, into full screen or not, as Windows would report it."""
        self.windows[window].full_screen = full_screen
        self.foreground.on_event(
            win32.EVENT_OBJECT_LOCATIONCHANGE, window, win32.OBJID_WINDOW, win32.CHILDID_SELF
        )

    def _hook(
        self,
        event: int,
        handler: Callable[[int, int | None, int, int], None],
        process: int = 0,
        last: int | None = None,
    ) -> FakeHook:
        hook = FakeHook(event, handler, process, last)
        self.hooks.append(hook)
        return hook


@pytest.fixture
def scene(monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(monkeypatch)


def test_an_app_is_observed_with_its_normalized_title_and_the_time(scene: Scene) -> None:
    scene.foreground.refresh()
    assert scene.observations == [Observation(START, NOTES)]


def test_only_a_change_of_context_is_sent(scene: Scene) -> None:
    scene.foreground.refresh()
    scene.clock.advance(1_000)
    scene.rename(NOTEPAD, "appunti.txt - Blocco note")  # the same context, normalized
    scene.clock.advance(1_000)
    scene.rename(NOTEPAD, "lettera.txt - Blocco note")
    assert [observation.at for observation in scene.observations] == [START, START + 2_000]
    assert scene.contexts[-1] == Context("notepad.exe", "lettera.txt - Blocco note", None)


def test_a_browser_tab_is_observed_with_its_address(scene: Scene) -> None:
    scene.switch(VIVALDI)
    assert scene.contexts == [Context("vivaldi.exe", "Fatture", "fatture.example.it/elenco")]


@pytest.mark.parametrize(
    ("reading", "context"),
    [
        (Reading(Outcome.TYPING), Context("vivaldi.exe", "Fatture", None)),
        (Reading(Outcome.FAILED), Context("vivaldi.exe", "Fatture", None)),
        (Reading(Outcome.ADDRESS, None), Context("vivaldi.exe", "Fatture", None)),
        (Reading(Outcome.PRIVATE), None),
        (Reading(Outcome.UNSURE), None),
    ],
    ids=["typing", "failed", "empty bar", "private", "maybe private"],
)
def test_a_browser_tab_without_an_address(
    scene: Scene, reading: Reading, context: Context | None
) -> None:
    scene.bars.readings[VIVALDI] = reading
    scene.switch(VIVALDI)
    assert scene.contexts == [context]


def test_nothing_in_front_jiffin_and_unknown_programs_are_not_contexts(scene: Scene) -> None:
    scene.foreground.refresh()
    for window in (None, NOTEPAD, JIFFIN, NOTEPAD, SYSTEM):
        scene.switch(window)
    assert scene.contexts == [
        Context("notepad.exe", "appunti.txt - Blocco note", None),
        None,
        Context("notepad.exe", "appunti.txt - Blocco note", None),
        None,
        Context("notepad.exe", "appunti.txt - Blocco note", None),
        None,
    ]


def test_changes_are_followed_in_the_process_in_front_only(scene: Scene) -> None:
    scene.foreground.refresh()
    assert [hook.process for hook in scene.changes] == [10]
    scene.switch(VIVALDI)
    assert [hook.process for hook in scene.changes] == [20]
    scene.switch(POPUP)  # the same process: the same hook
    assert len(scene.hooks) == 2
    scene.switch(JIFFIN)
    assert scene.changes == []
    scene.switch(None)
    assert scene.changes == []
    scene.foreground.close()
    assert all(hook.closed for hook in scene.hooks)


def test_a_title_change_elsewhere_is_ignored(scene: Scene) -> None:
    scene.switch(VIVALDI)
    scene.windows[POPUP].title = "Apri"
    scene.foreground.on_event(win32.EVENT_OBJECT_NAMECHANGE, POPUP, win32.OBJID_WINDOW, 0)
    scene.windows[VIVALDI].title = "Note - Vivaldi"
    scene.foreground.on_event(win32.EVENT_OBJECT_NAMECHANGE, VIVALDI, -4, 0)  # OBJID_CLIENT
    scene.foreground.on_event(win32.EVENT_OBJECT_NAMECHANGE, VIVALDI, win32.OBJID_WINDOW, 7)
    assert len(scene.observations) == 1
    assert scene.bars.reads == [VIVALDI]


def test_a_window_in_full_screen_is_not_a_context_until_it_leaves_it(scene: Scene) -> None:
    scene.switch(VIVALDI)
    scene.clock.advance(1_000)
    scene.resize(VIVALDI, full_screen=True)  # F11, or a video
    scene.clock.advance(1_000)
    scene.resize(VIVALDI, full_screen=False)
    assert scene.observations == [
        Observation(START, INVOICES),
        Observation(START + 1_000, None),
        Observation(START + 2_000, INVOICES),
    ]


def test_a_window_that_comes_in_front_in_full_screen_is_not_a_context(scene: Scene) -> None:
    scene.foreground.refresh()
    scene.switch(GAME)
    scene.switch(NOTEPAD)
    assert scene.contexts == [NOTES, None, NOTES]


def test_a_move_that_keeps_the_window_out_of_full_screen_reads_nothing(scene: Scene) -> None:
    scene.switch(VIVALDI)
    for _ in range(3):
        scene.resize(VIVALDI, full_screen=False)  # dragged around
    assert scene.contexts == [INVOICES]
    assert scene.bars.reads == [VIVALDI]


def test_a_move_elsewhere_is_ignored(scene: Scene) -> None:
    scene.switch(VIVALDI)
    scene.windows[POPUP].full_screen = True
    scene.foreground.on_event(win32.EVENT_OBJECT_LOCATIONCHANGE, POPUP, win32.OBJID_WINDOW, 0)
    scene.windows[VIVALDI].full_screen = True
    scene.foreground.on_event(win32.EVENT_OBJECT_LOCATIONCHANGE, VIVALDI, -8, 0)  # OBJID_CARET
    assert scene.contexts == [INVOICES]


def test_nothing_is_in_front_from_a_lock_to_the_unlock(scene: Scene) -> None:
    scene.foreground.refresh()
    scene.clock.advance(1_000)
    scene.foreground.on_notice(win32.Notice.LOCKED)
    scene.switch(VIVALDI)  # as the lock screen comes in front, a context any other time
    scene.clock.advance(1_000)
    scene.front = NOTEPAD
    scene.foreground.on_notice(win32.Notice.UNLOCKED)
    assert scene.observations == [
        Observation(START, NOTES),
        Observation(START + 1_000, None),
        Observation(START + 2_000, NOTES),
    ]


def test_nothing_is_in_front_from_sleep_to_both_the_wake_and_the_unlock(scene: Scene) -> None:
    scene.foreground.refresh()
    for notice in (win32.Notice.SLEEPING, win32.Notice.LOCKED, win32.Notice.AWAKE):
        scene.clock.advance(1_000)
        scene.foreground.on_notice(notice)
    assert scene.contexts == [NOTES, None]
    scene.clock.advance(1_000)
    scene.foreground.on_notice(win32.Notice.UNLOCKED)
    assert scene.observations[-1] == Observation(START + 4_000, NOTES)


def test_a_pc_that_does_not_lock_is_back_when_it_wakes(scene: Scene) -> None:
    scene.foreground.refresh()
    scene.foreground.on_notice(win32.Notice.SLEEPING)
    scene.clock.advance(60_000)
    scene.foreground.on_notice(win32.Notice.AWAKE)
    assert scene.observations == [
        Observation(START, NOTES),
        Observation(START, None),
        Observation(START + 60_000, NOTES),
    ]


def test_a_failure_while_reading_after_a_notice_is_logged(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    del scene.windows[NOTEPAD]  # it closed before it could be read
    with caplog.at_level(logging.ERROR):
        scene.foreground.on_notice(win32.Notice.UNLOCKED)
    assert "the foreground could not be read" in caplog.text


def test_a_failure_while_reading_is_logged_and_the_hook_goes_on(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    del scene.windows[NOTEPAD]  # it closed before it could be read
    with caplog.at_level(logging.ERROR):
        scene.switch(NOTEPAD)
    assert "the foreground could not be read" in caplog.text
    scene.switch(VIVALDI)
    assert scene.contexts == [Context("vivaldi.exe", "Fatture", "fatture.example.it/elenco")]


def test_only_the_tab_windows_of_a_browser_count_for_its_address(scene: Scene) -> None:
    scene.bars.readings[VIVALDI] = Reading(Outcome.FAILED)
    for _ in range(UNREADABLE_FAILURES):
        scene.switch(POPUP)  # no bar there: not a failure
        scene.clock.advance(UNREADABLE_MS)
    assert scene.unreadable == []
    for _ in range(UNREADABLE_FAILURES):
        scene.switch(VIVALDI)
        scene.switch(NOTEPAD)
        scene.clock.advance(UNREADABLE_MS // (UNREADABLE_FAILURES - 1))
    assert scene.unreadable == [frozenset({"vivaldi.exe"})]


def record(unreadable: Unreadable, clock: SimulatedClock, app: str, *readable: bool) -> None:
    """Record reads of `app` one minute apart."""
    for each in readable:
        unreadable.record(app, each)
        clock.advance(60_000)


def test_an_address_is_unreadable_after_enough_failures_over_enough_time() -> None:
    clock = SimulatedClock(START)
    changes: list[frozenset[str]] = []
    unreadable = Unreadable(clock, changes.append)
    record(unreadable, clock, "vivaldi.exe", *[False] * UNREADABLE_FAILURES)  # enough failures
    assert changes == []  # but only 4 minutes
    clock.advance(UNREADABLE_MS)
    record(unreadable, clock, "vivaldi.exe", False)
    assert changes == [frozenset({"vivaldi.exe"})]
    record(unreadable, clock, "chrome.exe", False)
    clock.advance(2 * UNREADABLE_MS)
    record(unreadable, clock, "chrome.exe", False)  # enough time, but two failures
    assert changes == [frozenset({"vivaldi.exe"})]
    record(unreadable, clock, "vivaldi.exe", True)
    assert changes == [frozenset({"vivaldi.exe"}), frozenset()]


def test_a_read_in_between_starts_the_count_again() -> None:
    clock = SimulatedClock(START)
    changes: list[frozenset[str]] = []
    unreadable = Unreadable(clock, changes.append)
    record(unreadable, clock, "brave.exe", *[False] * (UNREADABLE_FAILURES - 1), True)
    clock.advance(UNREADABLE_MS)
    record(unreadable, clock, "brave.exe", False)
    assert changes == []


def test_the_capture_thread_observes_at_once_and_closes() -> None:
    observations: list[Observation] = []
    capture = Capture(SystemClock(), observations.append, lambda apps: None)
    capture.start()
    try:
        assert observations  # whatever is in front
    finally:
        capture.close()
    assert not any(thread.name == "context" for thread in threading.enumerate())


def test_the_capture_thread_takes_windows_notices_and_ends_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[FakeNotices] = []

    def make(handler: Callable[[win32.Notice], None]) -> FakeNotices:
        made.append(FakeNotices(handler, threading.current_thread().name))
        return made[-1]

    monkeypatch.setattr(win32, "Notices", make)
    capture = Capture(SystemClock(), lambda observation: None, lambda apps: None)
    capture.start()
    capture.close()
    [notices] = made
    assert (notices.thread, notices.closed) == ("context", True)
    assert getattr(notices.handler, "__func__", None) is Foreground.on_notice


def test_a_capture_that_cannot_start_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object) -> None:
        raise OSError("SetWinEventHook refused the event 0x0003")

    monkeypatch.setattr(win32, "Hook", refuse)
    capture = Capture(SystemClock(), lambda observation: None, lambda apps: None)
    with pytest.raises(OSError, match="refused"):
        capture.start()
    capture.close()
