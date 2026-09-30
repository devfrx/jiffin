# Derived from Rizzo Flow, src/rizzo_flow/llama_release.py at commit b9ba007e
# (https://github.com/Rizzo-AI-Academy/rizzo-flow). Copyright 2026 Simone Rizzo — Rizzo AI
# Academy. Licensed under the Apache License, Version 2.0.
# Changed for Jiffin: only the Windows CUDA package is pinned, and the download lives in
# scripts/fetch_llama_cpp.py.
"""Pinned llama.cpp runtime: the official Windows CUDA package, verified by sha256 (ADR-0011).

Nothing is compiled. `scripts/fetch_llama_cpp.py` fetches the release archives from
github.com/ggml-org/llama.cpp and unpacks them under `runtimes/`. The ctypes layouts in
`llama_cpp.py` are transcribed from the header of exactly this release, so changing `RELEASE`
means checking `llama.h` field by field, and measuring again (ADR-0006).
"""

from pathlib import Path

RELEASE = "b11081"
COMMIT = "161755f29e415e2c33efe906e91843c068efd664"
BASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}"
# Archives to unpack into one directory, with their sha256: the CUDA runtime ships apart.
PACKAGE = (
    (
        "llama-b11081-bin-win-cuda-13.4-x64.zip",
        "fefb4d9751d36cbb5b82042729470fddf3a47841aa8c91025cd7de1dc2767e58",
    ),
    (
        "cudart-llama-bin-win-cuda-13.4-x64.zip",
        "738f8c251ac22b70c3ae6f83a10cf222725df0395246a2cf58f32bdb85fbe668",
    ),
)
LIBRARY_NAME = "llama.dll"
# In a checkout, `src/jiffin/engine` sits three levels below the repository.
RUNTIMES = Path(__file__).resolve().parents[3] / "runtimes"


def install_dir() -> Path:
    return RUNTIMES / f"llama-{RELEASE}-win32-x64-cuda"


def locate() -> Path:
    """The directory holding llama.dll and the libraries beside it."""
    directory = install_dir()
    if not (directory / LIBRARY_NAME).is_file():
        raise FileNotFoundError(
            f"llama.cpp {RELEASE} is not installed in {directory}; "
            "run `uv run scripts/fetch_llama_cpp.py`"
        )
    return directory
