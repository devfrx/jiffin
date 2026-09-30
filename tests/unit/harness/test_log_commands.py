from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context, Observation
from jiffin.core.model import EngineBuild
from jiffin.core.records import Alert
from jiffin.core.reminders import Reminders
from jiffin.harness import __main__ as harness
from jiffin.harness import day as days
from jiffin.harness import labels, snapshot
from jiffin.store.store import Store

T0 = 1_791_194_400_000  # 2026-10-05 10:00 UTC
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
FIGMA = Context("figma", "Icone <nuove> - Figma", None)
BANK = Context("vivaldi", "Banca Rossi", "bancarossi.it")
MAIL = Context("outlook", "Posta in arrivo", None)
ICONS, RENT, POST = "quando apro Figma", "se sono sul sito della banca", "quando leggo la posta"
D = {(FIGMA, ICONS): 2.5, (BANK, RENT): 0.99, (MAIL, POST): 0.98}


class FakeModel:
    def build(self) -> EngineBuild:
        return BUILD

    def rewrite(self, condition: str) -> str:
        return f"The user: {condition}."

    def judge(self, context: Context, statements: Mapping[int, str]) -> dict[int, float]:
        return {
            key: D.get((context, text.removeprefix("The user: ").removesuffix(".")), 0.1)
            for key, text in statements.items()
        }


def a_day(database: Path) -> None:
    """Three reminders, three contexts and three alerts, through the app's own core and store."""
    clock = SimulatedClock(T0, UTC)
    core = Reminders(FakeModel(), clock, lambda view: None)
    store = Store.open(database)
    core.create(ICONS, "esportare le icone")
    core.create(RENT, "pagare l'affitto")
    core.create(POST, "rispondere a Rossi")
    for context in (FIGMA, BANK, MAIL):
        core.observe(Observation(clock.now(), context))
        clock.advance(20_000)
        core.poll()
        records = core.take_records()
        store.save(records)
        clock.advance(10_000)  # nobody answers: the alerts leave the screen
        for alert in records:
            if isinstance(alert, Alert) and alert.shown_at is not None:
                core.vanished(alert.id)
        store.save(core.take_records())
        clock.advance(120_000)
    store.close()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "app" / "jiffin.db"
    path.parent.mkdir()
    a_day(path)
    return path


def run(*arguments: str) -> int:
    return harness.main(list(arguments))


def test_a_day_goes_from_a_copy_to_its_report(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = str(tmp_path / "prove")
    assert run("snapshot", "--data", data, "--database", str(database)) == 0
    (copy,) = (tmp_path / "prove").glob("log-*.db")
    assert sorted(path.name for path in copy.parent.iterdir()) == [copy.name]  # one file

    assert run("statements", "--data", data) == 0
    statements = next(copy.parent.glob("statements-*.html")).read_text(encoding="utf-8")
    assert "quando apro Figma" in statements and "The user: quando apro Figma." in statements

    assert run("label", "--data", data) == 0
    path = labels.path_for(
        copy.parent, days.select(snapshot.read(copy), None, SimulatedClock(T0, UTC)).day
    )
    labelled = labels.load(path)
    assert len(labelled.pairs) == 9
    by_text = {(pair["title"], pair["condition"]): pair["key"] for pair in labelled.pairs}
    labelled.claude = dict.fromkeys(by_text.values(), False) | {
        by_text[(FIGMA.title, ICONS)]: True,
        by_text[(BANK.title, RENT)]: True,
        by_text[(MAIL.title, RENT)]: True,  # never alerted: missed
        by_text[(MAIL.title, POST)]: False,  # alerted: a false alarm
    }
    labelled.save()

    capsys.readouterr()
    assert run("report", "--data", data) == 0
    summary = capsys.readouterr().out
    assert "## Day 2026-10-05" in summary
    assert "3 evaluations in 0.1 hours" in summary
    assert (
        "| Delay from the context change to the alert, p95 | 20.0 s (p50 20.0 s) | at most 30 s | yes |"
        in summary
    )
    assert (
        "| Missed reminders: relevant pairs never shown | 33% (1 of 3) | at most 20% | no |"
        in summary
    )
    assert "| False alarms in the day | 1 | target 5, cap 10 | yes |" in summary
    assert "Alerts shown: 3: 2 right, 1 false alarms, 0 not labelled." in summary
    assert not any(text in summary for text in ("Figma", "Banca", "Posta", "quando"))
    detail = next(copy.parent.glob("report-*.html")).read_text(encoding="utf-8")
    assert "Icone &lt;nuove&gt; - Figma" in detail and "<nuove>" not in detail

    assert run("forget", "--data", data) == 0
    assert not list(copy.parent.glob("log-*"))


def test_a_copy_can_be_made_while_the_app_writes(database: Path, tmp_path: Path) -> None:
    app = Store.open(database)  # the app's connection, in WAL mode
    try:
        copy = snapshot.snapshot(database, tmp_path, datetime.now(UTC))
        assert len(snapshot.read(copy).evaluations) == 3
    finally:
        app.close()


def test_without_the_apps_database_or_a_copy_the_harness_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("snapshot", "--data", str(tmp_path), "--database", str(tmp_path / "none.db")) == 1
    assert "there is no database" in capsys.readouterr().err
    assert run("report", "--data", str(tmp_path)) == 1
    assert "run snapshot first" in capsys.readouterr().err
    assert run("label", "--data", str(tmp_path), "--owner") == 1
    assert "run label first" in capsys.readouterr().err


def test_a_report_without_labels_says_so(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = str(tmp_path / "prove")
    run("snapshot", "--data", data, "--database", str(database))
    capsys.readouterr()
    assert run("report", "--data", data) == 0
    summary = capsys.readouterr().out
    assert "No labels yet: run label." in summary
    assert "| False alarms in the day | no labels |  |  |" in summary


def test_the_report_reads_the_monitors_rows(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "prove"
    run("snapshot", "--data", str(data), "--database", str(database))
    rows = [
        "at,app_cpu,app_ram_mib,engine_cpu,engine_ram_mib,browsers_cpu,browsers_ram_mib,vram_used_mib,battery_percent,plugged",
        "2026-10-05T12:00:05+02:00,0.5,300,1.0,900,2.0,1500,3300,90,1",
        "2026-10-05T12:00:10+02:00,0.3,320,0.2,950,1.0,1500,3350,80,0",
    ]
    (data / "monitor-2026-10-05.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert run("report", "--data", str(data)) == 0
    summary = capsys.readouterr().out
    assert "| VRAM of the whole GPU, peak | 3,350 MiB | at most 4,096 MiB | yes |" in summary
    assert (
        "| RAM of the app and its engine, peak | 1,270 MiB | at most 1,907 MiB (2 GB) | yes |"
        in summary
    )
    assert (
        "| CPU of the app and its engine, average | 1.00% (browsers 1.50%) | under 5% | yes |"
        in summary
    )
    assert "| Battery | 90% to 80%, 50% of the time unplugged | reported |  |" in summary
