"""`monitor`: what the app costs the machine during the acceptance day (ADR-0003, ADR-0017).

Every 5 s one row of numbers only: the CPU and RAM of the app, of its engine and of the
browsers, the GPU's memory in use and the battery. CPU is in percent of the whole machine, as
Task Manager shows it. RAM is the working set, which also counts the pages a process shares with
others: for the app's 2 GB threshold it errs on the safe side.
"""

import csv
import logging
import time
from collections.abc import Callable, Mapping, Sequence
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
COLUMNS = (
    "at",
    *(f"{group}_{measure}" for group in GROUPS for measure in ("cpu", "ram_mib")),
    "vram_used_mib",
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
    with path.open("a", newline="", encoding="utf-8") as file:
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
                row |= _gpu() | _battery()
                writer.writerow(row)
                file.flush()
                written += 1
                before, last = {process.pid: process for process in now_processes}, now
        except KeyboardInterrupt:
            pass
    log.info("%d rows written", written)
    return path


def _gpu() -> dict[str, object]:
    try:
        return {"vram_used_mib": gpu.memory().used_mib}
    except HarnessError as error:
        log.warning("%s", error)
        return {"vram_used_mib": ""}


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
