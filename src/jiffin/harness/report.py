"""`report`: a day against the thresholds of ADR-0022, numbers only, and a page with the texts.

The summary is Markdown fit for an issue; the page, with titles and reminder texts, stays in
the data folder.
"""

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from jiffin.core.clock import Clock
from jiffin.harness import day as days
from jiffin.harness import render
from jiffin.harness.errors import HarnessError
from jiffin.harness.labels import Labels
from jiffin.lang.harness import HARNESS

DELAY_P95_S = 30
MISSED_SHARE = 0.20
FALSE_ALARMS_TARGET, FALSE_ALARMS_CAP = 10, 20
"""Wrong pairs shown in the day, each once (ADR-0022): twice those of ADR-0003, as the occasions
of version 0.2 double them."""
VRAM_MIB = 4096
RAM_MIB = 2_000_000_000 >> 20
"""2 GB of RAM for all the app's processes, in MiB."""
CPU_PERCENT = 5.0


@dataclass(frozen=True, slots=True)
class Machine:
    """What `monitor` saw over the day."""

    rows: int
    vram_peak_mib: int | None
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
    vram = [int(row["vram_used_mib"]) for row in rows if row["vram_used_mib"]]
    charge = [int(row["battery_percent"]) for row in rows if row["battery_percent"]]
    plugged = [row["plugged"] == "1" for row in rows if row["plugged"]]
    return Machine(
        rows=len(rows),
        vram_peak_mib=max(vram) if vram else None,
        ram_peak_mib=max(int(row["app_ram_mib"]) + int(row["engine_ram_mib"]) for row in rows),
        cpu_mean=sum(float(row["app_cpu"]) + float(row["engine_cpu"]) for row in rows) / len(rows),
        browsers_cpu_mean=sum(float(row["browsers_cpu"]) for row in rows) / len(rows),
        battery=(min(charge), max(charge)) if charge else None,
        unplugged=plugged.count(False) / len(plugged) if plugged else None,
    )


def markdown(summary: days.Summary, labels: Labels | None, used: Machine | None) -> str:
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
    rows = [_delay(summary), *_labelled(summary, labels), *_machine(used)]
    lines += ["", "| Measure | Value | Threshold (ADR-0022) | Within |", "|---|---|---|---|"]
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


def _machine(used: Machine | None) -> list[list[str]]:
    if used is None:
        return [["VRAM, RAM, CPU and battery", "no monitor rows", "", ""]]
    rows = [
        [
            "VRAM of the whole GPU, peak",
            "no reading" if used.vram_peak_mib is None else f"{used.vram_peak_mib:,} MiB",
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


def _yes(within: bool) -> str:
    return "yes" if within else "no"
