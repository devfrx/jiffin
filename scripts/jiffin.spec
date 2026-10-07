# The packaged app (ADR-0015), built by scripts/package.py: PyInstaller in folder mode, with
# Jiffin.exe (windowed) and jiffin-engine.exe (console) sharing one folder of libraries.
#
#     pyinstaller scripts/jiffin.spec -- --releases <folder the installed app updates from>

import argparse
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

from jiffin.engine import llama_release

parser = argparse.ArgumentParser()
parser.add_argument("--releases", required=True)
releases = parser.parse_args().releases

ROOT = Path(SPECPATH).parent
SOURCE = Path(workpath) / "update-source.txt"
SOURCE.parent.mkdir(parents=True, exist_ok=True)
SOURCE.write_text(releases, encoding="utf-8")

# The libraries the engine loads, with their dependencies and license; not llama.cpp's programs
# and their libraries (*-impl, llama-common, mtmd), nor the RPC backend.
RUNTIME = llama_release.locate()
LLAMA = [
    (str(path), llama_release.PACKAGED)
    for pattern in (
        "llama.dll",
        "ggml.dll",
        "ggml-base.dll",
        "ggml-cpu-*.dll",
        "ggml-cuda.dll",
        "cu*.dll",
        "libomp.dll",
        "LICENSE-*",
    )
    for path in sorted(RUNTIME.glob(pattern))
]

# The evaluation harness never ships (ADR-0017), and neither do its texts (ADR-0026); nor does
# mypy, which pydantic's mypy plugin would bring from the development environment.
EXCLUDES = ["jiffin.harness", "jiffin.lang.harness", "mypy", "pydantic.mypy", "pydantic.v1.mypy"]

app = Analysis(
    [str(ROOT / "src" / "jiffin" / "__main__.py")],
    datas=[
        # Every file of the package that is not Python: the QML, the migrations and the language
        # files (ADR-0026), but the harness's.
        *collect_data_files("jiffin", excludes=["harness/**", "lang/it/harness.toml"]),
        (str(SOURCE), "jiffin/app"),
    ],
    excludes=EXCLUDES,
)
engine = Analysis(
    [str(ROOT / "src" / "jiffin" / "engine" / "__main__.py")],
    # `initialize` answers with the app's version, read from its metadata.
    datas=[*LLAMA, *copy_metadata("jiffin")],
    excludes=[*EXCLUDES, "PySide6"],
)
# PyInstaller collects the runtime's libraries again, as dependencies of one another, beside
# the app's own libraries: the engine loads them from their folder alone.
engine.binaries = [
    (name, source, kind)
    for name, source, kind in engine.binaries
    if not (Path(source).parent == RUNTIME and Path(name).parent == Path("."))
]

COLLECT(
    # No icon of our own yet, rather than PyInstaller's.
    EXE(
        PYZ(app.pure),
        app.scripts,
        exclude_binaries=True,
        name="Jiffin",
        console=False,
        icon="NONE",
        upx=False,
    ),
    app.binaries,
    app.datas,
    EXE(
        PYZ(engine.pure),
        engine.scripts,
        exclude_binaries=True,
        name="jiffin-engine",
        console=True,
        icon="NONE",
        upx=False,
    ),
    engine.binaries,
    engine.datas,
    name="Jiffin",
    upx=False,
)
