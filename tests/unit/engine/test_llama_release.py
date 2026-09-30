from pathlib import Path

import pytest

from jiffin.engine import llama_release


def test_a_missing_runtime_says_how_to_fetch_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(llama_release, "RUNTIMES", tmp_path)
    with pytest.raises(FileNotFoundError, match="uv run scripts/fetch_llama_cpp.py"):
        llama_release.locate()
    directory = llama_release.install_dir()
    directory.mkdir()
    (directory / "llama.dll").touch()
    assert llama_release.locate() == directory
