from pathlib import Path

import pytest

from jiffin.store.folders import Folders


def test_the_app_keeps_its_data_in_its_own_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")
    folders = Folders.app()
    assert folders.root == Path(r"C:\Users\someone\AppData\Local\Jiffin")
    assert (folders.database.name, folders.logs.name, folders.models.name) == (
        "jiffin.db",
        "logs",
        "models",
    )
    assert {folders.database.parent, folders.logs.parent, folders.models.parent} == {folders.root}
