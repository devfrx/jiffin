from pathlib import Path

import pytest

from jiffin.harness import __main__ as harness


def test_a_command_is_required(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        harness.main([])
    assert "command" in capsys.readouterr().err


def test_the_data_folder_is_made_only_inside_a_parent_that_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "missing" / "prove"
    assert harness.main(["monitor", "--data", str(data)]) == 1
    assert "missing does not exist: pass --data" in capsys.readouterr().err
    assert not data.parent.exists()
