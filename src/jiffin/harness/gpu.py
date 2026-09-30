"""The GPU's memory, from nvidia-smi: on Windows it does not tell the memory of each process."""

import subprocess
from dataclasses import dataclass

from jiffin.harness.errors import HarnessError

MIN_FREE_MIB = 4096
"""Free memory an engine needs: the VRAM budget of the whole app (ADR-0003). One engine peaks at
about 3.3 GiB (ADR-0011), so two need about 6.4 of the 8 GiB (ADR-0017)."""


@dataclass(frozen=True, slots=True)
class Memory:
    used_mib: int
    free_mib: int


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
