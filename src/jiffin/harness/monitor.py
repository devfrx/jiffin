"""`monitor`: what the app costs the machine during the acceptance day (ADR-0003, ADR-0031).

Every 5 s one row of numbers only: the CPU and RAM of the app, of its engine and of the
browsers, the GPU memory of the app and of its engine, and the battery. CPU is in percent of the
whole machine, as Task Manager shows it. RAM is the working set, which also counts the pages a
process shares with others: for the app's 2 GB threshold it errs on the safe side. The GPU
memory comes from Windows' performance counters, which do not wake the card (ADR-0031):
dedicated, the VRAM of the 4.0 GiB threshold, and shared, in the system's memory.
"""

import csv
import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psutil

from jiffin.core.context import BROWSER_SUFFIXES
from jiffin.harness import gpu
from jiffin.harness.errors import HarnessError

log = logging.getLogger(__name__)

EVERY_SECONDS = 5.0
GROUPS = ("app", "engine", "browsers")
JIFFIN = ("app", "engine")
"""The groups whose GPU memory is read: the threshold is on the two together (ADR-0031)."""
GPU_COLUMNS = tuple(
    f"{group}_gpu_{kind}_mib" for group in JIFFIN for kind in ("dedicated", "shared")
)
COLUMNS = (
    "at",
    *(f"{group}_{measure}" for group in GROUPS for measure in ("cpu", "ram_mib")),
    *GPU_COLUMNS,
    "battery_percent",
    "plugged",
)
BROWSERS = frozenset(BROWSER_SUFFIXES)


@dataclass(frozen=True, slots=True)
class Process:
    pid: int
    group: str
    cpu_seconds: float
    """User and kernel time since the process started."""
    ram_bytes: int


def group_of(name: str, arguments: Sequence[str]) -> str | None:
    """Which part a process belongs to: packaged (ADR-0015), or run from a checkout."""
    name = name.lower()
    module = _module(arguments)
    if name == "jiffin-engine.exe" or module == "jiffin.engine":
        return "engine"
    if name == "jiffin.exe" or module in ("jiffin", "jiffin.app"):
        return "app"
    if name in BROWSERS:
        return "browsers"
    return None


def usage(
    before: Mapping[int, Process], now: Sequence[Process], seconds: float, cores: int
) -> dict[str, float]:
    """CPU in percent of the machine over the last `seconds`, and RAM in MiB, by group.

    A process that was not there before started meanwhile: all of its time is new.
    """
    cpu = dict.fromkeys(GROUPS, 0.0)
    ram = dict.fromkeys(GROUPS, 0)
    for process in now:
        earlier = before.get(process.pid)
        spent = process.cpu_seconds - (0.0 if earlier is None else earlier.cpu_seconds)
        cpu[process.group] += max(spent, 0.0)
        ram[process.group] += process.ram_bytes
    row = {}
    for group in GROUPS:
        row[f"{group}_cpu"] = round(100 * cpu[group] / (seconds * cores), 2)
        row[f"{group}_ram_mib"] = ram[group] >> 20
    return row


def gpu_usage(processes: Sequence[Process], memory: Mapping[int, gpu.Usage]) -> dict[str, int]:
    """The dedicated and shared GPU memory of the app and of its engine, in MiB. In a checkout
    each is a launcher and its child, the interpreter that holds the memory."""
    dedicated = dict.fromkeys(JIFFIN, 0)
    shared = dict.fromkeys(JIFFIN, 0)
    for process in processes:
        used = memory.get(process.pid)
        if process.group in JIFFIN and used is not None:
            dedicated[process.group] += used.dedicated
            shared[process.group] += used.shared
    row = {}
    for group in JIFFIN:
        row[f"{group}_gpu_dedicated_mib"] = dedicated[group] >> 20
        row[f"{group}_gpu_shared_mib"] = shared[group] >> 20
    return row


def processes() -> list[Process]:
    found = []
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            group = group_of(process.info["name"] or "", process.info["cmdline"] or [])
            if group is None:
                continue
            with process.oneshot():
                times = process.cpu_times()
                ram = process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        found.append(Process(process.pid, group, times.user + times.system, ram))
    return found


def run(
    folder: Path,
    every: float = EVERY_SECONDS,
    read: Callable[[], list[Process]] = processes,
    rows: int | None = None,
) -> Path:
    """Append rows to the day's CSV until Ctrl+C, or until `rows` are written."""
    path = folder / f"monitor-{datetime.now().astimezone():%Y-%m-%d}.csv"
    header = not path.exists()
    cores = psutil.cpu_count() or 1
    written = 0
    with path.open("a", newline="", encoding="utf-8") as file, _counters() as counters:
        writer = csv.DictWriter(file, COLUMNS)
        if header:
            writer.writeheader()
        before = {process.pid: process for process in read()}
        last = time.monotonic()
        due = last + every
        try:
            while rows is None or written < rows:
                time.sleep(max(0.0, due - time.monotonic()))
                due += every
                now_processes, now = read(), time.monotonic()
                row: dict[str, object] = {
                    "at": datetime.now().astimezone().isoformat("T", "seconds")
                }
                row |= usage(before, now_processes, now - last, cores)
                row |= _gpu(counters, now_processes)
                row |= _battery()
                writer.writerow(row)
                file.flush()
                written += 1
                before, last = {process.pid: process for process in now_processes}, now
        except KeyboardInterrupt:
            pass
    log.info("%d rows written", written)
    return path


@contextmanager
def _counters() -> Iterator[gpu.Counters | None]:
    """The GPU's counters for the whole run; None, and the columns empty, without them."""
    try:
        counters = gpu.Counters()
    except HarnessError as error:
        log.warning("%s: the GPU's columns stay empty", error)
        yield None
        return
    try:
        yield counters
    finally:
        counters.close()


def _gpu(counters: gpu.Counters | None, processes: Sequence[Process]) -> Mapping[str, object]:
    if counters is None:
        return dict.fromkeys(GPU_COLUMNS, "")
    try:
        return gpu_usage(processes, counters.read())
    except HarnessError as error:
        log.warning("%s", error)
        return dict.fromkeys(GPU_COLUMNS, "")


def _battery() -> dict[str, object]:
    battery = psutil.sensors_battery()
    if battery is None:
        return {"battery_percent": "", "plugged": ""}
    plugged = "" if battery.power_plugged is None else int(battery.power_plugged)
    return {"battery_percent": round(battery.percent), "plugged": plugged}


def _module(arguments: Sequence[str]) -> str | None:
    """The module a Python process runs with `-m`."""
    for index, argument in enumerate(arguments[:-1]):
        if argument == "-m":
            return arguments[index + 1]
    return None
