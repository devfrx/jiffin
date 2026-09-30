"""A Job Object that ends its processes when it closes, even when the app crashes (ADR-0011).

A process joins a job only if its parent was in the job when it was created. In a checkout the
engine runs behind uv's `python.exe`, a launcher that starts the real interpreter as its child,
so the engine is created suspended, put in its job, and only then resumed: the order that the
process-wrap crate follows too. The packaged `jiffin-engine.exe` has no launcher.

Structures and signatures are transcribed from the Windows SDK headers `winnt.h`, `jobapi2.h`,
`processthreadsapi.h` and `tlhelp32.h`.
"""

import ctypes
from ctypes import POINTER, c_size_t, c_ulonglong, c_void_p, wintypes
from typing import Any

CREATE_SUSPENDED = 0x00000004
KILLED = 1
"""The exit code of the processes a job ends, as `Popen.kill` gives on Windows."""

_KILL_ON_JOB_CLOSE = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
_EXTENDED_LIMIT_INFORMATION = 9  # JOBOBJECTINFOCLASS JobObjectExtendedLimitInformation
_PROCESS_SET_QUOTA, _PROCESS_TERMINATE = 0x0100, 0x0001
_THREAD_SUSPEND_RESUME = 0x0002
_SNAPSHOT_THREADS = 0x00000004  # TH32CS_SNAPTHREAD
_INVALID_HANDLE = c_void_p(-1).value
_RESUME_FAILED = 0xFFFFFFFF


class _BasicLimits(ctypes.Structure):  # JOBOBJECT_BASIC_LIMIT_INFORMATION
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", c_size_t),
        ("MaximumWorkingSetSize", c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):  # IO_COUNTERS
    _fields_ = [
        ("ReadOperationCount", c_ulonglong),
        ("WriteOperationCount", c_ulonglong),
        ("OtherOperationCount", c_ulonglong),
        ("ReadTransferCount", c_ulonglong),
        ("WriteTransferCount", c_ulonglong),
        ("OtherTransferCount", c_ulonglong),
    ]


class _ExtendedLimits(ctypes.Structure):  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", c_size_t),
        ("JobMemoryLimit", c_size_t),
        ("PeakProcessMemoryUsed", c_size_t),
        ("PeakJobMemoryUsed", c_size_t),
    ]


class _ThreadEntry(ctypes.Structure):  # THREADENTRY32
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD),
        ("tpBasePri", wintypes.LONG),
        ("tpDeltaPri", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
    ]


# name -> (result, arguments)
_SIGNATURES: dict[str, tuple[Any, list[Any]]] = {
    "CreateJobObjectW": (wintypes.HANDLE, [c_void_p, wintypes.LPCWSTR]),
    "SetInformationJobObject": (
        wintypes.BOOL,
        [wintypes.HANDLE, ctypes.c_int, c_void_p, wintypes.DWORD],
    ),
    "AssignProcessToJobObject": (wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
    "TerminateJobObject": (wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT]),
    "OpenProcess": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
    "CreateToolhelp32Snapshot": (wintypes.HANDLE, [wintypes.DWORD, wintypes.DWORD]),
    "Thread32First": (wintypes.BOOL, [wintypes.HANDLE, POINTER(_ThreadEntry)]),
    "Thread32Next": (wintypes.BOOL, [wintypes.HANDLE, POINTER(_ThreadEntry)]),
    "OpenThread": (wintypes.HANDLE, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
    "ResumeThread": (wintypes.DWORD, [wintypes.HANDLE]),
    "CloseHandle": (wintypes.BOOL, [wintypes.HANDLE]),
}

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
for _name, (_result, _arguments) in _SIGNATURES.items():
    _function = getattr(_kernel32, _name)
    _function.restype, _function.argtypes = _result, _arguments


class Job:
    """A Job Object: every process in it ends when it closes, or when the app ends."""

    def __init__(self) -> None:
        handle = _kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        size = ctypes.sizeof(limits)
        if not _kernel32.SetInformationJobObject(
            handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), size
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            _kernel32.CloseHandle(handle)
            raise error
        self._handle: int | None = handle

    def start(self, pid: int) -> None:
        """Put a process created with CREATE_SUSPENDED in the job, then let it run.

        Whatever it starts from then on is in the job too.
        """
        process = _kernel32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not _kernel32.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            _kernel32.CloseHandle(process)
        _resume(pid)

    def close(self) -> None:
        """End every process still in the job, with exit code KILLED, and let the job go."""
        if self._handle is None:
            return
        # Closing the last handle would end them too, with no say on the exit code.
        _kernel32.TerminateJobObject(self._handle, KILLED)
        _kernel32.CloseHandle(self._handle)
        self._handle = None


def _resume(pid: int) -> None:
    """Resume the threads of a process created suspended: Popen keeps no handle to them."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_SNAPSHOT_THREADS, 0)
    if snapshot == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    resumed = 0
    try:
        entry = _ThreadEntry(dwSize=ctypes.sizeof(_ThreadEntry))
        found = _kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == pid:
                thread = _kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, entry.th32ThreadID)
                if not thread:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    if _kernel32.ResumeThread(thread) == _RESUME_FAILED:
                        raise ctypes.WinError(ctypes.get_last_error())
                finally:
                    _kernel32.CloseHandle(thread)
                resumed += 1
            found = _kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snapshot)
    if not resumed:
        raise OSError(f"process {pid} has no thread to resume")
