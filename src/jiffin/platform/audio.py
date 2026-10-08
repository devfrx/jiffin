"""Core Audio, on the context thread: which apps capture from a microphone, and whether the
default output is headphones (ADR-0028).

A capture session is an app's use of one microphone: active while the app's stream runs. Windows
tells each change on a thread of its own: a session that starts, stops or appears, a microphone
or an output that comes, goes or becomes the default. Those calls only wake the context thread,
which reads again: a read of every microphone takes a few milliseconds (#123). Session events
reach a thread in the multithreaded apartment only, as the context thread is, and a session
manager sends them only once its sessions were counted.

The interfaces are transcribed from the Windows SDK headers `mmdeviceapi.h`, `audiopolicy.h` and
`propsys.h` (10.0.26100): every method up to the last one called, in their order, and every
method of the three Jiffin implements.
"""

import contextlib
import ctypes
import os
from collections.abc import Callable
from ctypes import POINTER, wintypes
from typing import Any, ClassVar

import comtypes
import comtypes.client
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

_CLSID_ENUMERATOR = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_RENDER, _CAPTURE = 0, 1
"""EDataFlow."""
_CONSOLE = 0
"""ERole."""
_DEVICE_STATE_ACTIVE = 0x1
_CLSCTX_ALL = 0x17
_STGM_READ = 0
_E_NOTFOUND = 0x80070490
"""HRESULT_FROM_WIN32(ERROR_NOT_FOUND): there is no default output."""
_E_DEVICE_INVALIDATED = 0x88890004
"""AUDCLNT_E_DEVICE_INVALIDATED: the device went away or was built again, as a Bluetooth
headset's when it connects (seen on the owner's laptop, #147)."""
_SESSION_ACTIVE, _SESSION_EXPIRED = 1, 2
"""AudioSessionState."""
_HEADPHONES, _HEADSET = 3, 5
"""EndpointFormFactor."""
_VT_UI4 = 19


class _PropertyKey(ctypes.Structure):
    _fields_ = (("fmtid", GUID), ("pid", wintypes.DWORD))


class _PropVariant(ctypes.Structure):
    _fields_ = (
        ("vt", wintypes.USHORT),
        ("reserved1", wintypes.WORD),
        ("reserved2", wintypes.WORD),
        ("reserved3", wintypes.WORD),
        ("value", ctypes.c_ulonglong * 2),
    )


_FORM_FACTOR = _PropertyKey(GUID("{1DA5D803-D492-4EDD-8C23-E0C0FFEE7F0E}"), 0)
"""PKEY_AudioEndpoint_FormFactor."""

_ole32 = ctypes.OleDLL("ole32")
_ole32.PropVariantClear.argtypes = [POINTER(_PropVariant)]
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.CoTaskMemFree.restype = None


class IPropertyStore(IUnknown):  # type: ignore[misc]  # comtypes has no types
    _iid_ = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.DWORD))),
        COMMETHOD([], HRESULT, "GetAt", (["in"], wintypes.DWORD), (["out"], POINTER(_PropertyKey))),
        COMMETHOD(
            [],
            HRESULT,
            "GetValue",
            (["in"], POINTER(_PropertyKey)),
            (["in"], POINTER(_PropVariant)),
        ),
    ]


class IMMDevice(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD(
            [],
            HRESULT,
            "Activate",
            (["in"], POINTER(GUID)),
            (["in"], wintypes.DWORD),
            (["in"], ctypes.c_void_p),
            (["out"], POINTER(POINTER(IUnknown))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OpenPropertyStore",
            (["in"], wintypes.DWORD),
            (["out"], POINTER(POINTER(IPropertyStore))),
        ),
        # A string Windows allocates for the caller: see _taken.
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(ctypes.c_void_p))),
    ]


class IMMDeviceCollection(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(wintypes.UINT))),
        COMMETHOD(
            [], HRESULT, "Item", (["in"], wintypes.UINT), (["out"], POINTER(POINTER(IMMDevice)))
        ),
    ]


class IMMNotificationClient(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{7991EEC9-7E89-4D85-8390-6C703CEC60C0}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD(
            [],
            HRESULT,
            "OnDeviceStateChanged",
            (["in"], wintypes.LPCWSTR),
            (["in"], wintypes.DWORD),
        ),
        COMMETHOD([], HRESULT, "OnDeviceAdded", (["in"], wintypes.LPCWSTR)),
        COMMETHOD([], HRESULT, "OnDeviceRemoved", (["in"], wintypes.LPCWSTR)),
        COMMETHOD(
            [],
            HRESULT,
            "OnDefaultDeviceChanged",
            (["in"], ctypes.c_int),
            (["in"], ctypes.c_int),
            (["in"], wintypes.LPCWSTR),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OnPropertyValueChanged",
            (["in"], wintypes.LPCWSTR),
            (["in"], _PropertyKey),
        ),
    ]


class IMMDeviceEnumerator(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD(
            [],
            HRESULT,
            "EnumAudioEndpoints",
            (["in"], ctypes.c_int),
            (["in"], wintypes.DWORD),
            (["out"], POINTER(POINTER(IMMDeviceCollection))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDefaultAudioEndpoint",
            (["in"], ctypes.c_int),
            (["in"], ctypes.c_int),
            (["out"], POINTER(POINTER(IMMDevice))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetDevice",
            (["in"], wintypes.LPCWSTR),
            (["out"], POINTER(POINTER(IMMDevice))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "RegisterEndpointNotificationCallback",
            (["in"], POINTER(IMMNotificationClient)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "UnregisterEndpointNotificationCallback",
            (["in"], POINTER(IMMNotificationClient)),
        ),
    ]


class IAudioSessionEvents(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{24918ACC-64B3-37C1-8CA9-74A66E9957A8}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD(
            [],
            HRESULT,
            "OnDisplayNameChanged",
            (["in"], wintypes.LPCWSTR),
            (["in"], POINTER(GUID)),
        ),
        COMMETHOD(
            [], HRESULT, "OnIconPathChanged", (["in"], wintypes.LPCWSTR), (["in"], POINTER(GUID))
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OnSimpleVolumeChanged",
            (["in"], ctypes.c_float),
            (["in"], wintypes.BOOL),
            (["in"], POINTER(GUID)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OnChannelVolumeChanged",
            (["in"], wintypes.DWORD),
            (["in"], POINTER(ctypes.c_float)),
            (["in"], wintypes.DWORD),
            (["in"], POINTER(GUID)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "OnGroupingParamChanged",
            (["in"], POINTER(GUID)),
            (["in"], POINTER(GUID)),
        ),
        COMMETHOD([], HRESULT, "OnStateChanged", (["in"], ctypes.c_int)),
        COMMETHOD([], HRESULT, "OnSessionDisconnected", (["in"], ctypes.c_int)),
    ]


class IAudioSessionControl(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{F4B1A599-7266-4319-A8CA-E70ACB11E8CD}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(ctypes.c_int))),
        COMMETHOD([], HRESULT, "GetDisplayName", (["out"], POINTER(ctypes.c_void_p))),
        COMMETHOD(
            [], HRESULT, "SetDisplayName", (["in"], wintypes.LPCWSTR), (["in"], POINTER(GUID))
        ),
        COMMETHOD([], HRESULT, "GetIconPath", (["out"], POINTER(ctypes.c_void_p))),
        COMMETHOD([], HRESULT, "SetIconPath", (["in"], wintypes.LPCWSTR), (["in"], POINTER(GUID))),
        COMMETHOD([], HRESULT, "GetGroupingParam", (["out"], POINTER(GUID))),
        COMMETHOD(
            [], HRESULT, "SetGroupingParam", (["in"], POINTER(GUID)), (["in"], POINTER(GUID))
        ),
        COMMETHOD(
            [],
            HRESULT,
            "RegisterAudioSessionNotification",
            (["in"], POINTER(IAudioSessionEvents)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "UnregisterAudioSessionNotification",
            (["in"], POINTER(IAudioSessionEvents)),
        ),
    ]


class IAudioSessionControl2(IAudioSessionControl):
    _iid_ = GUID("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetSessionIdentifier", (["out"], POINTER(ctypes.c_void_p))),
        COMMETHOD([], HRESULT, "GetSessionInstanceIdentifier", (["out"], POINTER(ctypes.c_void_p))),
        COMMETHOD([], HRESULT, "GetProcessId", (["out"], POINTER(wintypes.DWORD))),
    ]


class IAudioSessionNotification(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{641DD20B-4D41-49CC-ABA3-174B9477BB08}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "OnSessionCreated", (["in"], POINTER(IAudioSessionControl))),
    ]


class IAudioSessionEnumerator(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(ctypes.c_int))),
        COMMETHOD(
            [],
            HRESULT,
            "GetSession",
            (["in"], ctypes.c_int),
            (["out"], POINTER(POINTER(IAudioSessionControl))),
        ),
    ]


class IAudioSessionManager2(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
    _methods_: ClassVar[list[Any]] = [
        # IAudioSessionManager's two, not called.
        COMMETHOD(
            [],
            HRESULT,
            "GetAudioSessionControl",
            (["in"], POINTER(GUID)),
            (["in"], wintypes.DWORD),
            (["out"], POINTER(ctypes.c_void_p)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetSimpleAudioVolume",
            (["in"], POINTER(GUID)),
            (["in"], wintypes.DWORD),
            (["out"], POINTER(ctypes.c_void_p)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "GetSessionEnumerator",
            (["out"], POINTER(POINTER(IAudioSessionEnumerator))),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "RegisterSessionNotification",
            (["in"], POINTER(IAudioSessionNotification)),
        ),
        COMMETHOD(
            [],
            HRESULT,
            "UnregisterSessionNotification",
            (["in"], POINTER(IAudioSessionNotification)),
        ),
    ]


class _Listener(comtypes.COMObject):  # type: ignore[misc]
    """Every change Windows tells of the microphones, the outputs and the capture sessions calls
    `on_change`, on Windows' thread: it must not block, nor call Core Audio back."""

    _com_interfaces_: ClassVar[list[Any]] = [
        IMMNotificationClient,
        IAudioSessionNotification,
        IAudioSessionEvents,
    ]

    def __init__(self, on_change: Callable[[], None]) -> None:
        super().__init__()
        self._on_change = on_change

    def OnDeviceStateChanged(self, device: str, state: int) -> None:
        self._on_change()

    def OnDeviceAdded(self, device: str) -> None:
        self._on_change()

    def OnDeviceRemoved(self, device: str) -> None:
        self._on_change()

    def OnDefaultDeviceChanged(self, flow: int, role: int, device: str) -> None:
        self._on_change()

    def OnPropertyValueChanged(self, device: str, key: Any) -> None:
        """A volume, a name: nothing Jiffin reads."""

    def OnSessionCreated(self, session: Any) -> None:
        self._on_change()

    def OnDisplayNameChanged(self, name: str, context: Any) -> None:
        """Nothing Jiffin reads, as the four that follow."""

    def OnIconPathChanged(self, path: str, context: Any) -> None:
        pass

    def OnSimpleVolumeChanged(self, volume: float, mute: int, context: Any) -> None:
        pass

    def OnChannelVolumeChanged(self, count: int, volumes: Any, changed: int, context: Any) -> None:
        pass

    def OnGroupingParamChanged(self, grouping: Any, context: Any) -> None:
        pass

    def OnStateChanged(self, state: int) -> None:
        self._on_change()

    def OnSessionDisconnected(self, reason: int) -> None:
        self._on_change()


def _taken(address: int | None) -> str:
    """A string Windows allocated for the caller, read and freed."""
    if not address:
        return ""
    try:
        return ctypes.wstring_at(address)
    finally:
        _ole32.CoTaskMemFree(address)


class Audio:
    """Reads Core Audio on the thread that made it, which must be in the multithreaded
    apartment. `close` it on the same thread."""

    def __init__(self, on_change: Callable[[], None], enumerator: Any = None) -> None:
        """`on_change` runs on Windows' threads; `enumerator` stands in for Windows' own in the
        tests."""
        self._own = os.getpid()
        self._listener = _Listener(on_change)
        self._held: Any = self._listener.QueryInterface(IMMNotificationClient)
        """Keeps the listener alive until the close: Windows holds no reference to it for the
        endpoints, and comtypes forgets a COM object nobody holds."""
        self._enumerator: Any = enumerator or comtypes.client.CreateObject(
            _CLSID_ENUMERATOR, interface=IMMDeviceEnumerator
        )
        self._enumerator.RegisterEndpointNotificationCallback(self._listener)
        self._microphones: dict[str, Any] = {}
        """The session manager of each active microphone followed, by the endpoint's id."""
        self._sessions: dict[tuple[str, str], Any] = {}
        """The capture sessions followed, by their microphone's id and their instance's."""

    def capturing(self) -> frozenset[int]:
        """The processes whose stream from a microphone runs now, never the system's sounds or
        Jiffin's own. A microphone or a session seen for the first time is followed from now
        on, and those gone are left. A microphone built again, as a Bluetooth headset's when it
        connects, is followed again; one that goes away while it is read is passed over: its
        next change reads it."""
        microphones: dict[str, Any] = {}
        sessions: dict[tuple[str, str], Any] = {}
        running: set[int] = set()
        endpoints = self._enumerator.EnumAudioEndpoints(_CAPTURE, _DEVICE_STATE_ACTIVE)
        for index in range(endpoints.GetCount()):
            device = endpoints.Item(index)
            endpoint = _taken(device.GetId())
            try:
                running |= self._read(device, endpoint, microphones, sessions)
            except comtypes.COMError as error:
                if error.hresult & 0xFFFFFFFF != _E_DEVICE_INVALIDATED:
                    raise
        self._leave()
        self._microphones, self._sessions = microphones, sessions
        return frozenset(running)

    def headphones(self) -> bool:
        """Whether the default output is headphones or a headset; no output is not. An output
        built again while it is read is read once more."""
        try:
            return self._headphones()
        except comtypes.COMError as error:
            if error.hresult & 0xFFFFFFFF != _E_DEVICE_INVALIDATED:
                raise
            return self._headphones()

    def _read(
        self,
        device: Any,
        endpoint: str,
        microphones: dict[str, Any],
        sessions: dict[tuple[str, str], Any],
    ) -> set[int]:
        """The processes whose stream from this microphone runs; its manager and sessions go
        into `microphones` and `sessions`."""
        manager = self._microphones.pop(endpoint, None)
        listed = None
        if manager is not None:
            try:
                listed = manager.GetSessionEnumerator()
            except comtypes.COMError as error:
                if error.hresult & 0xFFFFFFFF != _E_DEVICE_INVALIDATED:
                    raise
                # Built again: its manager and sessions are those of the microphone gone.
                with contextlib.suppress(comtypes.COMError):
                    manager.UnregisterSessionNotification(self._listener)
                for key in [key for key in self._sessions if key[0] == endpoint]:
                    with contextlib.suppress(comtypes.COMError):
                        self._sessions.pop(key).UnregisterAudioSessionNotification(self._listener)
        if listed is None:
            manager = device.Activate(
                ctypes.byref(IAudioSessionManager2._iid_), _CLSCTX_ALL, None
            ).QueryInterface(IAudioSessionManager2)
            manager.RegisterSessionNotification(self._listener)
            listed = manager.GetSessionEnumerator()
        microphones[endpoint] = manager
        running: set[int] = set()
        for position in range(listed.GetCount()):  # counting turns its events on
            control = listed.GetSession(position).QueryInterface(IAudioSessionControl2)
            state = control.GetState()
            if state == _SESSION_EXPIRED:
                continue
            key = (endpoint, _taken(control.GetSessionInstanceIdentifier()))
            kept = self._sessions.pop(key, None)
            if kept is None:
                control.RegisterAudioSessionNotification(self._listener)
                kept = control
            sessions[key] = kept
            process = control.GetProcessId()
            if state == _SESSION_ACTIVE and process not in (0, self._own):
                running.add(process)
        return running

    def _headphones(self) -> bool:
        try:
            device = self._enumerator.GetDefaultAudioEndpoint(_RENDER, _CONSOLE)
        except comtypes.COMError as error:
            if error.hresult & 0xFFFFFFFF == _E_NOTFOUND:
                return False
            raise
        value = _PropVariant()
        device.OpenPropertyStore(_STGM_READ).GetValue(
            ctypes.byref(_FORM_FACTOR), ctypes.byref(value)
        )
        try:
            return value.vt == _VT_UI4 and value.value[0] & 0xFFFFFFFF in (_HEADPHONES, _HEADSET)
        finally:
            _ole32.PropVariantClear(ctypes.byref(value))

    def close(self) -> None:
        if self._enumerator is None:
            return
        with contextlib.suppress(comtypes.COMError):
            self._enumerator.UnregisterEndpointNotificationCallback(self._listener)
        self._leave()
        self._microphones.clear()
        self._sessions.clear()
        self._enumerator = self._held = None

    def _leave(self) -> None:
        """Stop following what `capturing` still holds: a session or a microphone gone, or all
        of them at the close. Unregistering one gone may fail: it tells nothing more anyway."""
        for control in self._sessions.values():
            with contextlib.suppress(comtypes.COMError):
                control.UnregisterAudioSessionNotification(self._listener)
        for manager in self._microphones.values():
            with contextlib.suppress(comtypes.COMError):
                manager.UnregisterSessionNotification(self._listener)
