"""Windows' media controls, through WinRT with ctypes alone: which apps play now (ADR-0028).

An app that plays through Windows' media controls, as a browser's video or a music app does, has
a session there with a status. Jiffin reads only the app's id and whether it plays, never a
title or an artist. An app that does not use the controls (a game, some players) is not seen:
`away` may then come in front of it, and the return rings, a mistake that shows. The apps whose
sound runs, from Core Audio, would keep `away` off wherever a stream runs silent, and the return
would never ring: a mistake nobody sees (#147).

The calls go through combase, with the vtable slots of the SDK header
`winrt/windows.media.control.h` (10.0.26100), as #123 tried them; no package is needed, and a
read of every session takes about 0.03 ms. Run on a thread in the multithreaded apartment.
"""

import ctypes
import time
import uuid
from ctypes import POINTER, wintypes
from typing import Any

_combase = ctypes.WinDLL("combase")
_combase.WindowsCreateString.argtypes = [
    wintypes.LPCWSTR,
    wintypes.UINT,
    POINTER(ctypes.c_void_p),
]
_combase.WindowsCreateString.restype = ctypes.HRESULT
_combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
_combase.WindowsDeleteString.restype = ctypes.HRESULT
_combase.WindowsGetStringRawBuffer.argtypes = [ctypes.c_void_p, POINTER(wintypes.UINT)]
_combase.WindowsGetStringRawBuffer.restype = wintypes.LPCWSTR
_combase.RoGetActivationFactory.argtypes = [
    ctypes.c_void_p,
    ctypes.c_void_p,
    POINTER(ctypes.c_void_p),
]
_combase.RoGetActivationFactory.restype = ctypes.HRESULT

_CLASS = "Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager"
_IID_STATICS = uuid.UUID("2050c4ee-11a0-57de-aed7-c97c70338245")
_IID_ASYNC_INFO = uuid.UUID("00000036-0000-0000-c000-000000000046")
_FIRST = 6
"""The first slot after IInspectable's six: QueryInterface, AddRef, Release, GetIids,
GetRuntimeClassName and GetTrustLevel."""
_RELEASE = 2
_REQUEST_ASYNC = _FIRST  # IGlobalSystemMediaTransportControlsSessionManagerStatics
_GET_RESULTS = _FIRST + 2  # IAsyncOperation: put_Completed, get_Completed, GetResults
_GET_STATUS = _FIRST + 1  # IAsyncInfo: get_Id, get_Status
_GET_SESSIONS = _FIRST + 1  # the manager: GetCurrentSession, GetSessions
_GET_AT, _GET_SIZE = _FIRST, _FIRST + 1  # IVectorView
_GET_APP = _FIRST  # a session: get_SourceAppUserModelId
_GET_PLAYBACK_INFO = _FIRST + 3  # a session, after TryGetMediaPropertiesAsync, GetTimeline...
_GET_PLAYBACK_STATUS = _FIRST + 1  # its playback info: get_Controls, get_PlaybackStatus
_STARTED, _COMPLETED = 0, 1
"""AsyncStatus."""
_PLAYING = 4
"""GlobalSystemMediaTransportControlsSessionPlaybackStatus."""
_POLL_SECONDS = 0.005


def _guid(value: uuid.UUID) -> ctypes.Array[ctypes.c_char]:
    return ctypes.create_string_buffer(value.bytes_le, 16)


def _call(pointer: int | None, slot: int, types: list[Any], *arguments: Any) -> None:
    """Call a method by its slot in the object's vtable; a failed HRESULT raises OSError."""
    if not pointer:
        raise OSError("a WinRT object is missing")
    table = ctypes.cast(pointer, POINTER(POINTER(ctypes.c_void_p))).contents
    method = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *types)(table[slot])
    method(pointer, *arguments)


def _release(pointer: int | None) -> None:
    if pointer:
        table = ctypes.cast(pointer, POINTER(POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[_RELEASE])(pointer)


def _out(pointer: int | None, slot: int, kind: Any = ctypes.c_void_p, *arguments: Any) -> Any:
    """A method whose last parameter is its result."""
    result = kind()
    _call(pointer, slot, [*(type(a) for a in arguments), POINTER(kind)], *arguments, result)
    return result.value


def _text(string: int | None) -> str:
    """An HSTRING's text; the HSTRING is deleted."""
    if not string:
        return ""
    try:
        return _combase.WindowsGetStringRawBuffer(string, None) or ""
    finally:
        _combase.WindowsDeleteString(string)


class Media:
    """Windows' media sessions, on the thread that made it. `close` it on the same thread."""

    def __init__(self, timeout_ms: int = 2000) -> None:
        """Raises OSError when Windows has no media controls, or does not answer in time."""
        name = ctypes.c_void_p()
        _combase.WindowsCreateString(_CLASS, len(_CLASS), ctypes.byref(name))
        statics = ctypes.c_void_p()
        try:
            _combase.RoGetActivationFactory(name, _guid(_IID_STATICS), ctypes.byref(statics))
        finally:
            _combase.WindowsDeleteString(name)
        operation = info = None
        try:
            operation = _out(statics.value, _REQUEST_ASYNC)
            info = ctypes.c_void_p()
            _call(
                operation,
                0,  # QueryInterface
                [ctypes.c_char_p, POINTER(ctypes.c_void_p)],
                _guid(_IID_ASYNC_INFO),
                ctypes.byref(info),
            )
            deadline = time.monotonic() + timeout_ms / 1000
            while (status := _out(info.value, _GET_STATUS, ctypes.c_int)) == _STARTED:
                if time.monotonic() > deadline:
                    raise OSError("Windows' media controls did not answer")
                time.sleep(_POLL_SECONDS)
            if status != _COMPLETED:
                raise OSError(f"Windows' media controls failed: status {status}")
            self._manager: int | None = _out(operation, _GET_RESULTS)
        finally:
            _release(info.value if info else None)
            _release(operation)
            _release(statics.value)

    def playing(self) -> frozenset[str]:
        """The apps whose session plays now, by their app id in lower case, as `spotify.exe`
        or `vivaldi.<id>`."""
        if self._manager is None:
            return frozenset()
        found: set[str] = set()
        sessions = _out(self._manager, _GET_SESSIONS)
        try:
            for index in range(_out(sessions, _GET_SIZE, wintypes.UINT)):
                session = _out(sessions, _GET_AT, ctypes.c_void_p, wintypes.UINT(index))
                info = None
                try:
                    info = _out(session, _GET_PLAYBACK_INFO)
                    if _out(info, _GET_PLAYBACK_STATUS, ctypes.c_int) == _PLAYING:
                        found.add(_text(_out(session, _GET_APP)).lower())
                finally:
                    _release(info)
                    _release(session)
        finally:
            _release(sessions)
        return frozenset(found)

    def close(self) -> None:
        _release(self._manager)
        self._manager = None
