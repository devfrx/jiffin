"""Build the app's installer (ADR-0015): PyInstaller, then Velopack's vpk.

    uv run --group package scripts/package.py [--version 0.1.1-rc.1]

It needs the llama.cpp runtime in `runtimes/` (`uv run scripts/fetch_llama_cpp.py`) and the .NET
SDK, for vpk. The app is built into `dist/Jiffin`; the release, with
`devfrx.Jiffin-win-Setup.exe`, goes to `releases/`, the folder the installed app updates from at
its start. Keep the earlier releases there: Velopack makes each new one as a delta of the last.
"""

import argparse
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
APP = ROOT / "dist" / "Jiffin"
RELEASES = ROOT / "releases"
PACK_ID = "devfrx.Jiffin"
"""Velopack installs into `%LOCALAPPDATA%\\devfrx.Jiffin`, apart from the data (ADR-0013); a
release with another id would be another app, which the installed one never updates to."""
NUGET = "https://api.nuget.org/v3/index.json"


def vpk() -> Path:
    """Velopack's packer, of the same version as the velopack the app imports, as Velopack asks;
    installed once under build/."""
    pinned = version("velopack")
    folder = BUILD / f"vpk-{pinned}"
    if not (folder / "vpk.exe").is_file():
        subprocess.run(
            ["dotnet", "tool", "install", "vpk", "--version", pinned]
            + ["--tool-path", str(folder), "--add-source", NUGET],
            check=True,
        )
    return folder / "vpk.exe"


def pack_arguments(release: str) -> list[str]:
    """`vpk pack`'s arguments: a per-user install, with a Start menu entry and start at login."""
    return [
        "pack",
        *("--packId", PACK_ID),
        *("--packVersion", release),
        *("--packTitle", "Jiffin"),
        *("--packAuthors", "devfrx"),
        *("--packDir", str(APP)),
        *("--runtime", "win-x64"),
        *("--mainExe", "Jiffin.exe"),
        *("--shortcuts", "StartMenuRoot,Startup"),
        "--noPortable",
        *("--outputDir", str(RELEASES)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the app's installer.")
    parser.add_argument("--version", default=version("jiffin"), help="default: the project's")
    release = parser.parse_args().version
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean"]
        + ["--distpath", str(APP.parent), "--workpath", str(BUILD / "pyinstaller")]
        + [str(ROOT / "scripts" / "jiffin.spec"), "--", "--releases", str(RELEASES)],
        check=True,
    )
    subprocess.run([str(vpk()), *pack_arguments(release)], check=True)


if __name__ == "__main__":
    main()
