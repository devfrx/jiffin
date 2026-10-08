import subprocess
from typing import Any

import pytest

from jiffin.harness import gpu
from jiffin.harness.errors import HarnessError


def answer(stdout: str) -> Any:
    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["nvidia-smi"], 0, stdout=stdout)

    return run


def test_the_memory_is_read_from_nvidia_smi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", answer("3312, 4880\n"))
    assert gpu.memory() == gpu.Memory(used_mib=3312, free_mib=4880)


def test_without_nvidia_smi_the_harness_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(HarnessError, match="nvidia-smi"):
        gpu.memory()


def test_the_counters_instances_are_summed_by_process_over_the_adapters() -> None:
    dedicated = {
        "pid_4120_luid_0x00000000_0x000185E0_phys_0": 3_000,
        "pid_4120_luid_0x00000000_0x000185AE_phys_0": 200,  # the integrated GPU's share
        "pid_77_luid_0x00000000_0x000185E0_phys_0": 5,
        "_Total": 9_999,
    }
    shared = {"pid_4120_luid_0x00000000_0x000185AE_phys_0": 40, "pid_8_luid_0x0_0x1_phys_0": 1}
    assert gpu.usage_by_process(dedicated, shared) == {
        4120: gpu.Usage(3_200, 40),
        77: gpu.Usage(5, 0),
        8: gpu.Usage(0, 1),
    }


def test_the_counters_read_each_process_or_say_why_not() -> None:
    """Windows' own counters: on a machine without a GPU they may be missing."""
    try:
        counters = gpu.Counters()
    except HarnessError as error:
        assert "PDH error" in str(error)
        return
    try:
        first, second = counters.read(), counters.read()
    finally:
        counters.close()
    counters.close()  # once is enough
    for memory in (first, second):
        assert all(used.dedicated >= 0 and used.shared >= 0 for used in memory.values())


def test_an_engine_waits_for_enough_free_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", answer("6500, 1692\n"))
    with pytest.raises(
        HarnessError, match="1692 MiB free, and an engine needs 4096: close the app"
    ):
        gpu.require_free()
    monkeypatch.setattr(subprocess, "run", answer("600, 7592\n"))
    gpu.require_free()
