"""The installer's build (#45): what it asks of Velopack (ADR-0015)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "package.py"


@pytest.fixture
def package() -> ModuleType:
    spec = importlib.util.spec_from_file_location("package", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_release_installs_for_the_user_with_the_start_menu_and_at_login(
    package: ModuleType,
) -> None:
    arguments = package.pack_arguments("0.1.0")

    def given(option: str) -> str:
        return str(arguments[arguments.index(option) + 1])

    assert given("--packId") == "devfrx.Jiffin"  # the installed app updates only within its id
    assert given("--packVersion") == "0.1.0"
    assert given("--mainExe") == "Jiffin.exe"
    assert given("--shortcuts") == "StartMenuRoot,Startup"
    assert given("--outputDir") == str(package.RELEASES)
