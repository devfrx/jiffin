"""`sample`: the prototype's labelled sample through the app's engine (ADR-0007, ADR-0017).

Each condition is rewritten and each context judged as the app does it: contexts normalized,
the address only in the supported browsers and never while the user types in the bar
(ADR-0004), the conditions as their English statements (ADR-0008). The numbers are those of the
pipeline that runs, so a new engine build is measured against the last one on the same pairs.
"""

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from jiffin.core.context import BROWSER_SUFFIXES, Context, normalize
from jiffin.core.model import EngineBuild, Model
from jiffin.core.reminders import THRESHOLD
from jiffin.harness import metrics
from jiffin.harness.errors import HarnessError
from jiffin.harness.metrics import Operating, Table

CLASSES = {
    1: "name",
    2: "name",
    3: "type",
    4: "vague",
    5: "name",
    6: "name",
    7: "name",
    8: "negation",
    9: "name",
}
"""The kind of condition of each reminder of the sample, by its number: a name to find, a type
of work, a vague wish, a negation (devfrx/sibyl#20)."""

BUDGETS = (0.1, 0.13, 0.2)
"""False alarms per evaluated context at which recall is read, as in ADR-0007."""

# The prototype's reminders are one sentence, "quando … ricordami di …": the condition is the
# part before "ricordami", the "Quando" box of the app.
_CONDITION = re.compile(r"^\s*((?:quando|se)\b.*?)[\s,]+ricordami\b", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class Sample:
    context_ids: tuple[str, ...]
    contexts: tuple[Context, ...]
    reminder_ids: tuple[str, ...]
    numbers: tuple[int, ...]
    conditions: tuple[str, ...]
    relevant: tuple[tuple[bool, ...], ...]
    """Rows are contexts, columns reminders, in the order above."""


@dataclass(frozen=True, slots=True)
class Scores:
    build: EngineBuild
    d: tuple[tuple[float, ...], ...]
    """Laid out as `Sample.relevant`."""


@dataclass(frozen=True, slots=True)
class Kind:
    """The reminders of one class of condition."""

    reminders: int
    relevant: int
    auroc: float
    recall: float
    """At the app's threshold."""


@dataclass(frozen=True, slots=True)
class Measure:
    """A number of one build, with its 95% interval when there is one."""

    value: float
    interval: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class Summary:
    auroc: Measure
    within: dict[float, tuple[Operating, Measure]]
    """By budget of false alarms per evaluated context: the operating point, and its recall."""
    at_threshold: Operating
    kinds: dict[str, Kind]


@dataclass(frozen=True, slots=True)
class Differences:
    """This build minus the baseline."""

    auroc: Measure
    recall_within: dict[float, Measure]
    """By budget of false alarms per evaluated context."""
    at_threshold: tuple[float, float]
    """Of recall and of false alarms per evaluated context, at the app's threshold."""


def load(path: Path) -> Sample:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HarnessError(f"the sample cannot be read: {error.strerror}: pass --sample") from None
    reminders = sorted(data["reminders"], key=lambda reminder: reminder["n"])
    labels = data["labels"]
    return Sample(
        context_ids=tuple(row["id"] for row in data["contexts"]),
        contexts=tuple(_context(row) for row in data["contexts"]),
        reminder_ids=tuple(reminder["id"] for reminder in reminders),
        numbers=tuple(reminder["n"] for reminder in reminders),
        conditions=tuple(_condition(reminder["text"]) for reminder in reminders),
        relevant=tuple(
            tuple(bool(labels[row["id"]][reminder["id"]]) for reminder in reminders)
            for row in data["contexts"]
        ),
    )


def score(sample: Sample, model: Model) -> Scores:
    """Rewrite every condition, then judge every context with all the statements."""
    statements = dict(enumerate(model.rewrite(condition) for condition in sample.conditions))
    rows = []
    for context in sample.contexts:
        d = model.judge(context, statements)
        rows.append(tuple(d[index] for index in statements))
    return Scores(model.build(), tuple(rows))


def summarize(sample: Sample, d: Table[float]) -> Summary:
    auroc = _auroc(sample, d)
    within = {}
    for budget in BUDGETS:
        recall = _recall_within(sample, d, budget)
        point = metrics.best_within(d, sample.relevant, budget)
        within[budget] = (point, Measure(point.recall, metrics.bootstrap(len(d), recall)))
    return Summary(
        auroc=Measure(auroc(range(len(d))), metrics.bootstrap(len(d), auroc)),
        within=within,
        at_threshold=metrics.at_threshold(d, sample.relevant, THRESHOLD),
        kinds=_kinds(sample, d),
    )


def compare(sample: Sample, d: Table[float], baseline: Table[float]) -> Differences:
    """Paired differences: both builds get the same draws of contexts."""

    def gain(of: Callable[[Table[float]], Callable[[Sequence[int]], float]]) -> Measure:
        new, old = of(d), of(baseline)

        def difference(rows: Sequence[int]) -> float:
            return new(rows) - old(rows)

        return Measure(difference(range(len(d))), metrics.bootstrap(len(d), difference))

    def recall(budget: float) -> Callable[[Table[float]], Callable[[Sequence[int]], float]]:
        return lambda scores: _recall_within(sample, scores, budget)

    new, old = (
        metrics.at_threshold(scores, sample.relevant, THRESHOLD) for scores in (d, baseline)
    )
    return Differences(
        auroc=gain(lambda scores: _auroc(sample, scores)),
        recall_within={budget: gain(recall(budget)) for budget in BUDGETS},
        at_threshold=(new.recall - old.recall, new.false_alarms - old.false_alarms),
    )


def save(sample: Sample, scores: Scores, folder: Path, now: datetime) -> Path:
    """The scores, for the next build to compare with: ids and numbers only."""
    path = folder / f"sample-{now:%Y%m%d-%H%M%S}.json"
    record = {
        "at": now.isoformat(timespec="seconds"),
        "build": asdict(scores.build),
        "threshold": THRESHOLD,
        "contexts": sample.context_ids,
        "reminders": sample.reminder_ids,
        "d": scores.d,
    }
    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return path


def load_baseline(sample: Sample, path: Path) -> Scores:
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HarnessError(f"the baseline cannot be read: {error.strerror}") from None
    ids = (tuple(record["contexts"]), tuple(record["reminders"]))
    if ids != (sample.context_ids, sample.reminder_ids):
        raise HarnessError("the baseline was measured on another sample")
    return Scores(EngineBuild(**record["build"]), tuple(tuple(row) for row in record["d"]))


def report(
    sample: Sample,
    scores: Scores,
    summary: Summary,
    baseline: tuple[Scores, Summary, Differences] | None = None,
) -> str:
    """A summary of numbers only, in Markdown, fit for an issue.

    `baseline` is the earlier build: its scores, its summary, and the differences from it.
    """
    pairs = len(sample.contexts) * len(sample.conditions)
    relevant = sum(map(sum, sample.relevant))
    lines = [
        f"## Sample: {describe(scores.build)}",
        "",
        (
            f"{len(sample.contexts)} contexts, {len(sample.conditions)} reminders: "
            f"{relevant} relevant pairs of {pairs}."
        ),
    ]
    columns = ["", "this build", "95% interval"]
    if baseline is not None:
        lines += ["", f"Baseline: {describe(baseline[0].build)}."]
        columns += ["baseline", "difference", "95% interval of the difference"]
    rows = _rows(summary, None if baseline is None else (baseline[1], baseline[2]))
    kinds = [
        [
            name,
            str(kind.reminders),
            str(kind.relevant),
            _number(kind.auroc),
            _number(kind.recall, 2),
        ]
        for name, kind in summary.kinds.items()
    ]
    lines += ["", *_markdown(columns, rows)]
    lines += [
        "",
        *_markdown(
            ["Condition class", "reminders", "relevant pairs", "AUROC", "recall at the threshold"],
            kinds,
        ),
    ]
    return "\n".join(lines)


def describe(build: EngineBuild) -> str:
    return (
        f"engine {build.engine_version}, llama.cpp {build.llama_cpp_build}, "
        f"judge prompt {build.judge_prompt}, rewrite prompt {build.rewrite_prompt}, "
        f"model {build.model_sha256[:12]}"
    )


def _rows(summary: Summary, baseline: tuple[Summary, Differences] | None) -> list[list[str]]:
    at = summary.at_threshold
    rows = [
        ["AUROC", _number(summary.auroc.value), _interval(summary.auroc)],
        *(
            [
                f"Recall with at most {budget} false alarms per evaluated context",
                f"{_number(point.recall, 2)} at d >= {_number(point.threshold)}",
                _interval(recall, 2),
            ]
            for budget, (point, recall) in summary.within.items()
        ),
        [f"At the threshold {THRESHOLD}: recall", _number(at.recall, 2), ""],
        [
            f"At the threshold {THRESHOLD}: false alarms per evaluated context",
            _number(at.false_alarms),
            "",
        ],
    ]
    if baseline is None:
        return rows
    old, gain = baseline
    more = [
        [
            _number(old.auroc.value),
            _number(gain.auroc.value, signed=True),
            _interval(gain.auroc, signed=True),
        ],
        *(
            [
                _number(old.within[budget][0].recall, 2),
                _number(gain.recall_within[budget].value, 2, signed=True),
                _interval(gain.recall_within[budget], 2, signed=True),
            ]
            for budget in summary.within
        ),
        [_number(old.at_threshold.recall, 2), _number(gain.at_threshold[0], 2, signed=True), ""],
        [_number(old.at_threshold.false_alarms), _number(gain.at_threshold[1], signed=True), ""],
    ]
    return [row + extra for row, extra in zip(rows, more, strict=True)]


def _markdown(columns: list[str], rows: list[list[str]]) -> list[str]:
    return [
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
        *("| " + " | ".join(row) + " |" for row in rows),
    ]


def _auroc(sample: Sample, d: Table[float]) -> Callable[[Sequence[int]], float]:
    def auroc(rows: Sequence[int]) -> float:
        return metrics.auroc(
            metrics.flat(metrics.pick(d, rows)), metrics.flat(metrics.pick(sample.relevant, rows))
        )

    return auroc


def _recall_within(
    sample: Sample, d: Table[float], budget: float
) -> Callable[[Sequence[int]], float]:
    def recall(rows: Sequence[int]) -> float:
        return metrics.best_within(
            metrics.pick(d, rows), metrics.pick(sample.relevant, rows), budget
        ).recall

    return recall


def _kinds(sample: Sample, d: Table[float]) -> dict[str, Kind]:
    kinds = {}
    for name in dict.fromkeys(CLASSES[number] for number in sample.numbers):
        columns = [index for index, number in enumerate(sample.numbers) if CLASSES[number] == name]
        scores, relevant = metrics.column(d, columns), metrics.column(sample.relevant, columns)
        kinds[name] = Kind(
            reminders=len(columns),
            relevant=sum(map(sum, relevant)),
            auroc=metrics.auroc(metrics.flat(scores), metrics.flat(relevant)),
            recall=metrics.at_threshold(scores, relevant, THRESHOLD).recall,
        )
    return kinds


def _context(row: dict[str, Any]) -> Context:
    typing = bool(row.get("address_bar_focused"))
    address = None if typing else row.get("address_bar")
    context = normalize(row["app"], row.get("title") or "", address)
    if context.app not in BROWSER_SUFFIXES:
        context = replace(context, address=None)
    return context


def _condition(text: str) -> str:
    match = _CONDITION.match(text)
    if match is None:
        raise HarnessError("a reminder of the sample has no condition before 'ricordami'")
    return match.group(1).strip()


def _number(value: float, digits: int = 3, *, signed: bool = False) -> str:
    if math.isnan(value):
        return "n/a"
    if math.isinf(value):
        return "none"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def _interval(measure: Measure, digits: int = 3, *, signed: bool = False) -> str:
    if measure.interval is None:
        return ""
    low, high = measure.interval
    return f"{_number(low, digits, signed=signed)} to {_number(high, digits, signed=signed)}"
