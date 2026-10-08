"""The GPU's memory: each process's from Windows' performance counters, for the monitor; the free
memory of the whole card from nvidia-smi, before an engine starts.

nvidia-smi wakes the card it asks, and on Windows it does not tell the memory of each process;
the counters do, and reading them leaves the card as it is (#121, ADR-0031). They are read
through PDH by their English names; structures and signatures are transcribed from the Windows
SDK headers `pdh.h` and `pdhmsg.h`.
"""

import ctypes
import subprocess
from collections.abc import Mapping
from ctypes import POINTER, wintypes
from dataclasses import dataclass
from typing import Any

from jiffin.harness.errors import HarnessError

MIN_FREE_MIB = 4096
"""Free memory an engine needs: the VRAM budget of the whole app (ADR-0003). One engine peaks at
about 3.3 GiB (ADR-0011), so two need about 6.4 of the 8 GiB (ADR-0017)."""

DEDICATED = r"\GPU Process Memory(*)\Dedicated Usage"
SHARED = r"\GPU Process Memory(*)\Shared Usage"

_FORMAT_LARGE = 0x00000400  # PDH_FMT_LARGE
_MORE_DATA = 0x800007D2  # PDH_MORE_DATA
_VALID = (0x00000000, 0x00000001)  # PDH_CSTATUS_VALID_DATA, PDH_CSTATUS_NEW_DATA
_TRIES = 3
"""Instances may come between asking the size of their array and reading it."""


@dataclass(frozen=True, slots=True)
class Memory:
    used_mib: int
    free_mib: int


@dataclass(frozen=True, slots=True)
class Usage:
    """The GPU memory a process holds, in bytes, on every adapter."""

    dedicated: int = 0
    """In the cards' own memory: VRAM."""
    shared: int = 0
    """In the system's memory, which the GPU reaches through the bus."""


class _Value(ctypes.Union):  # the union in PDH_FMT_COUNTERVALUE
    _fields_ = [
        ("longValue", wintypes.LONG),
        ("doubleValue", ctypes.c_double),
        ("largeValue", ctypes.c_longlong),
        ("AnsiStringValue", wintypes.LPCSTR),
        ("WideStringValue", wintypes.LPCWSTR),
    ]


class _CounterValue(ctypes.Structure):  # PDH_FMT_COUNTERVALUE
    _fields_ = [("CStatus", wintypes.DWORD), ("value", _Value)]


class _Item(ctypes.Structure):  # PDH_FMT_COUNTERVALUE_ITEM_W
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _CounterValue)]


# name -> (result, arguments)
_SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    "PdhOpenQueryW": (
        wintypes.DWORD,
        [wintypes.LPCWSTR, ctypes.c_size_t, POINTER(wintypes.HANDLE)],
    ),
    "PdhAddEnglishCounterW": (
        wintypes.DWORD,
        [wintypes.HANDLE, wintypes.LPCWSTR, ctypes.c_size_t, POINTER(wintypes.HANDLE)],
    ),
    "PdhCollectQueryData": (wintypes.DWORD, [wintypes.HANDLE]),
    "PdhGetFormattedCounterArrayW": (
        wintypes.DWORD,
        [
            wintypes.HANDLE,
            wintypes.DWORD,
            POINTER(wintypes.DWORD),
            POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ],
    ),
    "PdhCloseQuery": (wintypes.DWORD, [wintypes.HANDLE]),
}

_pdh = ctypes.WinDLL("pdh")
for _name, (_result, _arguments) in _SIGNATURES.items():
    _function = getattr(_pdh, _name)
    _function.restype, _function.argtypes = _result, _arguments


class Counters:
    """One query of the dedicated and shared GPU memory of every process, open until `close`."""

    def __init__(self) -> None:
        query = wintypes.HANDLE()
        _check(_pdh.PdhOpenQueryW(None, 0, ctypes.byref(query)), "open a query")
        self._query: wintypes.HANDLE | None = query
        try:
            self._dedicated = self._add(DEDICATED)
            self._shared = self._add(SHARED)
        except HarnessError:
            self.close()
            raise

    def read(self) -> dict[int, Usage]:
        """What each process holds now, by its id."""
        _check(_pdh.PdhCollectQueryData(self._query), "collect")
        return usage_by_process(_array(self._dedicated), _array(self._shared))

    def close(self) -> None:
        if self._query is not None:
            _pdh.PdhCloseQuery(self._query)
            self._query = None

    def _add(self, path: str) -> wintypes.HANDLE:
        counter = wintypes.HANDLE()
        status = _pdh.PdhAddEnglishCounterW(self._query, path, 0, ctypes.byref(counter))
        _check(status, f"add {path}")
        return counter


def usage_by_process(dedicated: Mapping[str, int], shared: Mapping[str, int]) -> dict[int, Usage]:
    """The counters' instances, `pid_<id>_luid_<adapter>_phys_<n>`, summed by process."""
    found: dict[int, Usage] = {}
    for name in dedicated.keys() | shared.keys():
        if (pid := _pid(name)) is not None:
            used = found.get(pid, Usage())
            found[pid] = Usage(
                used.dedicated + dedicated.get(name, 0), used.shared + shared.get(name, 0)
            )
    return found


def memory() -> Memory:
    query = ["nvidia-smi", "--query-gpu=memory.used,memory.free", "--format=csv,noheader,nounits"]
    try:
        output = subprocess.run(query, capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        raise HarnessError(f"nvidia-smi cannot tell the GPU's memory: {error}") from None
    used, free = output.stdout.splitlines()[0].split(",")
    return Memory(int(used), int(free))


def require_free(mib: int = MIN_FREE_MIB) -> None:
    """Stop before starting an engine that the GPU cannot hold: the app may be open."""
    free = memory().free_mib
    if free < mib:
        raise HarnessError(
            f"the GPU has {free} MiB free, and an engine needs {mib}: close the app first"
        )


def _array(counter: wintypes.HANDLE) -> dict[str, int]:
    """The value of each instance of a counter, after a collect: the first call tells the size
    of the array."""
    size, count = wintypes.DWORD(0), wintypes.DWORD(0)
    buffer: ctypes.Array[ctypes.c_byte] | None = None
    for _ in range(_TRIES):
        status = _pdh.PdhGetFormattedCounterArrayW(
            counter, _FORMAT_LARGE, ctypes.byref(size), ctypes.byref(count), buffer
        )
        if status != _MORE_DATA:
            break
        buffer = (ctypes.c_byte * size.value)()
    _check(status, "read the instances")
    if buffer is None:
        return {}
    items = ctypes.cast(buffer, POINTER(_Item))
    return {
        items[index].szName: int(items[index].FmtValue.value.largeValue)
        for index in range(count.value)
        if items[index].FmtValue.CStatus in _VALID
    }


def _check(status: int, doing: str) -> None:
    if status:
        raise HarnessError(f"the GPU's counters cannot {doing}: PDH error 0x{status:08X}")


def _pid(name: str) -> int | None:
    parts = name.split("_")
    if len(parts) > 1 and parts[0] == "pid" and parts[1].isdigit():
        return int(parts[1])
    return None
