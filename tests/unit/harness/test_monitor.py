import csv
from pathlib import Path

import psutil
import pytest

from jiffin.harness import __main__ as harness
from jiffin.harness import gpu, monitor
from jiffin.harness.errors import HarnessError
from jiffin.harness.monitor import Process, gpu_usage, group_of, usage

MIB = 1 << 20


class Counters:
    """Windows' counters, as the engine and the app would hold the GPU's memory."""

    def __init__(self) -> None:
        self.closed = False

    def read(self) -> dict[int, gpu.Usage]:
        return {1: gpu.Usage(300 * MIB, 20 * MIB), 2: gpu.Usage(3_100 * MIB, 90 * MIB)}

    def close(self) -> None:
        self.closed = True


class NoCounters:
    def __init__(self) -> None:
        raise HarnessError("the GPU's counters cannot add a counter: PDH error 0xC0000BB8")


@pytest.mark.parametrize(
    ("name", "arguments", "group"),
    [
        ("Jiffin.exe", [], "app"),
        ("jiffin-engine.exe", [], "engine"),
        ("python.exe", ["python.exe", "-m", "jiffin"], "app"),
        ("uv.exe", ["uv", "run", "python", "-m", "jiffin"], "app"),
        ("python.exe", ["python.exe", "-m", "jiffin.engine"], "engine"),
        ("python.exe", ["python.exe", "-m", "jiffin.harness", "monitor"], None),
        ("python.exe", ["python.exe", "-m"], None),
        ("vivaldi.exe", [], "browsers"),
        ("Chrome.exe", [], "browsers"),
        ("brave.exe", [], "browsers"),
        ("msedge.exe", [], None),
    ],
)
def test_processes_are_told_apart_by_name_or_by_module(
    name: str, arguments: list[str], group: str | None
) -> None:
    assert group_of(name, arguments) == group


def test_cpu_is_in_percent_of_the_machine_and_ram_in_mib() -> None:
    before = {1: Process(1, "app", 10.0, 0), 2: Process(2, "browsers", 100.0, 0)}
    now = [
        Process(1, "app", 12.0, 300 << 20),
        Process(2, "browsers", 101.0, 500 << 20),
        Process(3, "browsers", 1.0, 200 << 20),  # started meanwhile: all its time is new
        Process(4, "engine", 3.0, 1024 << 20),
    ]
    assert usage(before, now, seconds=5.0, cores=4) == {
        "app_cpu": 10.0,
        "app_ram_mib": 300,
        "engine_cpu": 15.0,
        "engine_ram_mib": 1024,
        "browsers_cpu": 10.0,
        "browsers_ram_mib": 700,
    }


def test_a_reused_process_id_never_gives_negative_time() -> None:
    usage_row = usage({7: Process(7, "app", 50.0, 0)}, [Process(7, "app", 1.0, 0)], 5.0, 1)
    assert usage_row["app_cpu"] == 0.0


def test_the_gpu_memory_of_the_app_and_its_engine_is_summed_over_their_processes() -> None:
    running = [
        Process(1, "app", 0.0, 0),
        Process(2, "engine", 0.0, 0),  # a checkout's launcher, which holds nothing
        Process(3, "engine", 0.0, 0),  # and the interpreter it started
        Process(4, "browsers", 0.0, 0),
    ]
    memory = {
        1: gpu.Usage(150 * MIB, 40 * MIB),
        3: gpu.Usage(3_247 * MIB, 101 * MIB),
        4: gpu.Usage(900 * MIB, 300 * MIB),  # the browsers' are not read
        9: gpu.Usage(6_000 * MIB, 0),  # nor a game's
    }
    assert gpu_usage(running, memory) == {
        "app_gpu_dedicated_mib": 150,
        "app_gpu_shared_mib": 40,
        "engine_gpu_dedicated_mib": 3_247,
        "engine_gpu_shared_mib": 101,
    }


def test_the_monitor_appends_rows_of_numbers_to_the_days_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Counters] = []

    def counters() -> Counters:
        opened.append(Counters())
        return opened[-1]

    monkeypatch.setattr(gpu, "Counters", counters)
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    readings = iter(
        [[Process(1, "app", float(n), 64 * MIB), Process(2, "engine", 0.0, 0)] for n in range(10)]
    )
    path = monitor.run(tmp_path, every=0.01, read=lambda: next(readings), rows=2)
    path = monitor.run(tmp_path, every=0.01, read=lambda: next(readings), rows=1)
    assert [counters.closed for counters in opened] == [True, True]
    with path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert path.name.startswith("monitor-") and path.suffix == ".csv"
    assert len(rows) == 3  # one header only, though the monitor ran twice
    assert set(rows[0]) == set(monitor.COLUMNS)
    assert rows[0]["app_ram_mib"] == "64"
    assert (rows[0]["app_gpu_dedicated_mib"], rows[0]["app_gpu_shared_mib"]) == ("300", "20")
    assert (rows[0]["engine_gpu_dedicated_mib"], rows[0]["engine_gpu_shared_mib"]) == ("3100", "90")
    assert rows[0]["battery_percent"] == rows[0]["plugged"] == ""


def test_without_the_gpus_counters_their_columns_stay_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(gpu, "Counters", NoCounters)
    path = monitor.run(tmp_path, every=0.01, read=list, rows=2)
    with path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert [row[column] for row in rows for column in monitor.GPU_COLUMNS] == [""] * 8
    assert caplog.text.count("PDH error") == 1  # said once, not every row


def test_a_row_the_counters_cannot_read_leaves_its_gpu_columns_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Failing(Counters):
        def read(self) -> dict[int, gpu.Usage]:
            raise HarnessError("the GPU's counters cannot collect: PDH error 0x800007D5")

    monkeypatch.setattr(gpu, "Counters", Failing)
    path = monitor.run(tmp_path, every=0.01, read=list, rows=1)
    with path.open(encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    assert [row[column] for column in monitor.GPU_COLUMNS] == [""] * 4
    assert row["app_cpu"] == "0.0"


def test_the_command_writes_into_the_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def run(folder: Path, every: float) -> Path:
        calls.append((folder, every))
        return folder / "monitor.csv"

    monkeypatch.setattr(monitor, "run", run)
    assert harness.main(["monitor", "--data", str(tmp_path), "--every", "2.5"]) == 0
    assert calls == [(tmp_path, 2.5)]
