"""The app as the owner starts it, `python -m jiffin` (#44) or the installed `Jiffin.exe` (#45),
with the real engine on the GPU, the real context capture and the real screen: a reminder written
with Win+Shift+N alerts once a window it is about has stayed in front for 5 s, and Done on the
alert completes it.

It runs only on the owner's machine, with `uv run pytest -m integration
tests/integration/test_app.py`, and skips without the model in the `NO_GIT` folder beside the
repository, or for the installed app when Jiffin is not installed. A Jiffin already running, the
installed one started at login among them, must be closed with Quit first. For about a minute
per app it shows a window in front of everything, presses Win+Shift+N, types a reminder and
clicks the alert: leave the computer alone meanwhile, and any window or dialog that shows up too.
The app keeps its data in a temporary folder, never in the owner's.
"""

import ctypes
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from ctypes import POINTER, wintypes
from pathlib import Path
from typing import Any

import comtypes.client
import pytest

from jiffin.app.root import INSTANCE
from jiffin.client.model_file import MODEL
from jiffin.core.reminders import THRESHOLD
from jiffin.lang.texts import TEXTS

pytestmark = pytest.mark.integration

PINNED = (
    Path(__file__).resolve().parents[3] / "NO_GIT" / "rizzo-flow" / "models" / "rizzo-flow"
) / MODEL.name
INSTALLED = Path(os.environ["LOCALAPPDATA"]) / "devfrx.Jiffin" / "current"
"""Where Velopack installs the app (ADR-0015)."""
TITLE = "Lista della spesa"
CONDITION, ACTION = "quando scrivo la lista della spesa", "comprare il latte"
"""The real judge gives this reminder d = 3.1 in a window with that title (measured for #44)."""
TARGET = [sys.executable, str(Path(__file__).with_name("target_window.py")), TITLE]
WAIT_S = 90.0
"""The longest any step may take: the engine's start is the slowest."""


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


# name -> (result, arguments)
_USER32: dict[str, tuple[Any, list[Any]]] = {
    "SendInput": (wintypes.UINT, [wintypes.UINT, POINTER(_Input), ctypes.c_int]),
    "GetSystemMetrics": (ctypes.c_int, [ctypes.c_int]),
    "GetForegroundWindow": (wintypes.HWND, []),
    "GetWindowThreadProcessId": (wintypes.DWORD, [wintypes.HWND, POINTER(wintypes.DWORD)]),
    "GetWindowRect": (wintypes.BOOL, [wintypes.HWND, POINTER(wintypes.RECT)]),
    "WindowFromPoint": (wintypes.HWND, [wintypes.POINT]),
    "GetAncestor": (wintypes.HWND, [wintypes.HWND, wintypes.UINT]),
    "GetClassNameW": (ctypes.c_int, [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]),
    "SetWindowPos": (
        wintypes.BOOL,
        [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ],
    ),
    "PostMessageW": (
        wintypes.BOOL,
        [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
    ),
}

_user32 = ctypes.WinDLL("user32", use_last_error=True)
for _name, (_result, _arguments) in _USER32.items():
    _function = getattr(_user32, _name)
    _function.restype, _function.argtypes = _result, _arguments
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.restype, _kernel32.CloseHandle.argtypes = wintypes.BOOL, [wintypes.HANDLE]

_UIA: Any = comtypes.client.GetModule("UIAutomationCore.dll")

_INPUT_MOUSE, _INPUT_KEYBOARD = 0, 1
_KEYEVENTF_KEYUP, _KEYEVENTF_UNICODE = 0x0002, 0x0004
_VK_TAB, _VK_RETURN, _VK_SHIFT, _VK_LWIN = 0x09, 0x0D, 0x10, 0x5B
_MOUSEEVENTF_MOVE, _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP = 0x0001, 0x0002, 0x0004
_MOUSEEVENTF_VIRTUALDESK, _MOUSEEVENTF_ABSOLUTE = 0x4000, 0x8000
_SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN = 76, 77
_SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 78, 79
_WM_CLOSE = 0x0010
_SYNCHRONIZE = 0x00100000
_HWND_TOPMOST, _HWND_NOTOPMOST = -1, -2
_SWP_NOSIZE, _SWP_NOMOVE, _SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
_GA_ROOT = 2


def _send(events: list[_Input]) -> None:
    batch = (_Input * len(events))(*events)
    sent = _user32.SendInput(len(events), batch, ctypes.sizeof(_Input))
    assert sent == len(events), f"SendInput: {ctypes.WinError(ctypes.get_last_error())}"


def move_mouse(x: int, y: int) -> None:
    """Move the mouse as a real one does, to physical pixels."""
    left = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)
    top = _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
    width = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)
    height = _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
    event = _Input(type=_INPUT_MOUSE)
    event.u.mi = _MouseInput(
        round((x - left) * 65535 / (width - 1)),
        round((y - top) * 65535 / (height - 1)),
        0,
        _MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE | _MOUSEEVENTF_VIRTUALDESK,
        0,
        0,
    )
    _send([event])


def click(hwnd: int, x: int, y: int) -> None:
    """Click at a point of `hwnd`, only if it is the window there: never on another app."""
    under = _user32.WindowFromPoint(wintypes.POINT(x, y)) or 0
    assert (_user32.GetAncestor(under, _GA_ROOT) or 0) == hwnd, "another window is there"
    move_mouse(x, y)
    events = [_Input(type=_INPUT_MOUSE), _Input(type=_INPUT_MOUSE)]
    events[0].u.mi.dwFlags = _MOUSEEVENTF_LEFTDOWN
    events[1].u.mi.dwFlags = _MOUSEEVENTF_LEFTUP
    _send(events)


def type_text(text: str) -> None:
    """Characters to the foreground window, as a keyboard types them."""
    events = []
    for character in text:
        for flags in (_KEYEVENTF_UNICODE, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP):
            event = _Input(type=_INPUT_KEYBOARD)
            event.u.ki = _KeyboardInput(0, ord(character), flags, 0, 0)
            events.append(event)
    _send(events)


def press(*keys: int) -> None:
    """Keys held down in order, then let go."""
    events = []
    for key, flags in [(key, 0) for key in keys] + [(key, _KEYEVENTF_KEYUP) for key in keys[::-1]]:
        event = _Input(type=_INPUT_KEYBOARD)
        event.u.ki = _KeyboardInput(key, 0, flags, 0, 0)
        events.append(event)
    _send(events)


def foreground() -> int:
    return _user32.GetForegroundWindow() or 0


def process_of(hwnd: int) -> int:
    process = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
    return process.value


def class_name(hwnd: int) -> str:
    name = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, name, len(name))
    return name.value


def running() -> bool:
    """A Jiffin holds its mutex: one the test starts would leave at once."""
    handle = _kernel32.OpenMutexW(_SYNCHRONIZE, False, INSTANCE)
    if handle:
        _kernel32.CloseHandle(handle)
    return bool(handle)


def wait_for(what: str, condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        assert time.monotonic() < deadline, f"no {what} within {WAIT_S:g} s"
        time.sleep(0.2)


def automation() -> Any:
    return comtypes.client.CreateObject(_UIA.CUIAutomation, interface=_UIA.IUIAutomation)


def focused() -> str:
    """The name a screen reader gives what has the keyboard focus."""
    element = automation().GetFocusedElement()
    return str(element.CurrentName) if element else ""


def button(process: int, name: str) -> tuple[int, int, int] | None:
    """The top-level window of `process` with a button called `name`, and the button's centre in
    physical pixels, as a screen reader finds them."""
    uia = automation()
    owned = uia.CreatePropertyCondition(_UIA.UIA_ProcessIdPropertyId, process)
    windows = uia.GetRootElement().FindAll(_UIA.TreeScope_Children, owned)
    named = uia.CreatePropertyCondition(_UIA.UIA_NamePropertyId, name)
    for index in range(windows.Length):
        window = windows.GetElement(index)
        found = window.FindFirst(_UIA.TreeScope_Descendants, named)
        if found:
            box = found.CurrentBoundingRectangle
            centre = ((box.left + box.right) // 2, (box.top + box.bottom) // 2)
            return int(window.CurrentNativeWindowHandle), *centre
    return None


class App:
    """The app, started by `command`, with its data in a folder of its own and the pinned model
    in place."""

    def __init__(self, data: Path, command: list[str]) -> None:
        self.folder = data / "Jiffin"
        models = self.folder / "models"
        models.mkdir(parents=True)
        os.link(PINNED, models / MODEL.name)  # the same file, without a copy of 2.4 GB
        self._process = subprocess.Popen(
            command,
            env={**os.environ, "LOCALAPPDATA": str(data)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def log(self) -> str:
        path = self.folder / "logs" / "jiffin.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def count(self, table: str, where: str = "1") -> int:
        """Rows in a table, read as the harness reads them while the app runs."""
        database = (self.folder / "jiffin.db").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(database, uri=True)) as db:
            return int(db.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0])

    def end(self) -> None:
        """The app and the engine, with the interpreter that `uv`'s python.exe starts in a
        checkout."""
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(self._process.pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        self._process.wait(10)


class Target:
    """A window titled like the reminder's document, in a process of its own like any app."""

    def __init__(self) -> None:
        self._process = subprocess.Popen(TARGET, stdout=subprocess.PIPE, text=True)
        assert self._process.stdout is not None
        self.window, self.box = (int(handle) for handle in self._process.stdout.readline().split())

    def front(self) -> None:
        """Click in its text box, as the user would; for the click it is on top of every other
        window, so that the click cannot reach another app."""
        found = wintypes.RECT()
        assert _user32.GetWindowRect(self.box, ctypes.byref(found))
        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
        assert _user32.SetWindowPos(self.window, _HWND_TOPMOST, 0, 0, 0, 0, flags)
        click(self.window, (found.left + found.right) // 2, (found.top + found.bottom) // 2)
        assert _user32.SetWindowPos(self.window, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    def close(self) -> None:
        _user32.PostMessageW(self.window, _WM_CLOSE, 0, 0)
        try:
            self._process.wait(10)
        except subprocess.TimeoutExpired:
            self._process.kill()


@pytest.fixture(params=["checkout", "installed"])
def app(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[App]:
    if not PINNED.is_file():
        pytest.skip(f"the model is not in {PINNED.parent}")
    command = [sys.executable, "-m", "jiffin"]
    if request.param == "installed":
        installed = INSTALLED / "Jiffin.exe"
        if not installed.is_file():
            pytest.skip(f"Jiffin is not installed in {INSTALLED}")
        command = [str(installed)]
    assert not running(), "a Jiffin is running: close it with Esci from its tray icon's menu"
    started = App(tmp_path, command)
    yield started
    started.end()


@pytest.fixture
def target() -> Iterator[Target]:
    started = Target()
    yield started
    started.close()


def test_python_m_jiffin_runs_the_whole_loop(app: App, target: Target) -> None:
    wait_for("engine", lambda: " ready: llama.cpp " in app.log())
    assert "the shortcut is not registered" not in app.log(), "another app holds Win+Shift+N"
    target.front()
    wait_for("target window in front", lambda: foreground() == target.window)
    press(_VK_LWIN, _VK_SHIFT, ord("N"))
    wait_for(
        "creation window",
        lambda: (
            class_name(foreground()).startswith("Qt")
            and process_of(foreground()) != process_of(target.window)
        ),
    )
    jiffin = process_of(foreground())
    wait_for("focus in the Quando box", lambda: focused() == TEXTS.creation.condition)
    type_text(CONDITION)
    press(_VK_TAB)
    type_text(ACTION)
    press(_VK_RETURN)
    wait_for("target window back in front", lambda: foreground() == target.window)
    wait_for("alert", lambda: app.count("alert", "shown_at IS NOT NULL") == 1)
    time.sleep(1)  # it enters in 250 ms, moving: its buttons settle first
    wait_for("Fatto on the alert", lambda: button(jiffin, TEXTS.alert.done) is not None)
    done = button(jiffin, TEXTS.alert.done)
    assert done is not None
    click(*done)
    wait_for("answer", lambda: app.count("alert", "answer = 'done'") == 1)

    assert app.count("reminder", "completed_at IS NOT NULL") == 1
    assert app.count("revision", "statement IS NOT NULL AND statement_build IS NOT NULL") == 1
    assert app.count("candidate", f"outcome = 'alert' AND d >= {THRESHOLD}") == 1
    # The alert came from the window in front, as the context capture saw it.
    alerted = "id = (SELECT evaluation FROM alert)"
    in_front = f"context = (SELECT id FROM context WHERE app = 'python.exe' AND title = '{TITLE}')"
    assert app.count("evaluation", f"{alerted} AND {in_front}") == 1
    log = app.log()
    for words in (TITLE, CONDITION, ACTION):
        assert words.lower() not in log.lower(), "the app log holds only ids and numbers"
