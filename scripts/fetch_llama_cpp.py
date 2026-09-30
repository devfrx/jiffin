"""Fetch the pinned llama.cpp runtime of the engine into `runtimes/` (ADR-0011).

Run it once in a checkout, and again whenever the pin in `jiffin.engine.llama_release` changes:

    uv run scripts/fetch_llama_cpp.py

About 575 MB are downloaded. Each archive is checked against the sha256 recorded in the
repository before it is unpacked; a file that does not match is deleted.
"""

import hashlib
import shutil
import urllib.request
import zipfile
from pathlib import Path

from jiffin.engine import llama_release


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url: str, target: Path, sha256: str) -> Path:
    """Download to `target` unless a verified copy is already there; never keep a bad file."""
    if target.is_file() and sha256_file(target) == sha256:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    print(f"Downloading {target.name}...", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)
    digest = sha256_file(partial)
    if digest != sha256:
        partial.unlink()
        raise ValueError(f"{target.name}: sha256 mismatch (expected {sha256}, got {digest})")
    partial.replace(target)
    return target


def install() -> Path:
    """Download, verify and unpack the pinned runtime; nothing to do when it is there."""
    directory = llama_release.install_dir()
    if (directory / llama_release.LIBRARY_NAME).is_file():
        return directory
    staging = directory.with_name(directory.name + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    for name, sha256 in llama_release.PACKAGE:
        archive = fetch(
            f"{llama_release.BASE_URL}/{name}", llama_release.RUNTIMES / "downloads" / name, sha256
        )
        # zipfile keeps every member inside the destination on its own.
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
    if not (staging / llama_release.LIBRARY_NAME).is_file():
        raise ValueError(f"{llama_release.LIBRARY_NAME} is not in the llama.cpp package")
    staging.replace(directory)
    return directory


if __name__ == "__main__":
    print(f"llama.cpp {llama_release.RELEASE} is in {install()}")
