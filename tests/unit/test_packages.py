import importlib

import pytest

PARTS = ["core", "protocol", "engine", "client", "platform", "store", "ui", "app", "harness"]


@pytest.mark.parametrize("part", PARTS)
def test_part_imports(part: str) -> None:
    importlib.import_module(f"jiffin.{part}")
