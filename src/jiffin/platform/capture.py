"""The adapter of the context port: the window in the foreground, as observations (ADR-0004).

A thread of its own runs a message loop for two WinEvent hooks (ADR-0005): the foreground
changed, anywhere; a title changed, in the foreground window's process only, since every name
change of every process would reach the loop otherwise. On each, it reads the app, the title
and, in the supported browsers, the address, from the multithreaded apartment. Private windows,
windows that may be private, and Jiffin's own are not contexts. An observation goes out only
when the context changed. Titles and addresses never reach the log.
"""

import contextlib
import logging
import os
import threading
from collections.abc import Callable
from typing import Protocol

import comtypes

from jiffin.core.clock import Clock
from jiffin.core.context import BROWSER_SUFFIXES, Context, Observation, normalize
from jiffin.platform import win32
from jiffin.platform.address import BROWSERS, AddressBars, Reading

log = logging.getLogger(__name__)

UNREADABLE_MS = 600_000
UNREADABLE_FAILURES = 5
"""A browser's address is unreadable once its bar has failed this many times over at least
UNREADABLE_MS, with no read in between: long enough for a video in full screen, which hides
the bar, and short enough to notice a browser update that broke the reading."""


class Bars(Protocol):
    def read(self, hwnd: int, app: str) -> Reading: ...


class Unreadable:
    """The browsers whose address cannot be read, for the tray (ADR-0005)."""

    def __init__(self, clock: Clock, on_change: Callable[[frozenset[str]], None]) -> None:
        self._clock = clock
        self._on_change = on_change
        self._failures: dict[str, tuple[int, int]] = {}
        """By app: when the first failure since the last read came, and how many there were."""
        self._apps: frozenset[str] = frozenset()

    def record(self, app: str, readable: bool) -> None:
        now = self._clock.now()
        if readable:
            self._failures.pop(app, None)
        else:
            since, count = self._failures.get(app, (now, 0))
            self._failures[app] = (since, count + 1)
        apps = frozenset(
            app
            for app, (since, count) in self._failures.items()
            if count >= UNREADABLE_FAILURES and now - since >= UNREADABLE_MS
        )
        if apps != self._apps:
            self._apps = apps
            log.info("address unreadable in: %s", ", ".join(sorted(apps)) or "no browser")
            self._on_change(apps)


class Foreground:
    """What is in the foreground, as observations; all of it runs on the context thread."""

    def __init__(
        self,
        clock: Clock,
        bars: Bars,
        on_observation: Callable[[Observation], None],
        unreadable: Unreadable,
    ) -> None:
        self._clock = clock
        self._bars = bars
        self._on_observation = on_observation
        self._unreadable = unreadable
        self._own = os.getpid()
        self._window: int | None = None
        self._titles: win32.Hook | None = None
        self._titles_of: int | None = None
        """The process whose title changes are hooked."""
        self._sent = False
        self._last: Context | None = None

    def on_event(self, event: int, hwnd: int | None, id_object: int, id_child: int) -> None:
        """A WinEvent: the foreground changed, or the name of something changed."""
        if event == win32.EVENT_OBJECT_NAMECHANGE and not (
            id_object == win32.OBJID_WINDOW
            and id_child == win32.CHILDID_SELF
            and hwnd == self._window
        ):
            return
        try:
            self.refresh()
        except Exception:  # a hook must not raise: ctypes would only print it
            log.exception("the foreground could not be read")

    def refresh(self) -> None:
        """Observe the foreground now; send the observation when the context changed."""
        at = self._clock.now()
        window = win32.foreground()
        if window != self._window:
            self._window = window
            self._follow_titles(window)
        context = self._context(window)
        if self._sent and context == self._last:
            return
        self._sent, self._last = True, context
        self._on_observation(Observation(at, context))

    def close(self) -> None:
        if self._titles is not None:
            self._titles.close()
            self._titles = None

    def _follow_titles(self, window: int | None) -> None:
        process = None if window is None else win32.process_id(window)
        if process == self._titles_of:
            return
        self.close()
        self._titles_of = process
        if process is not None and process != self._own:
            self._titles = win32.Hook(win32.EVENT_OBJECT_NAMECHANGE, self.on_event, process)

    def _context(self, window: int | None) -> Context | None:
        if window is None or win32.process_id(window) == self._own:
            return None
        program = win32.program(window)
        if program is None:
            return None
        title = win32.title(window)
        context = normalize(program, title, None)
        if context.app not in BROWSERS:
            return context
        reading = self._bars.read(window, context.app)
        # Only a tab window has a bar: not a dialog, an installed web app, or DevTools.
        if title.endswith(BROWSER_SUFFIXES[context.app]):
            self._unreadable.record(context.app, reading.readable)
        if not reading.contextual:
            return None
        return normalize(program, title, reading.address)


class Capture:
    """The context thread: its message loop, its hooks and its COM apartment.

    `on_observation` and `on_unreadable` are called on that thread: they should only queue
    what they get. `start` returns once the first observation has gone out.
    """

    def __init__(
        self,
        clock: Clock,
        on_observation: Callable[[Observation], None],
        on_unreadable: Callable[[frozenset[str]], None],
    ) -> None:
        self._clock = clock
        self._on_observation = on_observation
        self._on_unreadable = on_unreadable
        self._thread = threading.Thread(target=self._run, name="context", daemon=True)
        self._started = threading.Event()
        self._failure: Exception | None = None
        self._native_id: int | None = None

    def start(self) -> None:
        self._thread.start()
        self._started.wait()
        if self._failure is not None:
            self._thread.join()
            raise self._failure

    def close(self) -> None:
        if not self._started.is_set():
            return
        if self._native_id is not None and self._thread.is_alive():
            with contextlib.suppress(OSError):  # it has just ended on its own
                win32.post_quit(self._native_id)
        self._thread.join()

    def _run(self) -> None:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        bars: AddressBars | None = None
        foreground: Foreground | None = None
        hook: win32.Hook | None = None
        try:
            try:
                win32.make_queue()
                self._native_id = threading.get_native_id()
                bars = AddressBars()
                foreground = Foreground(
                    self._clock,
                    bars,
                    self._on_observation,
                    Unreadable(self._clock, self._on_unreadable),
                )
                hook = win32.Hook(win32.EVENT_SYSTEM_FOREGROUND, foreground.on_event)
                foreground.refresh()
            except Exception as error:  # noqa: BLE001  # start() raises it on its own thread
                self._failure = error
                return
            finally:
                self._started.set()
            win32.run_messages()
        except Exception:
            log.exception("the context thread failed")
        finally:
            if hook is not None:
                hook.close()
            if foreground is not None:
                foreground.close()
            if bars is not None:
                bars.close()
            # Every COM pointer must be gone before the apartment ends.
            hook = foreground = bars = None
            comtypes.CoUninitialize()
