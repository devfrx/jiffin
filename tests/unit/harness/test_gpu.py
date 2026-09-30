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


def test_an_engine_waits_for_enough_free_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", answer("6500, 1692\n"))
    with pytest.raises(
        HarnessError, match="1692 MiB free, and an engine needs 4096: close the app"
    ):
        gpu.require_free()
    monkeypatch.setattr(subprocess, "run", answer("600, 7592\n"))
    gpu.require_free()
