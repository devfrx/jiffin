import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jiffin.core.context import Context, Observation
from jiffin.core.model import EngineBuild
from jiffin.harness import __main__ as harness
from jiffin.harness import capture, engine, snapshot
from jiffin.harness.errors import HarnessError

BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
CODE = r"C:\Users\rossi\AppData\Local\Programs\Microsoft VS Code\Code.exe"
VIVALDI = r"C:\Users\rossi\AppData\Local\Vivaldi\Application\vivaldi.exe"
ROWS: list[dict[str, Any]] = [
    {"ts": "2026-09-28T09:00:00.000+02:00", "type": "capture_start"},
    {
        "ts": "2026-09-28T09:00:01.000+02:00",
        "type": "context",
        "exe": CODE,
        "title": "● app.py - verdi - Visual Studio Code",
        "private": False,
    },
    {
        "ts": "2026-09-28T09:01:00.000+02:00",
        "type": "context",
        "exe": VIVALDI,
        "title": "Banca Rossi - Vivaldi",
        "address_bar": "https://www.bancarossi.it/conto?id=7",
        "private": False,
    },
    # Its privacy could not be told: title and address were not recorded.
    {"ts": "2026-09-28T09:02:00.000+02:00", "type": "context", "exe": VIVALDI, "title": None},
    {
        "ts": "2026-09-28T09:02:30.000+02:00",
        "type": "context",
        "exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "title": "Nuova scheda - Google Chrome",
        "address_bar": "banca ro",
        "address_bar_focused": True,
        "private": False,
    },
    {
        "ts": "2026-09-28T09:03:00.000+02:00",
        "type": "context",
        "exe": r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        "title": "Posta in arrivo - Outlook",
        "address_bar": "not a browser",
        "private": False,
    },
    {
        "ts": "2026-09-28T09:03:30.000+02:00",
        "type": "context",
        "exe": r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "title": None,
        "private": True,
    },
    {"ts": "2026-09-28T09:04:00.000+02:00", "type": "heartbeat"},
    {"ts": "2026-09-28T09:04:10.000+02:00", "type": "idle_start", "last_input": "x"},
]


def ms(ts: str) -> int:
    return round(datetime.fromisoformat(ts).timestamp() * 1000)


class FakeEngine:
    def build(self) -> EngineBuild:
        return BUILD

    def rewrite(self, condition: str) -> str:
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        return dict.fromkeys(statements, 2.0 if context.app == "vivaldi.exe" else -3.0)


@pytest.fixture
def day(tmp_path: Path) -> Path:
    path = tmp_path / "contesti-2026-09-28.jsonl"
    lines = [json.dumps(row) for row in ROWS] + ['{"ts": "2026-09-28T09:04:1']  # cut short
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_the_capture_is_read_with_the_apps_rules(day: Path) -> None:
    read = capture.read(day)
    assert read.observations == (
        Observation(ms(ROWS[0]["ts"]), None),
        Observation(
            ms(ROWS[1]["ts"]), Context("code.exe", "app.py - verdi - Visual Studio Code", None)
        ),
        Observation(
            ms(ROWS[2]["ts"]), Context("vivaldi.exe", "Banca Rossi", "bancarossi.it/conto")
        ),
        Observation(ms(ROWS[3]["ts"]), None),
        Observation(ms(ROWS[4]["ts"]), Context("chrome.exe", "Nuova scheda", None)),
        Observation(ms(ROWS[5]["ts"]), Context("outlook.exe", "Posta in arrivo - Outlook", None)),
        Observation(ms(ROWS[6]["ts"]), None),
    )
    assert read.end == ms(ROWS[-1]["ts"])


def test_a_capture_without_contexts_is_refused(tmp_path: Path) -> None:
    empty = tmp_path / "contesti.jsonl"
    empty.write_text(json.dumps(ROWS[0]), encoding="utf-8")
    with pytest.raises(HarnessError, match="holds no context"):
        capture.read(empty)


def test_the_day_becomes_a_copy_of_the_log(day: Path, tmp_path: Path) -> None:
    copy = tmp_path / "log-20260928-capture.db"
    reminders = [("se sono sul sito della banca", "pagare il bollo")]
    capture.convert(capture.read(day), reminders, FakeEngine(), copy)
    log = snapshot.read(copy)
    assert [evaluation.context.app for evaluation in log.evaluations] == [
        "code.exe",
        "vivaldi.exe",
        "chrome.exe",
        "outlook.exe",
    ]
    assert [alert.context.app for alert in log.alerts] == ["vivaldi.exe"]
    with pytest.raises(HarnessError, match="exists already"):
        capture.convert(capture.read(day), reminders, FakeEngine(), copy)


def test_the_command_judges_the_day_with_the_samples_reminders(
    day: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    @contextmanager
    def running(models: Path) -> Iterator[FakeEngine]:
        yield FakeEngine()

    monkeypatch.setattr(engine, "running", running)
    sample = tmp_path / "etichette.json"
    reminders = [
        {"id": "r1", "n": 1, "text": "se sono sul sito della banca, ricordami di pagare il bollo"}
    ]
    sample.write_text(json.dumps({"reminders": reminders}), encoding="utf-8")
    data = tmp_path / "prove"
    arguments = ["convert", str(day), "--data", str(data), "--sample", str(sample)]
    assert harness.main(arguments) == 0
    log = snapshot.read(data / "log-20260928-capture.db")
    assert {reminder.revision.action for reminder in log.reminders} == {"pagare il bollo"}
