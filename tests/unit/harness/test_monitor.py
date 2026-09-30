import csv
from pathlib import Path

import psutil
import pytest

from jiffin.harness import __main__ as harness
from jiffin.harness import gpu, monitor
from jiffin.harness.errors import HarnessError
from jiffin.harness.monitor import Process, group_of, usage


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


def test_the_monitor_appends_rows_of_numbers_to_the_days_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gpu, "memory", lambda: gpu.Memory(used_mib=3300, free_mib=4892))
    monkeypatch.setattr(psutil, "sensors_battery", lambda: None)
    readings = iter([[Process(1, "app", float(n), 64 << 20)] for n in range(10)])
    path = monitor.run(tmp_path, every=0.01, read=lambda: next(readings), rows=2)
    path = monitor.run(tmp_path, every=0.01, read=lambda: next(readings), rows=1)
    with path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert path.name.startswith("monitor-") and path.suffix == ".csv"
    assert len(rows) == 3  # one header only, though the monitor ran twice
    assert set(rows[0]) == set(monitor.COLUMNS)
    assert rows[0]["app_ram_mib"] == "64"
    assert rows[0]["vram_used_mib"] == "3300"
    assert rows[0]["battery_percent"] == rows[0]["plugged"] == ""


def test_a_missing_gpu_leaves_its_column_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_gpu() -> gpu.Memory:
        raise HarnessError("nvidia-smi cannot tell the GPU's memory")

    monkeypatch.setattr(gpu, "memory", no_gpu)
    path = monitor.run(tmp_path, every=0.01, read=list, rows=1)
    with path.open(encoding="utf-8") as file:
        assert next(csv.DictReader(file))["vram_used_mib"] == ""


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
