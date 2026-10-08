"""The networks Windows is connected to, from the Network List Manager: by their id, never their
name (ADR-0028).

A network's id stays the same each time the PC joins it, so the settings can keep a label for it
(home or office) without its name. A read asks Windows' network service, about 2 ms (#147): the
manager's events wake the context thread, which reads again, instead of a read every second.
Its events reach a thread in the multithreaded apartment, as the context thread is.

The interfaces are transcribed from the Windows SDK header `netlistmgr.h` (10.0.26100): every
method up to the last one called, in their order, and all four of the events.
"""

import contextlib
import ctypes
from collections.abc import Callable
from ctypes import POINTER, wintypes
from typing import Any, ClassVar

import comtypes
import comtypes.client
from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
from comtypes.automation import IDispatch
from comtypes.connectionpoints import IConnectionPointContainer

_CLSID_MANAGER = GUID("{DCB00C01-570F-4A9B-8D69-199FDBA5723B}")
_CONNECTED = 0x1
"""NLM_ENUM_NETWORK_CONNECTED."""


class INetwork(IDispatch):  # type: ignore[misc]  # comtypes has no types
    _iid_ = GUID("{DCB00002-570F-4A9B-8D69-199FDBA5723B}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "GetName", (["out"], POINTER(comtypes.BSTR))),
        COMMETHOD([], HRESULT, "SetName", (["in"], comtypes.BSTR)),
        COMMETHOD([], HRESULT, "GetDescription", (["out"], POINTER(comtypes.BSTR))),
        COMMETHOD([], HRESULT, "SetDescription", (["in"], comtypes.BSTR)),
        COMMETHOD([], HRESULT, "GetNetworkId", (["out"], POINTER(GUID))),
    ]


class IEnumNetworks(IDispatch):  # type: ignore[misc]
    _iid_ = GUID("{DCB00003-570F-4A9B-8D69-199FDBA5723B}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "get__NewEnum", (["out"], POINTER(ctypes.c_void_p))),
        COMMETHOD(
            [],
            HRESULT,
            "Next",
            (["in"], wintypes.ULONG),
            (["out"], POINTER(POINTER(INetwork))),
            (["in", "out"], POINTER(wintypes.ULONG)),
        ),
    ]


class INetworkListManager(IDispatch):  # type: ignore[misc]
    _iid_ = GUID("{DCB00000-570F-4A9B-8D69-199FDBA5723B}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD(
            [],
            HRESULT,
            "GetNetworks",
            (["in"], ctypes.c_int),
            (["out"], POINTER(POINTER(IEnumNetworks))),
        ),
    ]


class INetworkEvents(IUnknown):  # type: ignore[misc]
    _iid_ = GUID("{DCB00004-570F-4A9B-8D69-199FDBA5723B}")
    _methods_: ClassVar[list[Any]] = [
        COMMETHOD([], HRESULT, "NetworkAdded", (["in"], GUID)),
        COMMETHOD([], HRESULT, "NetworkDeleted", (["in"], GUID)),
        COMMETHOD(
            [], HRESULT, "NetworkConnectivityChanged", (["in"], GUID), (["in"], ctypes.c_int)
        ),
        COMMETHOD([], HRESULT, "NetworkPropertyChanged", (["in"], GUID), (["in"], ctypes.c_int)),
    ]


class _Listener(comtypes.COMObject):  # type: ignore[misc]
    """A network joined, left or added calls `on_change`, on Windows' thread: it must not block."""

    _com_interfaces_: ClassVar[list[Any]] = [INetworkEvents]

    def __init__(self, on_change: Callable[[], None]) -> None:
        super().__init__()
        self._on_change = on_change

    def NetworkAdded(self, network: Any) -> None:
        self._on_change()

    def NetworkDeleted(self, network: Any) -> None:
        self._on_change()

    def NetworkConnectivityChanged(self, network: Any, connectivity: int) -> None:
        self._on_change()

    def NetworkPropertyChanged(self, network: Any, flags: int) -> None:
        """A name, a category: nothing Jiffin reads."""


class Networks:
    """Reads the Network List Manager on the thread that made it, which must be in the
    multithreaded apartment. `close` it on the same thread."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        """`on_change` runs on Windows' threads."""
        self._listener = _Listener(on_change)
        self._held: Any = self._listener.QueryInterface(INetworkEvents)
        """Keeps the listener alive until the close: comtypes forgets a COM object nobody
        holds."""
        self._manager: Any = comtypes.client.CreateObject(
            _CLSID_MANAGER, interface=INetworkListManager
        )
        self._point: Any = (
            self._manager.QueryInterface(IConnectionPointContainer)
        ).FindConnectionPoint(ctypes.byref(INetworkEvents._iid_))
        self._cookie: int | None = self._point.Advise(self._held)

    def connected(self) -> frozenset[str]:
        """The ids of the networks connected now, in lower case without braces; none offline."""
        found: set[str] = set()
        networks = self._manager.GetNetworks(_CONNECTED)
        while True:
            network, fetched = networks.Next(1, 0)
            if not fetched:
                return frozenset(found)
            found.add(str(network.GetNetworkId()).strip("{}").lower())

    def close(self) -> None:
        if self._cookie is not None:
            with contextlib.suppress(comtypes.COMError):
                self._point.Unadvise(self._cookie)
            self._cookie = None
        self._point = self._manager = self._held = None
