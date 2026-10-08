"""The real foreground, with Vivaldi, Chrome and Brave on fresh profiles (ADR-0005), and the
situations Windows tells (ADR-0028).

These tests run only on the owner's machine. `uv run pytest -m integration` opens windows of
each installed browser, in the foreground, for about two minutes, puts a page in full screen and
records from the microphone for a few seconds in each; `uv run pytest -m benchmark -s` measures
the CPU Vivaldi spends on the reads, in ten minutes. Leave the computer alone meanwhile. Every
page comes from a local server; nothing of the owner's browsers is touched.
"""

import ctypes
import json
import shutil
import subprocess
import threading
import time
import winreg
from collections.abc import Callable, Iterator
from ctypes import POINTER, wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import comtypes
import comtypes.client
import psutil
import pytest

from jiffin.core.clock import SystemClock
from jiffin.core.context import Observation
from jiffin.core.situations import Situation, SituationObservation
from jiffin.platform import win32
from jiffin.platform.address import BROWSERS
from jiffin.platform.capture import Capture
from jiffin.platform.media import Media
from jiffin.platform.network import Networks

PAGE = """<!doctype html><title>Jiffin {name}</title><p id="tick">0</p>
<script>
let tick = 0;
if ({every} > 0) setInterval(() => {{
  tick += 1;
  document.title = "Jiffin {name} " + tick;
  document.getElementById("tick").textContent = tick;
}}, {every});
addEventListener("keydown", (event) => {{
  if (event.key === "f") document.documentElement.requestFullscreen();
}});
if ({records}) navigator.mediaDevices.getUserMedia({{audio: true}}).then((stream) => {{
  window.kept = stream;
}});
</script>"""
BENCHMARK_SECONDS = 300
"""Each half of the benchmark: without reads, then with them."""


class _MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput), ("ki", _KeyboardInput))


class _Input(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _InputUnion))


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.restype = wintypes.UINT
_user32.SendInput.argtypes = [wintypes.UINT, POINTER(_Input), ctypes.c_int]
_INPUT_KEYBOARD, _KEYEVENTF_KEYUP = 1, 0x0002
_VK_ESCAPE, _VK_F = 0x1B, 0x46


def press(key: int) -> None:
    """A key down and up, to the window in front, as a keyboard sends it."""
    events = (_Input * 2)()
    for event, flags in zip(events, (0, _KEYEVENTF_KEYUP), strict=True):
        event.type = _INPUT_KEYBOARD
        event.u.ki = _KeyboardInput(key, 0, flags, 0, 0)
    sent = _user32.SendInput(len(events), events, ctypes.sizeof(_Input))
    assert sent == len(events), f"SendInput: {ctypes.WinError(ctypes.get_last_error())}"


class Pages:
    """A local server of pages titled "Jiffin <name>"; `?every=N` changes the title every N ms,
    the key F puts a page in full screen, as on a video, and `&records=1` records from the
    microphone, as a call does."""

    def __init__(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path, _, query = self.path.partition("?")
                values = dict(part.partition("=")[::2] for part in query.split("&") if part)
                body = PAGE.format(
                    name=path.strip("/"),
                    every=int(values.get("every", "0")),
                    records="true" if values.get("records") == "1" else "false",
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.host = f"127.0.0.1:{self._server.server_port}"

    def url(self, name: str, every_ms: int = 0, records: bool = False) -> str:
        return f"http://{self.host}/{name}?every={every_ms}&records={int(records)}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class Seen:
    """The observations of a capture, to wait on: the contexts, and the situations apart."""

    def __init__(self) -> None:
        self.observations: list[Observation] = []
        self.situations: list[SituationObservation] = []
        self._changed = threading.Condition()

    def add(self, observation: Observation | SituationObservation) -> None:
        with self._changed:
            if isinstance(observation, SituationObservation):
                self.situations.append(observation)
            else:
                self.observations.append(observation)
            self._changed.notify_all()

    def wait(self, what: Callable[[Observation], bool], after: int = 0) -> int:
        """The index of the first observation from `after` on that matches, within 30 s."""
        return self._wait(self.observations, what, after)

    def wait_situation(self, what: Callable[[SituationObservation], bool]) -> int:
        """The index of the first situation's observation that matches, within 30 s."""
        return self._wait(self.situations, what, 0)

    def _wait[T](self, seen: list[T], what: Callable[[T], bool], after: int) -> int:
        with self._changed:
            for _ in range(300):
                for index in range(after, len(seen)):
                    if what(seen[index]):
                        return index
                self._changed.wait(0.1)
        pytest.fail("the capture did not see it within 30 s")


def titled(prefix: str) -> Callable[[Observation], bool]:
    return lambda seen: seen.context is not None and seen.context.title.startswith(prefix)


class Browser:
    """A browser on a profile of its own, killed at the end. The pages of `allowed` (a host and
    its port) may record from the microphone without asking: the profile says so before the
    browser starts, as a user's Allow would. The browser's own switches that skip the question
    would also skip what marks the tab that records (`FakeMediaStreamUIProxy`)."""

    def __init__(self, app: str, program: str, profile: Path, allowed: str | None = None) -> None:
        self.app = app
        self._arguments = [
            program,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            # Programs such as security suites register extensions for Chrome in the registry, and
            # Vivaldi reads them too: a fresh profile installs them disabled, and Vivaldi says so
            # in a dialog that takes the focus from the address bar (#62).
            "--disable-extensions",
        ]
        self._profile = profile
        if allowed is not None:
            exception = {f"http://{allowed},*": {"setting": 1}}  # CONTENT_SETTING_ALLOW
            preferences = {
                "profile": {"content_settings": {"exceptions": {"media_stream_mic": exception}}}
            }
            (profile / "Default").mkdir(parents=True)
            (profile / "Default" / "Preferences").write_text(json.dumps(preferences))
        # The first window of a fresh Vivaldi shows its welcome, without the address bar.
        self._main = subprocess.Popen(self._arguments)
        time.sleep(5)

    def open(self, url: str, private: bool = False) -> None:
        # It hands the URL to the running browser, and ends.
        subprocess.run(
            [*self._arguments, "--incognito" if private else "--new-window", url], check=True
        )

    def processes(self) -> set[int]:
        main = psutil.Process(self._main.pid)
        return {main.pid, *(child.pid for child in main.children(recursive=True))}

    def cpu_seconds(self) -> dict[int, float]:
        seconds = {}
        for pid in self.processes():
            try:
                times = psutil.Process(pid).cpu_times()
            except psutil.NoSuchProcess:
                continue
            seconds[pid] = times.user + times.system
        return seconds

    def close(self) -> None:
        try:
            main = psutil.Process(self._main.pid)
            for process in [*main.children(recursive=True), main]:
                process.kill()
        except psutil.NoSuchProcess:
            pass
        self._main.wait(10)
        shutil.rmtree(self._profile, ignore_errors=True)


def installed(app: str) -> str | None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        key = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app}"
        try:
            return winreg.QueryValue(hive, key)
        except OSError:
            continue
    return None


@pytest.fixture(scope="module")
def pages() -> Iterator[Pages]:
    pages = Pages()
    yield pages
    pages.close()


@pytest.fixture
def seen() -> Iterator[Seen]:
    seen = Seen()
    capture = Capture(SystemClock(), seen.add, lambda apps: None)
    capture.start()
    yield seen
    capture.close()


def start(app: str, tmp_path: Path, allowed: str | None = None) -> Browser:
    program = installed(app)
    if program is None:
        pytest.skip(f"{app} is not installed")
    return Browser(app, program, tmp_path / "profile", allowed)


@pytest.fixture(params=sorted(BROWSERS))
def browser(request: pytest.FixtureRequest, tmp_path: Path, pages: Pages) -> Iterator[Browser]:
    browser = start(request.param, tmp_path, allowed=pages.host)
    yield browser
    browser.close()


@pytest.mark.integration
def test_the_address_of_a_tab_is_read(pages: Pages, seen: Seen, browser: Browser) -> None:
    browser.open(pages.url(f"read-{browser.app}"))
    context = seen.observations[seen.wait(titled(f"Jiffin read-{browser.app}"))].context
    assert context is not None
    assert (context.app, context.address) == (browser.app, f"{pages.host}/read-{browser.app}")


@pytest.mark.integration
def test_a_private_window_is_not_a_context(pages: Pages, seen: Seen, browser: Browser) -> None:
    browser.open(pages.url(f"shown-{browser.app}"))
    shown = seen.wait(titled(f"Jiffin shown-{browser.app}"))
    browser.open(pages.url(f"secret-{browser.app}"), private=True)
    seen.wait(lambda observation: observation.context is None, after=shown + 1)
    time.sleep(3)
    assert win32.process_id(win32.foreground() or 0) in browser.processes()
    assert seen.observations[-1].context is None
    assert not any(
        "secret" in f"{observation.context.title} {observation.context.address}"
        for observation in seen.observations
        if observation.context is not None
    )


@pytest.mark.integration
def test_typing_in_the_bar_gives_no_address(pages: Pages, seen: Seen, browser: Browser) -> None:
    page = f"Jiffin typing-{browser.app}"
    browser.open(pages.url(f"typing-{browser.app}", every_ms=2_000))
    seen.wait(titled(page))
    window = win32.foreground()
    assert window is not None and win32.process_id(window) in browser.processes()
    uia: Any = comtypes.client.GetModule("UIAutomationCore.dll")
    client = comtypes.client.CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
    bar = client.ElementFromHandle(window).FindFirst(
        uia.TreeScope_Descendants, client.CreatePropertyCondition(*BROWSERS[browser.app].bar)
    )
    bar.SetFocus()  # as Ctrl+L does, before the user types
    focused = len(seen.observations)
    # The title goes on changing: the next reads find the bar in use.
    seen.wait(
        lambda observation: (
            titled(f"{page} ")(observation)
            and observation.context is not None
            and observation.context.address is None
        ),
        focused,
    )


@pytest.mark.integration
def test_a_page_in_full_screen_is_no_context_and_has_its_address_after(
    pages: Pages, seen: Seen, browser: Browser
) -> None:
    page = f"Jiffin video-{browser.app}"
    browser.open(pages.url(f"video-{browser.app}"))
    shown = seen.wait(titled(page))
    press(_VK_F)
    away = seen.wait(lambda observation: observation.context is None, after=shown + 1)
    press(_VK_ESCAPE)
    # Vivaldi builds a new address bar on the way out: the one read before is gone.
    back = seen.observations[seen.wait(titled(page), after=away + 1)].context
    assert back is not None
    assert back.address == f"{pages.host}/video-{browser.app}"


@pytest.mark.integration
def test_a_tab_that_records_gives_the_call_its_site(
    pages: Pages, seen: Seen, browser: Browser
) -> None:
    """With the microphone, for a few seconds: Windows shows its icon meanwhile. Vivaldi marks
    no tab that records: its calls count whole."""
    browser.open(pages.url(f"call-{browser.app}", records=True))
    seen.wait(titled(f"Jiffin call-{browser.app}"))
    site = browser.app if browser.app == "vivaldi.exe" else "127.0.0.1"
    seen.wait_situation(
        lambda observation: (
            observation.situation is Situation.CALL and observation.values == frozenset({site})
        )
    )


@pytest.mark.integration
def test_the_media_controls_and_the_networks_are_read_here() -> None:
    """On the owner's machine, where both answer: the ids only, never a name."""
    read: dict[str, frozenset[str]] = {}

    def run() -> None:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            media = Media()
            read["playing"] = media.playing()
            media.close()
            networks = Networks(lambda: None)
            read["connected"] = networks.connected()
            networks.close()
        finally:
            comtypes.CoUninitialize()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert all(app == app.lower() for app in read["playing"])
    assert all(len(network) == 36 and "{" not in network for network in read["connected"])


@pytest.mark.benchmark
def test_the_cpu_vivaldi_spends_on_the_reads(pages: Pages, tmp_path: Path) -> None:
    browser = start("vivaldi.exe", tmp_path)
    try:
        browser.open(pages.url("ticking", every_ms=1_000))
        time.sleep(10)
        without = measure(browser, BENCHMARK_SECONDS)
        seen = Seen()
        capture = Capture(SystemClock(), seen.add, lambda apps: None)
        own = psutil.Process()
        before = own.cpu_times()
        capture.start()
        try:
            with_reads = measure(browser, BENCHMARK_SECONDS)
        finally:
            capture.close()
        after = own.cpu_times()
    finally:
        browser.close()
    reads = sum(1 for observation in seen.observations if titled("Jiffin ticking")(observation))
    # A title that changes every second: at least 4 reads in 5 s, or the page left the front.
    assert reads >= BENCHMARK_SECONDS * 0.8
    jiffin = (after.user + after.system - before.user - before.system) / BENCHMARK_SECONDS
    cores = psutil.cpu_count() or 1
    print(
        f"\nVivaldi, {reads} reads in {BENCHMARK_SECONDS} s; CPU in percent of one core "
        f"(of the machine, {cores} logical cores):\n"
        f"  without reads   {100 * without:6.2f} ({100 * without / cores:5.2f})\n"
        f"  with reads      {100 * with_reads:6.2f} ({100 * with_reads / cores:5.2f})\n"
        f"  the difference  {100 * (with_reads - without):6.2f} "
        f"({100 * (with_reads - without) / cores:5.2f})\n"
        f"  this process    {100 * jiffin:6.2f} ({100 * jiffin / cores:5.2f})"
    )


def measure(browser: Browser, seconds: int) -> float:
    """The CPU the browser's processes spend, in cores, over `seconds`."""
    before = browser.cpu_seconds()
    time.sleep(seconds)
    after = browser.cpu_seconds()
    return sum(spent - before.get(pid, 0.0) for pid, spent in after.items()) / seconds
