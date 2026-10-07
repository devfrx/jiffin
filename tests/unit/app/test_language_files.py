"""An app whose language files cannot be read says so in Windows' message box, in English: the
one message the files cannot hold (ADR-0026)."""

import subprocess
import sys
from pathlib import Path

START = """
import sys
from pathlib import Path

import jiffin.lang

jiffin.lang.FOLDER = Path(sys.argv[1])
from jiffin.app import main, win32

win32.show_error = print
main()
"""
"""The app's start, with an empty folder for its language and the message box printed."""


def test_language_files_that_cannot_be_read_end_the_start_with_a_message_in_english(
    tmp_path: Path,
) -> None:
    # A process of its own: this one read the files when it imported the app.
    started = subprocess.run(
        [sys.executable, "-c", START, str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert started.returncode == 1
    assert started.stdout.startswith("Jiffin cannot start: its language files cannot be read.")
    assert "texts.toml" in started.stdout
