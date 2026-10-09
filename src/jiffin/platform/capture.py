"""The adapter of the context port: the window in the foreground and the situations, as
observations (ADR-0004, ADR-0028).

A thread of its own runs a message loop for two WinEvent hooks (ADR-0005): the foreground
changed, anywhere; the window in front changed its title, moved or resized, in its process
only, since every change of every process would reach the loop otherwise. On each, it reads the
app, the title and, in the supported browsers, the address, from the multithreaded apartment.
The same loop takes Windows' notices of a lock and of sleep (ADR-0021).

Private windows, windows that may be private, Jiffin's own and a window in full screen
(ADR-0024) are not contexts, and nothing is in front while the screen is locked or the PC
asleep. An observation goes out only when the context changed.

The situations are read on the same thread: Core Audio and the Network List Manager tell their
changes on Windows' own threads, which only wake the loop; the states that cost little to read,
or have no event, are read at each tick. Each situation goes out at start, and then only when
its values changed. The networks' labels come from the settings, on another thread, and wake the
loop too; the ids of the networks connected go to the interface, for the settings to label them.

Titles, addresses, sites and the networks' ids never reach the log.
"""

import contextlib
import logging
import os
import threading
from collections.abc import Callable, Mapping
from typing import Protocol

import comtypes

from jiffin.core.clock import Clock
from jiffin.core.context import BROWSER_SUFFIXES, Context, Observation, normalize
from jiffin.core.situations import (
    AWAY_MS,
    BATTERY,
    NO,
    OFFLINE,
    PLUGGED,
    YES,
    Situation,
    SituationObservation,
)
from jiffin.platform import win32
from jiffin.platform.address import BROWSERS, AddressBars, Reading
from jiffin.platform.audio import Audio
from jiffin.platform.media import Media
from jiffin.platform.network import Networks

log = logging.getLogger(__name__)

UNREADABLE_MS = 600_000
UNREADABLE_FAILURES = 5
"""A browser's address is unreadable once its bar has failed this many times over at least
UNREADABLE_MS, with no read in between: long enough to pass over a failure now and then, and
short enough to notice a browser update that broke the reading. A window in full screen, which
hides the bar, is not read at all."""
TICK_MS = 1_000
"""How often the states without events of their own are read: the time since the last input,
what plays, the power and the displays. All four take about half a millisecond (#147)."""
RETRY_MS = 60_000
"""A source of Windows that could not start, or failed a read, starts again this long after."""
_AUDIO_CHANGED = win32.WM_APP + 1
_NETWORKS_CHANGED = win32.WM_APP + 2
_LABELS_CHANGED = win32.WM_APP + 3


class Bars(Protocol):
    def read(self, hwnd: int, app: str) -> Reading: ...


class Tabs(Protocol):
    def records(self, hwnd: int, app: str) -> bool | None: ...


class Microphones(Protocol):
    """Core Audio: `platform.audio.Audio`."""

    def capturing(self) -> frozenset[int]: ...
    def headphones(self) -> bool: ...
    def close(self) -> None: ...


class Players(Protocol):
    """Windows' media controls: `platform.media.Media`."""

    def playing(self) -> frozenset[str]: ...
    def close(self) -> None: ...


class Connections(Protocol):
    """The Network List Manager: `platform.network.Networks`."""

    def connected(self) -> frozenset[str]: ...
    def close(self) -> None: ...


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
    """What is in the foreground, as observations; all of it runs on the context thread.
    `on_front` gets the window in front with each context that goes out."""

    def __init__(
        self,
        clock: Clock,
        bars: Bars,
        on_observation: Callable[[Observation], None],
        unreadable: Unreadable,
        on_front: Callable[[int | None, Context | None], None] | None = None,
    ) -> None:
        self._clock = clock
        self._bars = bars
        self._on_observation = on_observation
        self._unreadable = unreadable
        self._on_front = on_front
        self._own = os.getpid()
        self._window: int | None = None
        self._changes: win32.Hook | None = None
        self._changes_of: int | None = None
        """The process whose changes of title, place and size are hooked."""
        self._full_screen = False
        """Whether the window in front was in full screen when last read."""
        self._locked = False
        self._asleep = False
        self._sent = False
        self._last: Context | None = None

    def on_event(self, event: int, hwnd: int | None, id_object: int, id_child: int) -> None:
        """A WinEvent: the foreground changed, or something changed its name, moved or resized."""
        if event != win32.EVENT_SYSTEM_FOREGROUND and not (
            id_object == win32.OBJID_WINDOW
            and id_child == win32.CHILDID_SELF
            and hwnd == self._window
        ):
            return
        try:
            # A move or a resize of the window in front matters only into or out of full screen:
            # F11 changes its rectangle, not the window.
            if (
                event == win32.EVENT_OBJECT_LOCATIONCHANGE
                and hwnd is not None
                and win32.full_screen(hwnd) == self._full_screen
            ):
                return
            self.refresh()
        except Exception:  # a hook must not raise: ctypes would only print it
            log.exception("the foreground could not be read")

    def on_notice(self, notice: win32.Notice) -> None:
        """The screen locked or unlocked, or the PC goes to sleep or woke: nothing is in front
        from a lock or a sleep until both are over (ADR-0021)."""
        if notice in (win32.Notice.LOCKED, win32.Notice.UNLOCKED):
            self._locked = notice is win32.Notice.LOCKED
        else:
            self._asleep = notice is win32.Notice.SLEEPING
        try:
            self.refresh()
        except Exception:  # a window procedure must not raise either
            log.exception("the foreground could not be read")

    def refresh(self) -> None:
        """Observe the foreground now; send the observation when the context changed."""
        at = self._clock.now()
        window = win32.foreground()
        if window != self._window:
            self._window = window
            self._follow(window)
        self._full_screen = window is not None and win32.full_screen(window)
        away = self._locked or self._asleep or self._full_screen
        context = None if away else self._context(window)
        if self._sent and context == self._last:
            return
        self._sent, self._last = True, context
        self._on_observation(Observation(at, context))
        if self._on_front is not None:
            self._on_front(window, context)

    def close(self) -> None:
        if self._changes is not None:
            self._changes.close()
            self._changes = None

    def _follow(self, window: int | None) -> None:
        process = None if window is None else win32.process_id(window)
        if process == self._changes_of:
            return
        self.close()
        self._changes_of = process
        if process is not None and process != self._own:
            # One hook takes both: the two events are next to each other.
            self._changes = win32.Hook(
                win32.EVENT_OBJECT_LOCATIONCHANGE,
                self.on_event,
                process,
                last=win32.EVENT_OBJECT_NAMECHANGE,
            )

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


def _code(error: Exception) -> str:
    """An error's code, for the log: COM's or Windows', or else what it says."""
    if isinstance(error, comtypes.COMError):
        return f"{error.hresult & 0xFFFFFFFF:#010x}"
    code = getattr(error, "winerror", None)
    return f"{code & 0xFFFFFFFF:#010x}" if code else str(error)


class _Trouble:
    """What the log says of a source that fails: each failure once, by its code, and its
    return."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._code: str | None = None
        """The code of the failure under way, as the log told it."""

    def failed(self, error: Exception) -> None:
        code = _code(error)
        if code != self._code:
            log.warning("%s cannot be read: error %s", self._name, code)
            self._code = code

    def read(self) -> None:
        if self._code is not None:
            log.info("%s read again", self._name)
            self._code = None


def _machine[R](trouble: _Trouble, read: Callable[[], R]) -> R | None:
    """A state Windows gives at each call; None when the call fails."""
    try:
        value = read()
    except OSError as error:
        trouble.failed(error)
        return None
    trouble.read()
    return value


class _Closable(Protocol):
    def close(self) -> None: ...


class _Source[T: _Closable]:
    """One of Windows' sources, started on the context thread. When it cannot start, or a read
    fails, it is closed and starts again RETRY_MS later; in between, it is not read."""

    def __init__(self, name: str, start: Callable[[], T]) -> None:
        self._start = start
        self._trouble = _Trouble(name)
        self._source: T | None = None
        self._again_at = 0
        """When it starts again, while it is closed."""

    def due(self, now: int) -> bool:
        """Whether it is closed and may start again."""
        return self._source is None and now >= self._again_at

    def read[R](self, now: int, read: Callable[[T], R]) -> R | None:
        """What `read` gives of the source, started now if it is due; None while it cannot be
        read."""
        if self.due(now):
            try:
                self._source = self._start()
            except (OSError, comtypes.COMError) as error:
                self._failed(now, error)
        if self._source is None:
            return None
        try:
            value = read(self._source)
        except (OSError, comtypes.COMError) as error:
            self._failed(now, error)
            return None
        self._trouble.read()
        return value

    def close(self) -> None:
        if self._source is not None:
            with contextlib.suppress(OSError, comtypes.COMError):
                self._source.close()
            self._source = None

    def _failed(self, now: int, error: Exception) -> None:
        self._trouble.failed(error)
        self.close()
        self._again_at = now + RETRY_MS


class _Wake:
    """Wakes the context thread from Windows' threads, with one message for a burst of calls: it
    is posted again only once the thread has taken it."""

    def __init__(self, thread: int, message: int) -> None:
        self._thread = thread
        self._message = message
        self._posted = threading.Event()

    def __call__(self) -> None:
        if self._posted.is_set():
            return
        self._posted.set()
        with contextlib.suppress(OSError):  # the thread has ended with the app
            win32.post(self._thread, self._message)

    def taken(self) -> None:
        """The thread took the message and reads now: a later call wakes it again."""
        self._posted.clear()


def _either(value: bool | None, yes: str, no: str) -> frozenset[str] | None:
    return None if value is None else frozenset({yes if value else no})


class Situations:
    """What Windows tells of the situations, as observations (ADR-0028); all of it runs on the
    context thread, which makes it. Each situation goes out at `start`, all at one time, and
    then only when its values changed: at a tick, when Core Audio or the networks wake the
    thread, when the context in front changes, at a notice of a lock or of sleep.

    A source that fails gives its situations no value, None, until it reads again. Otherwise
    away, power, display and headphones always have one: the harness takes the end of one of
    them with nothing after it for the app's close (#155).

    `on_networks` gets the ids of the networks connected, at start and when they change, on this
    thread: none while the networks cannot be read.
    """

    def __init__(
        self,
        clock: Clock,
        on_observation: Callable[[SituationObservation], None],
        tabs: Tabs,
        *,
        audio: Callable[[Callable[[], None]], Microphones] = Audio,
        media: Callable[[], Players] = Media,
        networks: Callable[[Callable[[], None]], Connections] = Networks,
        labels: Mapping[str, str] | None = None,
        on_networks: Callable[[frozenset[str]], None] | None = None,
    ) -> None:
        """`audio`, `media` and `networks` start each source, with what wakes the thread when
        it changes; `labels` are the networks' labels, `HOME` or `OFFICE`, by their id, as the
        settings keep them, until `label` gives new ones (#153)."""
        thread = threading.get_native_id()
        self._clock = clock
        self._on_observation = on_observation
        self._on_networks = on_networks
        self._tabs = tabs
        self._audio_changed = _Wake(thread, _AUDIO_CHANGED)
        self._networks_changed = _Wake(thread, _NETWORKS_CHANGED)
        self._labels_changed = _Wake(thread, _LABELS_CHANGED)
        self._audio = _Source("Core Audio", lambda: audio(self._audio_changed))
        self._media = _Source("the media controls", media)
        self._networks = _Source("the networks", lambda: networks(self._networks_changed))
        self._idle = _Trouble("the time since the last input")
        self._power = _Trouble("the power")
        self._displays = _Trouble("the displays")
        self._labels = labels or {}
        self._started = False
        self._sent: dict[Situation, frozenset[str] | None] = {}
        self._capturing: frozenset[str] | None = None
        """The programs whose stream from a microphone runs, in lower case; None when Core
        Audio cannot be read."""
        self._sites: dict[str, str] = {}
        """The site of the tab that records, by the browser that captures, once read."""
        self._headphones: bool | None = None
        self._playing: frozenset[str] | None = None
        self._connected: frozenset[str] | None = None
        self._told: frozenset[str] | None = None
        """The ids the interface heard of last; None before the first read."""
        self._plugged: bool | None = None
        self._display: bool | None = None
        self._window: int | None = None
        self._context: Context | None = None
        self._locked = False
        self._asleep = False
        self._busy_at = 0
        """When a call or something playing was last seen: the time without input counts from
        then at the latest, so that its end is no return."""

    def start(self) -> None:
        """Read every situation, and send each one."""
        try:
            at = self._clock.now()
            self._read_audio(at)
            self._read_networks(at)
            self._read_ticked(at)
            self._started = True
            self._send(at)
        except Exception:  # the contexts go on without the situations
            log.exception("the situations cannot be read")

    def tick(self) -> None:
        """Every TICK_MS: the states without events, and the sources due to start again."""
        if not self._started:
            return
        try:
            at = self._clock.now()
            if self._audio.due(at):
                self._read_audio(at)
            if self._networks.due(at):
                self._read_networks(at)
            self._read_ticked(at)
            if self._context is not None and self._context.app not in self._sites:
                self._read_tab()  # its mark may come a moment after the browser captures
            self._send(at)
        except Exception:  # a timer's handler must not raise: ctypes would only print it
            log.exception("the situations could not be read")

    def label(self, labels: Mapping[str, str]) -> None:
        """New labels for the networks, from the settings, on any thread: a label put on the
        network in use counts at once. Before the start they are only kept, and read then."""
        self._labels = labels
        if self._started:
            self._labels_changed()

    def on_message(self, message: int) -> None:
        """A message to the thread: Core Audio's wake, the networks', or new labels."""
        if not self._started:
            return
        try:
            at = self._clock.now()
            if message == _AUDIO_CHANGED:
                self._audio_changed.taken()
                self._read_audio(at)
            elif message == _NETWORKS_CHANGED:
                self._networks_changed.taken()
                self._read_networks(at)
            elif message == _LABELS_CHANGED:
                self._labels_changed.taken()
            else:
                return
            self._send(at)
        except Exception:  # the loop must go on
            log.exception("the situations could not be read")

    def front(self, window: int | None, context: Context | None) -> None:
        """The context in front changed: in a browser that captures, its tab in front may be
        the call's."""
        self._window, self._context = window, context
        if not self._started:
            return
        try:
            self._read_tab()
            self._send(self._clock.now())
        except Exception:  # a hook must not raise either
            log.exception("the situations could not be read")

    def on_notice(self, notice: win32.Notice) -> None:
        """The screen locked or unlocked, or the PC goes to sleep or woke: the user is away from
        a lock or a sleep until both are over."""
        if notice in (win32.Notice.LOCKED, win32.Notice.UNLOCKED):
            self._locked = notice is win32.Notice.LOCKED
        else:
            self._asleep = notice is win32.Notice.SLEEPING
        if not self._started:
            return
        try:
            self._send(self._clock.now())
        except Exception:  # a window procedure must not raise
            log.exception("the situations could not be read")

    def close(self) -> None:
        for source in (self._audio, self._media, self._networks):
            source.close()

    def _read_audio(self, at: int) -> None:
        read = self._audio.read(at, lambda audio: (audio.capturing(), audio.headphones()))
        if read is None:
            self._capturing = self._headphones = None
            self._sites.clear()
            return
        processes, self._headphones = read
        self._capturing = frozenset(
            program.lower() for process in processes if (program := win32.program_of(process))
        )
        for browser in self._sites.keys() - self._capturing:
            del self._sites[browser]
        self._read_tab()

    def _read_networks(self, at: int) -> None:
        """The networks connected; the interface hears of their ids at the first read, then when
        they change."""
        self._connected = self._networks.read(at, lambda networks: networks.connected())
        told = self._connected or frozenset()
        if told != self._told and self._on_networks is not None:
            self._told = told
            self._on_networks(told)

    def _read_ticked(self, at: int) -> None:
        """What plays, the power and the displays; the time since the last input is read with
        away."""
        self._playing = self._media.read(at, lambda media: media.playing())
        self._plugged = _machine(self._power, win32.plugged_in)
        self._display = _machine(self._displays, win32.external_display)

    def _read_tab(self) -> None:
        """While a supported browser captures and its window is in front, the site of its tab in
        front when that tab records: the call's site from then on, until the browser stops
        capturing. A tab that does not record keeps the site read before: the call goes on in
        another tab."""
        window, context = self._window, self._context
        if (
            window is None
            or context is None
            or context.app not in BROWSER_SUFFIXES
            or context.app not in (self._capturing or ())
        ):
            return
        site = context.site
        if site is not None and self._tabs.records(window, context.app):
            self._sites[context.app] = site

    def _send(self, at: int) -> None:
        """Send each situation whose values changed, all at `at`: once started, as every caller
        is."""
        values_now = {
            Situation.CALL: self._call(),
            Situation.AWAY: self._away(at),
            Situation.POWER: _either(self._plugged, PLUGGED, BATTERY),
            Situation.DISPLAY: _either(self._display, YES, NO),
            Situation.HEADPHONES: _either(self._headphones, YES, NO),
            Situation.NETWORK: self._network(),
            Situation.PLAYBACK: self._playing,
        }
        for situation, values in values_now.items():
            if situation in self._sent and self._sent[situation] == values:
                continue
            self._sent[situation] = values
            log.info("%s: %s", situation, self._shown(situation, values))
            self._on_observation(SituationObservation(at, situation, values))

    def _call(self) -> frozenset[str] | None:
        """The programs that capture, a browser's by the site of its call once read."""
        if self._capturing is None:
            return None
        return frozenset(self._sites.get(program, program) for program in self._capturing)

    def _away(self, at: int) -> frozenset[str] | None:
        """At once while locked or asleep; else after AWAY_MS without input, nor a call or
        anything playing."""
        if self._locked or self._asleep:
            return frozenset({YES})
        if self._call() or self._playing:
            self._busy_at = at
            return frozenset({NO})
        idle = _machine(self._idle, win32.idle_ms)
        if idle is None:
            return None
        quiet_since = max(at - idle, self._busy_at)
        return frozenset({YES if at - quiet_since >= AWAY_MS else NO})

    def _network(self) -> frozenset[str] | None:
        """The labels of the networks connected; `OFFLINE` without one."""
        if self._connected is None:
            return None
        if not self._connected:
            return frozenset({OFFLINE})
        return frozenset(
            self._labels[network] for network in self._connected if network in self._labels
        )

    def _shown(self, situation: Situation, values: frozenset[str] | None) -> str:
        """The values for the log: a call's sites only by their count."""
        if values is None:
            return "not read"
        if situation is not Situation.CALL:
            return ", ".join(sorted(values)) or "none"
        programs = values & (self._capturing or frozenset())
        shown = sorted(programs)
        if sites := len(values - programs):
            shown.append(f"{sites} sites" if sites > 1 else "1 site")
        return ", ".join(shown) or "none"


def _each(*handlers: Callable[[win32.Notice], None]) -> Callable[[win32.Notice], None]:
    """One handler of Windows' notices for several, called in order."""

    def handle(notice: win32.Notice) -> None:
        for handler in handlers:
            handler(notice)

    return handle


class Capture:
    """The context thread: its message loop, its hooks, its timer and its COM apartment.

    `on_observation`, `on_unreadable` and `on_networks` are called on that thread: they should
    only queue what they get. `start` returns once the first observations have gone out, the
    context's and the situations'.
    """

    def __init__(
        self,
        clock: Clock,
        on_observation: Callable[[Observation | SituationObservation], None],
        on_unreadable: Callable[[frozenset[str]], None],
        on_networks: Callable[[frozenset[str]], None],
    ) -> None:
        self._clock = clock
        self._on_observation = on_observation
        self._on_unreadable = on_unreadable
        self._on_networks = on_networks
        self._thread = threading.Thread(target=self._run, name="context", daemon=True)
        self._started = threading.Event()
        self._failure: Exception | None = None
        self._native_id: int | None = None
        self._labels: Mapping[str, str] = {}
        self._situations: Situations | None = None

    def label(self, labels: Mapping[str, str]) -> None:
        """The networks' labels, `HOME` or `OFFICE` by id, as the settings keep them: from any
        thread, before the start or after it."""
        self._labels = dict(labels)
        situations = self._situations
        if situations is not None:
            situations.label(self._labels)

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
        situations: Situations | None = None
        foreground: Foreground | None = None
        hook: win32.Hook | None = None
        notices: win32.Notices | None = None
        timer: win32.Timer | None = None
        try:
            try:
                win32.make_queue()
                self._native_id = threading.get_native_id()
                bars = AddressBars()
                situations = Situations(
                    self._clock,
                    self._on_observation,
                    bars,
                    labels=self._labels,
                    on_networks=self._on_networks,
                )
                self._situations = situations
                situations.label(self._labels)  # any that came meanwhile
                foreground = Foreground(
                    self._clock,
                    bars,
                    self._on_observation,
                    Unreadable(self._clock, self._on_unreadable),
                    situations.front,
                )
                hook = win32.Hook(win32.EVENT_SYSTEM_FOREGROUND, foreground.on_event)
                notices = win32.Notices(_each(foreground.on_notice, situations.on_notice))
                foreground.refresh()
                situations.start()
                timer = win32.Timer(TICK_MS, situations.tick)
            except Exception as error:  # noqa: BLE001  # start() raises it on its own thread
                self._failure = error
                return
            finally:
                self._started.set()
            win32.run_messages(situations.on_message)
        except Exception:
            log.exception("the context thread failed")
        finally:
            if timer is not None:
                timer.close()
            if notices is not None:
                notices.close()
            if hook is not None:
                hook.close()
            if foreground is not None:
                foreground.close()
            if situations is not None:
                situations.close()
            if bars is not None:
                bars.close()
            # Every COM pointer must be gone before the apartment ends: the timer and the notices
            # hold the readers through their handlers.
            timer = notices = hook = foreground = situations = bars = self._situations = None
            comtypes.CoUninitialize()
