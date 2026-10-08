"""Core Audio's reader over an enumerator the test plays: its microphones, their capture sessions
and the default output (ADR-0028)."""

import ctypes
import os
from typing import Any

import comtypes
import pytest

from jiffin.platform.audio import Audio

_ole32 = ctypes.WinDLL("ole32")
_ole32.CoTaskMemAlloc.argtypes = [ctypes.c_size_t]
_ole32.CoTaskMemAlloc.restype = ctypes.c_void_p
ACTIVE, INACTIVE, EXPIRED = 1, 0, 2
SPEAKERS, HEADPHONES, HEADSET = 1, 3, 5
NOT_FOUND = comtypes.COMError(0x80070490 - 2**32, None, None)
INVALIDATED = comtypes.COMError(0x88890004 - 2**32, None, None)  # AUDCLNT_E_DEVICE_INVALIDATED
GONE = comtypes.COMError(0x800706BA - 2**32, None, None)  # RPC_S_SERVER_UNAVAILABLE


def allocated(text: str) -> int:
    """A string as Windows hands one to the caller, which frees it."""
    buffer = ctypes.create_unicode_buffer(text)
    address = _ole32.CoTaskMemAlloc(ctypes.sizeof(buffer))
    assert address
    ctypes.memmove(address, buffer, ctypes.sizeof(buffer))
    return int(address)


class Registry:
    """What is registered for the listener, by kind and id."""

    def __init__(self) -> None:
        self.held: set[tuple[str, str]] = set()
        self.registered: list[tuple[str, str]] = []
        self.failing = False

    def add(self, kind: str, name: str) -> None:
        self.registered.append((kind, name))
        self.held.add((kind, name))

    def remove(self, kind: str, name: str) -> None:
        if self.failing:
            raise GONE
        self.held.discard((kind, name))


class Session:
    def __init__(self, registry: Registry, name: str, process: int, state: int) -> None:
        self._registry = registry
        self.name = name
        self.process = process
        self.state = state

    def QueryInterface(self, interface: Any) -> "Session":
        return self

    def GetState(self) -> int:
        return self.state

    def GetSessionInstanceIdentifier(self) -> int:
        return allocated(self.name)

    def GetProcessId(self) -> int:
        return self.process

    def RegisterAudioSessionNotification(self, listener: Any) -> None:
        self._registry.add("session", self.name)

    def UnregisterAudioSessionNotification(self, listener: Any) -> None:
        self._registry.remove("session", self.name)


class Listed:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def GetCount(self) -> int:
        return len(self._items)

    def GetSession(self, index: int) -> Any:
        return self._items[index]

    def Item(self, index: int) -> Any:
        return self._items[index]


class Manager:
    """A microphone's session manager, as one activation gives it, until the microphone is built
    again."""

    def __init__(self, microphone: "Microphone") -> None:
        self._microphone = microphone
        self.error: comtypes.COMError | None = None

    def QueryInterface(self, interface: Any) -> "Manager":
        return self

    def RegisterSessionNotification(self, listener: Any) -> None:
        self._microphone.registry.add("microphone", self._microphone.name)

    def UnregisterSessionNotification(self, listener: Any) -> None:
        self._microphone.registry.remove("microphone", self._microphone.name)

    def GetSessionEnumerator(self) -> Listed:
        if self.error is not None:
            raise self.error
        return Listed(self._microphone.sessions)


class Microphone:
    """A microphone, and the managers of its sessions."""

    def __init__(self, registry: Registry, name: str, *sessions: Session) -> None:
        self.registry = registry
        self.name = name
        self.sessions = list(sessions)
        self.managers: list[Manager] = []
        self.going = False
        """It goes away while it is read."""

    def GetId(self) -> int:
        return allocated(self.name)

    def Activate(self, interface: Any, context: int, parameters: Any) -> Manager:
        if self.going:
            raise INVALIDATED
        self.managers.append(Manager(self))
        return self.managers[-1]

    def built_again(self) -> None:
        """As a Bluetooth headset's microphone when the headset connects."""
        for manager in self.managers:
            manager.error = INVALIDATED


class Output:
    """The default output, by the form factor its properties give; `rebuilding` reads fail with
    the device built again."""

    def __init__(self, form: int | None, rebuilding: int = 0) -> None:
        self.form = form
        self.rebuilding = rebuilding

    def OpenPropertyStore(self, access: int) -> "Output":
        if self.rebuilding:
            self.rebuilding -= 1
            raise INVALIDATED
        return self

    def GetValue(self, key: Any, value: Any) -> None:
        if self.form is not None:
            value._obj.vt = 19  # VT_UI4
            value._obj.value[0] = self.form


class Enumerator:
    def __init__(self) -> None:
        self.registry = Registry()
        self.microphones: list[Microphone] = []
        self.output: Output | None = Output(SPEAKERS)
        self.error: comtypes.COMError | None = None
        self.listener: Any = None
        """What Windows calls back."""

    def session(self, name: str, process: int, state: int = ACTIVE) -> Session:
        return Session(self.registry, name, process, state)

    def microphone(self, name: str, *sessions: Session) -> Microphone:
        self.microphones.append(Microphone(self.registry, name, *sessions))
        return self.microphones[-1]

    def RegisterEndpointNotificationCallback(self, listener: Any) -> None:
        self.listener = listener
        self.registry.add("endpoints", "")

    def UnregisterEndpointNotificationCallback(self, listener: Any) -> None:
        self.registry.remove("endpoints", "")

    def EnumAudioEndpoints(self, flow: int, states: int) -> Listed:
        return Listed(self.microphones)

    def GetDefaultAudioEndpoint(self, flow: int, role: int) -> Output:
        if self.error is not None:
            raise self.error
        if self.output is None:
            raise NOT_FOUND
        return self.output


@pytest.fixture
def windows() -> Enumerator:
    return Enumerator()


def test_the_processes_whose_microphone_stream_runs_capture(windows: Enumerator) -> None:
    windows.microphone(
        "array",
        windows.session("a", 11),
        windows.session("b", 22, INACTIVE),
        windows.session("c", 0),  # the system's sounds
        windows.session("d", os.getpid()),  # Jiffin's own
        windows.session("e", 33, EXPIRED),
    )
    windows.microphone("headset", windows.session("f", 44))
    audio = Audio(lambda: None, windows)
    assert audio.capturing() == {11, 44}
    audio.close()


def test_microphones_and_sessions_are_followed_once_and_left_when_gone(
    windows: Enumerator,
) -> None:
    array = windows.microphone("array", windows.session("a", 11), windows.session("e", 33, EXPIRED))
    headset = windows.microphone("headset", windows.session("f", 44))
    audio = Audio(lambda: None, windows)
    audio.capturing()
    audio.capturing()
    assert sorted(windows.registry.registered) == [
        ("endpoints", ""),
        ("microphone", "array"),
        ("microphone", "headset"),
        ("session", "a"),
        ("session", "f"),
    ]
    assert (len(array.managers), len(headset.managers)) == (1, 1)
    windows.microphones.remove(headset)  # unplugged
    array.sessions[0].state = EXPIRED  # its app closed
    array.sessions.append(windows.session("g", 55))
    assert audio.capturing() == {55}
    assert windows.registry.held == {("endpoints", ""), ("microphone", "array"), ("session", "g")}
    audio.close()
    assert windows.registry.held == set()


def test_a_microphone_built_again_is_followed_again(windows: Enumerator) -> None:
    """Seen on the owner's laptop: a Bluetooth headset that connects builds its microphone again,
    and the manager kept from before refuses every call."""
    headset = windows.microphone("headset", windows.session("f", 44))
    windows.microphone("array", windows.session("a", 11))
    audio = Audio(lambda: None, windows)
    audio.capturing()
    headset.built_again()
    assert audio.capturing() == {11, 44}
    assert len(headset.managers) == 2
    assert windows.registry.registered.count(("session", "f")) == 2  # on the new session
    assert audio.capturing() == {11, 44}
    assert len(headset.managers) == 2


def test_a_microphone_going_away_while_read_is_passed_over(windows: Enumerator) -> None:
    windows.microphone("array", windows.session("a", 11))
    windows.microphone("headset", windows.session("f", 44)).going = True
    assert Audio(lambda: None, windows).capturing() == {11}


def test_another_failure_of_a_microphone_fails_the_read(windows: Enumerator) -> None:
    headset = windows.microphone("headset", windows.session("f", 44))
    audio = Audio(lambda: None, windows)
    audio.capturing()
    headset.managers[0].error = GONE  # the audio service has gone
    with pytest.raises(comtypes.COMError):
        audio.capturing()


def test_a_failed_unregistration_is_passed_over(windows: Enumerator) -> None:
    windows.microphone("array", windows.session("a", 11))
    audio = Audio(lambda: None, windows)
    audio.capturing()
    windows.registry.failing = True  # the audio service has gone
    audio.close()
    audio.close()


@pytest.mark.parametrize(
    ("form", "headphones"),
    [(HEADPHONES, True), (HEADSET, True), (SPEAKERS, False), (None, False)],
    ids=["headphones", "headset", "speakers", "no form"],
)
def test_headphones_are_the_form_of_the_default_output(
    windows: Enumerator, form: int | None, headphones: bool
) -> None:
    windows.output = Output(form)
    assert Audio(lambda: None, windows).headphones() is headphones


def test_no_output_is_no_headphones_and_other_errors_raise(windows: Enumerator) -> None:
    windows.output = None
    audio = Audio(lambda: None, windows)
    assert audio.headphones() is False
    windows.error = GONE
    with pytest.raises(comtypes.COMError):
        audio.headphones()


def test_an_output_built_again_while_read_is_read_once_more(windows: Enumerator) -> None:
    windows.output = Output(HEADPHONES, rebuilding=1)
    audio = Audio(lambda: None, windows)
    assert audio.headphones() is True
    windows.output = Output(HEADPHONES, rebuilding=2)
    with pytest.raises(comtypes.COMError):
        audio.headphones()


def test_windows_calls_back_on_every_change_jiffin_reads(windows: Enumerator) -> None:
    changes: list[str] = []
    Audio(lambda: changes.append("changed"), windows)
    listener = windows.listener
    listener.OnDeviceStateChanged("a", 1)
    listener.OnDeviceAdded("a")
    listener.OnDeviceRemoved("a")
    listener.OnDefaultDeviceChanged(0, 0, "a")
    listener.OnSessionCreated(None)
    listener.OnStateChanged(ACTIVE)
    listener.OnSessionDisconnected(0)
    assert len(changes) == 7
    listener.OnSimpleVolumeChanged(0.5, 0, None)  # nothing Jiffin reads
    listener.OnPropertyValueChanged("a", None)
    listener.OnDisplayNameChanged("Zoom", None)
    assert len(changes) == 7
