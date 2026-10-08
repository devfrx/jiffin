from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from jiffin.core.clock import SimulatedClock, SystemClock
from jiffin.core.context import Context, Observation
from jiffin.core.model import EngineBuild
from jiffin.core.records import (
    Alert,
    Answer,
    Candidate,
    EngineSleep,
    Evaluation,
    Outcome,
    Revision,
    SleepReason,
    Waker,
)
from jiffin.core.reminders import Reminders
from jiffin.harness import __main__ as harness
from jiffin.harness import day as days
from jiffin.harness import labels, monitor, report, sleeps, snapshot, statements
from jiffin.lang.harness import HARNESS
from jiffin.store.store import Log, Store

T0 = 1_791_194_400_000  # 2026-10-05 10:00 UTC
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
FIGMA = Context("figma.exe", "Icone <nuove> - Figma", None)
BANK = Context("vivaldi.exe", "Banca Rossi", "bancarossi.it")
MAIL = Context("outlook.exe", "Posta in arrivo", None)
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
    core = Reminders(FakeModel(), clock, lambda view: None, lambda view: None)
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
    by_text = {(pair["title"], pair["remainder"]): pair["key"] for pair in labelled.pairs}
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
    assert "3 reminders judged, with a return pause of 2 min." in summary
    assert "| Measure | Value | Threshold (ADR-0031) | Within |" in summary
    assert (
        "| Delay from when the alert became due, p95 | 20.0 s (p50 20.0 s) | at most 30 s | yes |"
        in summary
    )
    assert (
        "| Missed reminders: relevant pairs never shown, unless kept quiet as already reminded "
        "| 33% (1 of 3) | at most 20% | no |"
    ) in summary
    assert "| False alarms in the day, once per pair | 1 | target 10, cap 20 | yes |" in summary
    assert "Alerts shown: 3, on 3 pairs: 2 right, 1 wrong, 0 not labelled." in summary
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
    assert "| False alarms in the day, once per pair | no labels |  |  |" in summary


def test_the_statements_page_shows_the_time_understood_and_the_remainder(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    core = Reminders(FakeModel(), clock, lambda view: None, lambda view: None)
    core.create("quando apro Figma dopo le 23", "salvare il file")
    core.create("alle 15", "chiamare Rossi")
    core.create("quando apro Figma verso sera", "chiudere le tavole")
    store = Store.open(tmp_path / "jiffin.db")
    store.save(core.take_records())
    log = store.log()
    store.close()
    text = statements.page(log, tmp_path / "log.db", tmp_path, clock).read_text(encoding="utf-8")
    assert "Dalle 23:00 alle 04:00" in text and "Alle 15:00" in text
    assert "The user: quando apro Figma." in text  # from the remainder, without its time
    assert "solo orario" in text  # "alle 15" has no remainder, and no statement
    assert "non capito: «verso sera»" in text


def test_the_summary_counts_the_alerts_with_only_a_time_apart(tmp_path: Path) -> None:
    summary = days.Summary(
        day=date(2026, 10, 5),
        evaluations=10,
        judged=5,
        failed=0,
        hours=1.0,
        reminders=3,
        pauses=(120_000, 10_000),
        shown=14,
        time_only=2,
        delays=(5.0,),
        pairs=20,
        labelled=20,
        relevant=5,
        missed={},
        reminded={},
        alerted=12,
        false_alarms=11,
        unlabelled=0,
    )
    labelled = labels.Labels(tmp_path / "labels.json", summary.day, [])
    text = report.markdown(summary, labelled, None, sleeps.NOT_RECORDED, SimulatedClock(T0, UTC))
    assert "3 reminders judged, with a return pause of 2 min, then 10 s." in text
    assert (
        "| False alarms in the day, once per pair | 11 | target 10, cap 20 "
        "| over the target, within the cap |"
    ) in text
    assert (
        "Alerts shown: 14; 12 of them on 12 pairs: 1 right, 11 wrong, 0 not labelled; "
        "2 of reminders with only a time, right when their time is read right "
        "(the statements page shows it)."
    ) in text


def test_the_report_tells_the_pairs_kept_quiet_as_already_reminded_apart(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    icons = Revision(10, 1, 1, ICONS, "esportare le icone", ICONS, "Figma.", BUILD)
    rent = Revision(20, 2, 1, RENT, "pagare l'affitto", RENT, "The bank.", BUILD)
    candidates = (
        Candidate(10, 2.5, False, Outcome.SAME_OCCASION),  # it rang in another window already
        Candidate(20, 0.1, False, Outcome.BELOW_THRESHOLD),
    )
    evaluation = Evaluation(1, T0 + 20_000, FIGMA, T0, 0.97, BUILD, candidates)
    day = days.select(Log((), {10: icons, 20: rent}, (evaluation,), (), (), ()), None, clock)
    relevant = {days.key(FIGMA, ICONS): True, days.key(FIGMA, RENT): True}
    labelled = labels.Labels(tmp_path / "labels.json", day.day, [])
    summary = days.summarize(day, relevant, clock)
    text = report.markdown(summary, labelled, None, sleeps.NOT_RECORDED, clock)
    assert (
        "| Missed reminders: relevant pairs never shown, unless kept quiet as already reminded "
        "| 50% (1 of 2) | at most 20% | no |"
    ) in text
    assert "Missed, by why: below threshold 1." in text
    assert "Kept quiet as already reminded, not missed, by why: same occasion 1." in text
    page = report.page(day, relevant, clock, "Copia", tmp_path / "report.html")
    missed, kept = page.read_text(encoding="utf-8").split("<h2>Taciuti")
    assert RENT in missed and ICONS not in missed
    assert ICONS in kept and "stessa occasione" in kept


def test_the_engines_thresholds_say_no_when_they_are_missed(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    icons = Revision(10, 1, 1, ICONS, "esportare le icone", ICONS, "Figma.", BUILD)
    candidate = Candidate(10, 0.1, False, Outcome.BELOW_THRESHOLD)
    evaluation = Evaluation(1, T0 + 20_000, FIGMA, T0, 0.97, BUILD, (candidate,))
    summary = days.summarize(
        days.select(Log((), {10: icons}, (evaluation,), (), (), ()), None, clock), {}, clock
    )
    used = report.Machine(1, 5_000, 0, (), 1_000, 1.0, 0.0, None, None)
    late = sleeps.Wake(T0, Waker.CONTEXT, 7.5, 2.5)
    written = sleeps.Wake(T0 + 60_000, Waker.STATEMENT, 3.0, 0.0)
    error = sleeps.SleepError(T0 + 400_000, SleepReason.IDLE)
    engine = sleeps.Sleeps(
        True, {SleepReason.IDLE: 2}, (late, written), 1, (error,), 0, 60_000, 300, 4, 3_247
    )
    text = report.markdown(summary, None, used, engine, clock)
    assert (
        "| Late wakes: the engine ready after the 5 s of the context waiting for it "
        "| 1, by at most 2.5 s | at most 1, by at most 2 s | no |"
    ) in text
    assert (
        "| Sleep errors: awake 5 min 10 s after core's last request, or 10 s after nothing came "
        "in front | 1 | none | no |"
    ) in text
    assert (
        "| Dedicated VRAM of the engine asleep, after its first 10 s, peak | 300 MiB in 4 rows "
        "| at most 204.8 MiB (0.2 GiB) | no |"
    ) in text
    assert (
        "| Dedicated VRAM of the app and its engine, peak | 5,000 MiB (shared 0 MiB) "
        "| at most 4,096 MiB | no |"
    ) in text
    assert "The engine slept 2 times (2 after 5 minutes idle)" in text
    assert (
        "Wakes for a statement, which delay no alert: 1; the creation window waited "
        "3.0 · 3.0 · 3.0 s (min · median · max) for the engine."
    ) in text
    assert "Wakes that ended without the model: 1." in text
    assert "Late: 10:00:00 by 2.5 s." in text
    assert (
        "Sleep errors, when the engine should have been asleep: 10:06:40 after 5 minutes idle."
    ) in text
    twice = replace(engine, wakes=(replace(late, late=1.0), replace(late, late=1.5)))
    assert "| 2, by at most 1.5 s | at most 1, by at most 2 s | no |" in report.markdown(
        summary, None, used, twice, clock
    )


def test_the_report_names_each_answer_in_the_owners_words(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    icons = Revision(10, 1, 1, ICONS, "esportare le icone", ICONS, "Figma.", BUILD)
    evaluation = Evaluation(
        1, T0 + 20_000, FIGMA, T0, 0.97, BUILD, (Candidate(10, 2.5, False, Outcome.ALERT),)
    )
    shown = Alert(1, 1, icons, 1, FIGMA, 2.5, evaluation.at, T0, shown_at=evaluation.at)
    for answer in Answer:
        alerts = (replace(shown, answer=answer),)
        day = days.select(Log((), {10: icons}, (evaluation,), alerts, (), ()), None, clock)
        page = report.page(day, {}, clock, "Copia", tmp_path / "report.html")
        assert f'<td class="muted">{HARNESS.report.answers[answer]}</td>' in page.read_text(
            encoding="utf-8"
        )


def monitor_rows(data: Path, *rows: str, header: str = ",".join(monitor.COLUMNS)) -> None:
    (data / "monitor-2026-10-05.csv").write_text("\n".join([header, *rows]) + "\n", "utf-8")


def test_the_report_reads_the_monitors_rows(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "prove"
    run("snapshot", "--data", str(data), "--database", str(database))
    monitor_rows(
        data,
        "2026-10-05T12:00:05+02:00,0.5,300,1.0,900,2.0,1500,150,40,3247,101,90,1",
        "2026-10-05T12:00:10+02:00,0.3,320,0.2,950,1.0,1500,160,30,3250,90,80,0",
    )
    capsys.readouterr()
    assert run("report", "--data", str(data)) == 0
    summary = capsys.readouterr().out
    assert (
        "| Dedicated VRAM of the app and its engine, peak | 3,410 MiB (shared 141 MiB) "
        "| at most 4,096 MiB | yes |"
    ) in summary
    assert (
        "| RAM of the app and its engine, peak | 1,270 MiB | at most 1,907 MiB (2 GB) | yes |"
        in summary
    )
    assert (
        "| CPU of the app and its engine, average | 1.00% (browsers 1.50%) | under 5% | yes |"
        in summary
    )
    assert "| Battery | 90% to 80%, 50% of the time unplugged | reported |  |" in summary


def test_the_rows_of_a_monitor_before_0_3_have_no_vram_of_each_process(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "prove"
    run("snapshot", "--data", str(data), "--database", str(database))
    monitor_rows(
        data,
        "2026-10-05T12:00:05+02:00,0.5,300,1.0,900,2.0,1500,3300,90,1",
        header="at,app_cpu,app_ram_mib,engine_cpu,engine_ram_mib,browsers_cpu,browsers_ram_mib,"
        "vram_used_mib,battery_percent,plugged",
    )
    capsys.readouterr()
    assert run("report", "--data", str(data)) == 0
    summary = capsys.readouterr().out
    assert (
        "| Dedicated VRAM of the app and its engine, peak | not in the monitor's rows "
        "| at most 4,096 MiB |  |"
    ) in summary
    assert "| RAM of the app and its engine, peak | 1,200 MiB |" in summary


def test_the_engines_sleeps_and_wakes_go_into_the_report(
    database: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The day of `a_day`, with the engine asleep from 200 s to 300 s, when the window of the
    mail woke it; its evaluation came at 305 s, and the engine was ready at 306 s."""
    store = Store.open(database)
    slept = EngineSleep(T0 + 200_000, SleepReason.IDLE, T0 + 300_000, Waker.CONTEXT, T0 + 306_000)
    store.save([slept])
    store.close()
    data = tmp_path / "prove"
    run("snapshot", "--data", str(data), "--database", str(database))
    monitor_rows(
        data,
        "2026-10-05T12:01:40+02:00,0.5,300,1.0,900,2.0,1500,150,40,3247,101,100,1",
        "2026-10-05T12:03:25+02:00,0.5,300,1.0,900,2.0,1500,150,40,900,101,100,1",  # falling
        "2026-10-05T12:04:10+02:00,0.5,300,1.0,900,2.0,1500,150,40,98,101,100,1",
        "2026-10-05T12:05:10+02:00,0.5,300,1.0,900,2.0,1500,150,40,3250,101,100,1",
    )
    capsys.readouterr()
    assert run("report", "--data", str(data)) == 0
    summary = capsys.readouterr().out
    assert (
        "| Late wakes: the engine ready after the 5 s of the context waiting for it "
        "| 1, by at most 1.0 s | at most 1, by at most 2 s | yes |"
    ) in summary
    assert (
        "| Sleep errors: awake 5 min 10 s after core's last request, or 10 s after nothing came "
        "in front | 0 | none | yes |"
    ) in summary
    assert (
        "| Dedicated VRAM of the engine asleep, after its first 10 s, peak | 98 MiB in 1 row "
        "| at most 204.8 MiB (0.2 GiB) | yes |"
    ) in summary
    assert (
        "The engine slept 1 time (1 after 5 minutes idle): asleep 0.0 of the 0.1 hours from the "
        "first context evaluated to the last evaluation (31%)."
    ) in summary
    assert "Wakes: 1 (1 for a context), ready in 6.0 · 6.0 · 6.0 s (min · median · max)." in summary
    assert f"Late: {SystemClock().local(T0 + 300_000):%H:%M:%S} by 1.0 s." in summary
    assert "The engine's dedicated VRAM awake peaked at 3,250 MiB." in summary
