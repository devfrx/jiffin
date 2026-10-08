"""`report`: a day against the thresholds of ADR-0031, numbers only, and a page with the texts.

The summary is Markdown fit for an issue; the page, with titles and reminder texts, stays in
the data folder.
"""

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jiffin.core.clock import Clock
from jiffin.core.records import SleepReason, Waker
from jiffin.harness import day as days
from jiffin.harness import render, sleeps
from jiffin.harness.errors import HarnessError
from jiffin.harness.labels import Labels
from jiffin.lang.harness import HARNESS

DELAY_P95_S = 30
MISSED_SHARE = 0.20
FALSE_ALARMS_TARGET, FALSE_ALARMS_CAP = 10, 20
"""Wrong pairs shown in the day, each once (ADR-0022): twice those of ADR-0003, as the occasions
of version 0.2 double them."""
VRAM_MIB = 4096
"""The dedicated GPU memory of the app and its engine together (ADR-0031)."""
RAM_MIB = 2_000_000_000 >> 20
"""2 GB of RAM for all the app's processes, in MiB."""
CPU_PERCENT = 5.0


@dataclass(frozen=True, slots=True)
class Machine:
    """What `monitor` saw over the day."""

    rows: int
    vram_peak_mib: int | None
    """The dedicated GPU memory of the app and its engine together, at its peak; None in the rows
    of a monitor before version 0.3, which read the whole GPU's."""
    shared_peak_mib: int | None
    """Their shared GPU memory together, at its peak."""
    engine_vram: tuple[tuple[int, int], ...]
    """When each row was taken, in UTC milliseconds, with the engine's dedicated GPU memory then:
    for its sleeps."""
    ram_peak_mib: int
    """Of the app and its engine together."""
    cpu_mean: float
    """Of the app and its engine together, in percent of the machine."""
    browsers_cpu_mean: float
    battery: tuple[int, int] | None
    """The lowest and highest charge, in percent."""
    unplugged: float | None
    """The share of rows on battery."""


def machine(path: Path) -> Machine:
    try:
        with path.open(encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
    except OSError as error:
        raise HarnessError(f"the monitor's rows cannot be read: {error.strerror}") from None
    if not rows:
        raise HarnessError(f"{path.name} has no rows")
    read = [row for row in rows if row.get("engine_gpu_dedicated_mib")]
    charge = [int(row["battery_percent"]) for row in rows if row["battery_percent"]]
    plugged = [row["plugged"] == "1" for row in rows if row["plugged"]]
    return Machine(
        rows=len(rows),
        vram_peak_mib=max((_both(row, "gpu_dedicated_mib") for row in read), default=None),
        shared_peak_mib=max((_both(row, "gpu_shared_mib") for row in read), default=None),
        engine_vram=tuple((_ms(row["at"]), int(row["engine_gpu_dedicated_mib"])) for row in read),
        ram_peak_mib=max(_both(row, "ram_mib") for row in rows),
        cpu_mean=sum(float(row["app_cpu"]) + float(row["engine_cpu"]) for row in rows) / len(rows),
        browsers_cpu_mean=sum(float(row["browsers_cpu"]) for row in rows) / len(rows),
        battery=(min(charge), max(charge)) if charge else None,
        unplugged=plugged.count(False) / len(plugged) if plugged else None,
    )


def markdown(
    summary: days.Summary,
    labels: Labels | None,
    used: Machine | None,
    engine: sleeps.Sleeps,
    clock: Clock,
) -> str:
    per_hour = summary.evaluations / summary.hours if summary.hours else 0.0
    lines = [
        f"## Day {summary.day.isoformat()}",
        "",
        (
            f"{summary.evaluations} evaluations in {summary.hours:.1f} hours ({per_hour:.1f} per "
            f"hour): {summary.judged} asked the engine, {summary.failed} failed. "
            f"{summary.reminders} reminders judged{_pauses(summary.pauses)}."
        ),
    ]
    if labels is None:
        lines.append("No labels yet: run label.")
    else:
        agree, both = labels.agreement()
        lines.append(
            f"Labels: {summary.labelled} of {summary.pairs} pairs; "
            f"the owner agrees with Claude on {agree} of {both}."
        )
    rows = [
        _delay(summary),
        *_labelled(summary, labels),
        *_sleeping(engine, used),
        *_machine(used),
    ]
    lines += ["", "| Measure | Value | Threshold (ADR-0031) | Within |", "|---|---|---|---|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    if labels is not None:
        right = summary.alerted - summary.false_alarms - summary.unlabelled
        judged = (
            f"on {summary.alerted} pairs: {right} right, {summary.false_alarms} wrong, "
            f"{summary.unlabelled} not labelled"
        )
        if summary.time_only:
            shown = (
                f"Alerts shown: {summary.shown}; {summary.shown - summary.time_only} of them "
                f"{judged}; {summary.time_only} of reminders with only a time, right when their "
                "time is read right (the statements page shows it)."
            )
        else:
            shown = f"Alerts shown: {summary.shown}, {judged}."
        lines += ["", shown]
        if summary.missed:
            lines.append(f"Missed, by why: {_whys(summary.missed)}.")
        if summary.reminded:
            lines.append(
                f"Kept quiet as already reminded, not missed, by why: {_whys(summary.reminded)}."
            )
    lines += _engine(engine, clock)
    if used is not None:
        lines.append(
            "The CPU the browsers spend on accessibility is not in the monitor's rows: "
            "the benchmark in docs/design/context.md measures it apart."
        )
    return "\n".join(lines)


def replays(rows: Sequence[tuple[str, days.Day]], labels: Mapping[str, bool], clock: Clock) -> str:
    """One line per replay of a day, numbers only, with the day as recorded first."""
    lines = [
        f"## Replays of {rows[0][1].day.isoformat()}",
        "",
        (
            "| Replay | reminders | threshold | evaluations | failed | alerts shown | pairs "
            "| false alarms | missed reminders | pairs not labelled | delay p95 |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, day in rows:
        summary = days.summarize(day, labels, clock)
        thresholds = sorted({evaluation.threshold for evaluation in day.evaluations})
        missed = sum(summary.missed.values())
        p95 = days.delay(summary, 95)
        cells = [
            name,
            str(summary.reminders),
            ", ".join(f"{threshold:g}" for threshold in thresholds),
            str(summary.evaluations),
            str(summary.failed),
            str(summary.shown),
            str(summary.alerted),
            str(summary.false_alarms) if labels else "no labels",
            f"{missed / summary.relevant:.0%} ({missed} of {summary.relevant})"
            if labels and summary.relevant
            else "no labels",
            str(summary.unlabelled),
            "" if p95 is None else f"{p95:.1f} s",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def page(day: days.Day, labels: Mapping[str, bool], clock: Clock, source: str, path: Path) -> Path:
    alerts = [
        {
            "time": f"{clock.local(alert.shown_at):%H:%M}",
            "app": alert.context.app,
            "title": alert.context.title,
            "address": alert.context.address,
            "condition": alert.revision.condition,
            "action": alert.revision.action,
            "d": "" if alert.d is None else f"{alert.d:.2f}",
            "time_only": alert.evaluation_id is None,
            "label": labels.get(days.Pair(alert.context, alert.revision).key),
            "answer": "" if alert.answer is None else HARNESS.report.answers[alert.answer.value],
            "delay": f"{(alert.shown_at - alert.due_at) / 1000:.0f} s",
        }
        for alert in day.alerts
        if alert.shown_at is not None
    ]
    unshown = days.unshown(day, labels, clock)
    return render.page(
        "report.html",
        path,
        day=day.day.isoformat(),
        source=source,
        alerts=alerts,
        missed=[_unshown(pair) for pair in unshown if pair.missed],
        reminded=[_unshown(pair) for pair in unshown if not pair.missed],
    )


def _unshown(pair: days.Unshown) -> dict[str, str | None]:
    context, revision = pair.pair.context, pair.pair.revision
    return {
        "app": context.app,
        "title": context.title,
        "address": context.address,
        "condition": revision.condition,
        "action": revision.action,
        "why": HARNESS.report.reasons[pair.why],
        "d": f"{pair.d:.2f}",
    }


def _pauses(pauses: Sequence[int]) -> str:
    """ ", with a return pause of 2 min", the setting the day was judged with (ADR-0022); nothing
    for a day of version 0.1."""
    if not pauses:
        return ""
    return ", with a return pause of " + ", then ".join(_duration(pause) for pause in pauses)


def _duration(milliseconds: int) -> str:
    seconds = milliseconds // 1000
    return f"{seconds // 60} min" if seconds % 60 == 0 else f"{seconds} s"


def _delay(summary: days.Summary) -> list[str]:
    name = "Delay from when the alert became due, p95"
    p95, p50 = days.delay(summary, 95), days.delay(summary, 50)
    if p95 is None or p50 is None:
        return [name, "no alert shown", "", ""]
    return [
        name,
        f"{p95:.1f} s (p50 {p50:.1f} s)",
        f"at most {DELAY_P95_S} s",
        _yes(p95 <= DELAY_P95_S),
    ]


def _whys(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{why} {count}" for why, count in sorted(counts.items()))


def _labelled(summary: days.Summary, labels: Labels | None) -> list[list[str]]:
    missed_label = (
        "Missed reminders: relevant pairs never shown, unless kept quiet as already reminded"
    )
    false_label = "False alarms in the day, once per pair"
    if labels is None:
        return [[missed_label, "no labels", "", ""], [false_label, "no labels", "", ""]]
    missed = sum(summary.missed.values())
    share = missed / summary.relevant if summary.relevant else 0.0
    if summary.false_alarms <= FALSE_ALARMS_TARGET:
        within = "yes"
    elif summary.false_alarms <= FALSE_ALARMS_CAP:
        within = "over the target, within the cap"
    else:
        within = "no"
    return [
        [
            missed_label,
            f"{share:.0%} ({missed} of {summary.relevant})",
            f"at most {MISSED_SHARE:.0%}",
            _yes(share <= MISSED_SHARE),
        ],
        [
            false_label,
            str(summary.false_alarms),
            f"target {FALSE_ALARMS_TARGET}, cap {FALSE_ALARMS_CAP}",
            within,
        ],
    ]


def _sleeping(engine: sleeps.Sleeps, used: Machine | None) -> list[list[str]]:
    """The thresholds of the engine's sleep (ADR-0031)."""
    late_name = "Late wakes: the engine ready after the 5 s of the context waiting for it"
    errors_name = (
        "Sleep errors: awake 5 min 10 s after core's last request, or 10 s after nothing "
        "came in front"
    )
    asleep_name = "Dedicated VRAM of the engine asleep, after its first 10 s, peak"
    if not engine.recorded:
        return [[name, "not recorded before 0.3", "", ""] for name in (late_name, errors_name)]
    late = engine.late
    longest = max((wake.late for wake in late), default=0.0)
    rows = [
        [
            late_name,
            f"{len(late)}, by at most {longest:.1f} s" if late else "0",
            f"at most {sleeps.LATE_WAKES}, by at most {sleeps.LATE_BY_S:g} s",
            _yes(len(late) <= sleeps.LATE_WAKES and longest <= sleeps.LATE_BY_S),
        ],
        [errors_name, str(len(engine.errors)), "none", _yes(not engine.errors)],
    ]
    if used is None:
        rows.append([asleep_name, "no monitor rows", "", ""])
    elif engine.vram_asleep_mib is None:
        rows.append([asleep_name, "no row with the engine asleep", "", ""])
    else:
        rows.append(
            [
                asleep_name,
                f"{engine.vram_asleep_mib:,} MiB in {_count(engine.vram_asleep_rows, 'row')}",
                f"at most {sleeps.ASLEEP_VRAM_MIB:g} MiB (0.2 GiB)",
                _yes(engine.vram_asleep_mib <= sleeps.ASLEEP_VRAM_MIB),
            ]
        )
    return rows


def _engine(engine: sleeps.Sleeps, clock: Clock) -> list[str]:
    """The engine's sleeps and wakes in words, numbers only."""
    if not engine.recorded:
        return []
    share = engine.asleep_ms / engine.active_ms if engine.active_ms else 0.0
    why = ", ".join(f"{n} {_SLEPT[reason]}" for reason, n in engine.slept.items())
    lines = [
        "",
        (
            f"The engine slept {_count(sum(engine.slept.values()), 'time')}"
            f"{f' ({why})' if why else ''}: "
            f"asleep {engine.asleep_ms / 3_600_000:.1f} of the {engine.active_ms / 3_600_000:.1f} "
            f"hours from the first context evaluated to the last evaluation ({share:.0%})."
        ),
    ]
    alerts = [wake for wake in engine.wakes if wake.woken_by is not Waker.STATEMENT]
    statements = [wake for wake in engine.wakes if wake.woken_by is Waker.STATEMENT]
    if alerts:
        by = ", ".join(
            f"{n} {_WOKEN[waker]}"
            for waker in Waker
            if (n := sum(wake.woken_by is waker for wake in alerts))
        )
        lines.append(f"Wakes: {len(alerts)} ({by}), ready in {_spread(alerts)}.")
    if statements:
        lines.append(
            f"Wakes for a statement, which delay no alert: {len(statements)}; the creation "
            f"window waited {_spread(statements)} for the engine."
        )
    if engine.unready:
        lines.append(f"Wakes that ended without the model: {engine.unready}.")
    if engine.late:
        late = "; ".join(
            f"{clock.local(wake.woken_at):%H:%M:%S} by {wake.late:.1f} s" for wake in engine.late
        )
        lines.append(f"Late: {late}.")
    if engine.errors:
        errors = "; ".join(
            f"{clock.local(error.due):%H:%M:%S} {_SLEPT[error.rule]}" for error in engine.errors
        )
        lines.append(f"Sleep errors, when the engine should have been asleep: {errors}.")
    if engine.vram_awake_mib is not None:
        lines.append(f"The engine's dedicated VRAM awake peaked at {engine.vram_awake_mib:,} MiB.")
    return lines


_SLEPT = {
    SleepReason.IDLE: "after 5 minutes idle",
    SleepReason.NOTHING_IN_FRONT: "with nothing in front",
}
_WOKEN = {
    Waker.CONTEXT: "for a context",
    Waker.JUDGEMENT: "for a judgement no context announced",
    Waker.RETRY: "on Retry",
}


def _spread(wakes: Sequence[sleeps.Wake]) -> str:
    low, median, high = sleeps.spread(wakes)
    return f"{low:.1f} · {median:.1f} · {high:.1f} s (min · median · max)"


def _machine(used: Machine | None) -> list[list[str]]:
    if used is None:
        return [["VRAM, RAM, CPU and battery", "no monitor rows", "", ""]]
    rows = [
        [
            "Dedicated VRAM of the app and its engine, peak",
            "not in the monitor's rows"
            if used.vram_peak_mib is None
            else f"{used.vram_peak_mib:,} MiB (shared {used.shared_peak_mib or 0:,} MiB)",
            f"at most {VRAM_MIB:,} MiB",
            "" if used.vram_peak_mib is None else _yes(used.vram_peak_mib <= VRAM_MIB),
        ],
        [
            "RAM of the app and its engine, peak",
            f"{used.ram_peak_mib:,} MiB",
            f"at most {RAM_MIB:,} MiB (2 GB)",
            _yes(used.ram_peak_mib <= RAM_MIB),
        ],
        [
            "CPU of the app and its engine, average",
            f"{used.cpu_mean:.2f}% (browsers {used.browsers_cpu_mean:.2f}%)",
            f"under {CPU_PERCENT:.0f}%",
            _yes(used.cpu_mean < CPU_PERCENT),
        ],
    ]
    if used.battery is not None and used.unplugged is not None:
        low, high = used.battery
        rows.append(
            [
                "Battery",
                f"{high}% to {low}%, {used.unplugged:.0%} of the time unplugged",
                "reported",
                "",
            ]
        )
    return rows


def _count(n: int, thing: str) -> str:
    return f"{n:,} {thing}{'' if n == 1 else 's'}"


def _both(row: Mapping[str, str], measure: str) -> int:
    """A measure of the app and its engine together, from a row of the monitor."""
    return int(row[f"app_{measure}"]) + int(row[f"engine_{measure}"])


def _ms(at: str) -> int:
    """A row's time, written with its offset, in UTC milliseconds."""
    return int(datetime.fromisoformat(at).timestamp() * 1000)


def _yes(within: bool) -> str:
    return "yes" if within else "no"
