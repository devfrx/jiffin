"""`report`: a day against the thresholds of ADR-0003, numbers only, and a page with the texts.

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

DELAY_P95_S = 30
MISSED_SHARE = 0.20
FALSE_ALARMS_TARGET, FALSE_ALARMS_CAP = 5, 10
VRAM_MIB = 4096
RAM_MIB = 2_000_000_000 >> 20
"""2 GB of RAM for all the app's processes, in MiB."""
CPU_PERCENT = 5.0

_WHY = {
    "below threshold": "sotto la soglia",
    "same occasion": "stessa occasione",
    "held back": "trattenuto (una volta all'ora)",
    "out of time": "fuori orario",
    "snoozed": "rimandato",
    "silenced": "«Non qui»",
    "waited": "in attesa di un posto, poi chiuso",
}


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
            f"{summary.reminders} reminders judged."
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
    lines += ["", "| Measure | Value | Threshold (ADR-0003) | Within |", "|---|---|---|---|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    if labels is not None:
        right = summary.shown - summary.false_alarms - summary.unlabelled_alerts
        lines += [
            "",
            (
                f"Alerts shown: {summary.shown}: {right} right, {summary.false_alarms} false "
                f"alarms, {summary.unlabelled_alerts} not labelled."
            ),
        ]
        if summary.missed:
            reasons = ", ".join(f"{why} {count}" for why, count in sorted(summary.missed.items()))
            lines.append(f"Missed, by why: {reasons}.")
    if used is not None:
        lines.append(
            "The CPU the browsers spend on accessibility is not in the monitor's rows: "
            "the benchmark in docs/design/context.md measures it apart."
        )
    return "\n".join(lines)


def replays(rows: Sequence[tuple[str, days.Day]], labels: Mapping[str, bool]) -> str:
    """One line per replay of a day, numbers only, with the day as recorded first."""
    lines = [
        f"## Replays of {rows[0][1].day.isoformat()}",
        "",
        (
            "| Replay | reminders | threshold | evaluations | failed | alerts shown "
            "| false alarms | missed reminders | alerts not labelled | delay p95 |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, day in rows:
        summary = days.summarize(day, labels)
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
            str(summary.false_alarms) if labels else "no labels",
            f"{missed / summary.relevant:.0%} ({missed} of {summary.relevant})"
            if labels and summary.relevant
            else "no labels",
            str(summary.unlabelled_alerts),
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
            "label": labels.get(days.key(alert.context, alert.revision.condition)),
            "answer": "" if alert.answer is None else alert.answer.value,
            "delay": f"{(alert.shown_at - alert.due_at) / 1000:.0f} s",
        }
        for alert in day.alerts
        if alert.shown_at is not None
    ]
    missed = [
        {
            "app": pair.pair.context.app,
            "title": pair.pair.context.title,
            "address": pair.pair.context.address,
            "condition": pair.pair.revision.condition,
            "action": pair.pair.revision.action,
            "why": _WHY[pair.why],
            "d": f"{pair.d:.2f}",
        }
        for pair in days.missed(day, labels)
    ]
    return render.page(
        "report.html", path, day=day.day.isoformat(), source=source, alerts=alerts, missed=missed
    )


def _delay(summary: days.Summary) -> list[str]:
    p95, p50 = days.delay(summary, 95), days.delay(summary, 50)
    if p95 is None or p50 is None:
        return ["Delay from the context change to the alert, p95", "no alert shown", "", ""]
    return [
        "Delay from the context change to the alert, p95",
        f"{p95:.1f} s (p50 {p50:.1f} s)",
        f"at most {DELAY_P95_S} s",
        _yes(p95 <= DELAY_P95_S),
    ]


def _labelled(summary: days.Summary, labels: Labels | None) -> list[list[str]]:
    missed_label = "Missed reminders: relevant pairs never shown"
    false_label = "False alarms in the day"
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
