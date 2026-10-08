"""`python -m jiffin.harness <command>`: the measurements of ADR-0017."""

import argparse
import logging
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from datetime import date, datetime
from pathlib import Path

from jiffin.core.clock import Clock, SystemClock
from jiffin.core.meanings import read
from jiffin.core.model import ModelError
from jiffin.core.records import Revision
from jiffin.core.reminders import THRESHOLD
from jiffin.harness import (
    calls,
    capture,
    engine,
    fixtures,
    folders,
    labels,
    monitor,
    page,
    replay,
    report,
    sample,
    scores,
    sleeps,
    snapshot,
    statements,
)
from jiffin.harness import day as days
from jiffin.harness.errors import HarnessError
from jiffin.harness.truth import Truth
from jiffin.lang.harness import HARNESS
from jiffin.store.folders import Folders
from jiffin.store.store import Log

log = logging.getLogger(__name__)


def main(arguments: Sequence[str] | None = None) -> int:
    options = parser().parse_args(arguments)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    try:
        options.command(options)
    except HarnessError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--data",
        type=Path,
        default=folders.DATA,
        help="the folder for anything with titles, addresses or reminder texts "
        "(default: %(default)s)",
    )
    copy_options = argparse.ArgumentParser(add_help=False)
    copy_options.add_argument(
        "--copy", type=Path, help="a copy of the log (default: the newest in the data folder)"
    )
    day_options = argparse.ArgumentParser(add_help=False)
    day_options.add_argument(
        "--day",
        type=date.fromisoformat,
        help="a local day, YYYY-MM-DD (default: the copy's last day with evaluations)",
    )
    engine_options = argparse.ArgumentParser(add_help=False)
    engine_options.add_argument(
        "--models",
        type=Path,
        default=Folders.app().models,
        help="the folder with the model file (default: the app's, %(default)s)",
    )

    main_parser = argparse.ArgumentParser(prog="python -m jiffin.harness", description=__doc__)
    commands = main_parser.add_subparsers(required=True, metavar="command")

    measure = commands.add_parser(
        "sample",
        parents=[common, engine_options],
        help="the labelled sample through the engine: AUROC and recall at fixed false alarms",
    )
    measure.add_argument(
        "--sample", type=Path, default=folders.SAMPLE, help="(default: %(default)s)"
    )
    measure.add_argument(
        "--baseline", type=Path, help="the scores of an earlier build, saved by an earlier run"
    )
    measure.set_defaults(command=_sample)

    watch = commands.add_parser(
        "monitor",
        parents=[common],
        help="CPU, RAM, VRAM and battery every few seconds, into a CSV, until Ctrl+C",
    )
    watch.add_argument(
        "--every", type=float, default=monitor.EVERY_SECONDS, help="seconds (default: %(default)s)"
    )
    watch.set_defaults(command=_monitor)

    copy = commands.add_parser(
        "snapshot",
        parents=[common],
        help="copy the app's log into the data folder, also while the app runs",
    )
    copy.add_argument(
        "--database",
        type=Path,
        default=Folders.app().database,
        help="(default: the app's, %(default)s)",
    )
    copy.set_defaults(command=_snapshot)

    forget = commands.add_parser(
        "forget", parents=[common], help="delete the copies of the log, once the analysis is done"
    )
    forget.set_defaults(command=_forget)

    check = commands.add_parser(
        "statements",
        parents=[common, copy_options],
        help="a page with every condition beside its English statement",
    )
    check.set_defaults(command=_statements)

    label = commands.add_parser(
        "label",
        parents=[common, copy_options, day_options],
        help="the day's pairs to label, for Claude; with --owner, a page for the owner's share; "
        "with --calls, a page for the owner's check of the calls and absences",
    )
    pages = label.add_mutually_exclusive_group()
    pages.add_argument(
        "--owner",
        type=int,
        nargs="?",
        const=labels.OWNER_SHARE,
        metavar="PAIRS",
        help=f"serve the page for the owner's share (default: {labels.OWNER_SHARE} pairs)",
    )
    pages.add_argument(
        "--calls",
        action="store_true",
        help="serve the page where the owner marks the day's wrong calls and absences and adds "
        "the missing ones",
    )
    label.add_argument(
        "--no-browser", action="store_true", help="print the page's address without opening it"
    )
    label.add_argument(
        "--reminders",
        type=_integers,
        metavar="N[,N...]",
        help="also the pairs of the invented reminders that replay --reminders adds",
    )
    label.set_defaults(command=_label)

    again = commands.add_parser(
        "replay",
        parents=[common, copy_options, day_options, engine_options],
        help="the day again through core: at other thresholds, with more reminders, or judged "
        "by this checkout's engine",
    )
    again.add_argument(
        "--threshold",
        type=_decimals,
        metavar="T[,T...]",
        help="thresholds to replay at: from the scores the log keeps, no engine; with --engine "
        "or --reminders, from the engine's, kept in the data folder",
    )
    again.add_argument(
        "--engine", action="store_true", help="judge the day again with this checkout's engine"
    )
    again.add_argument(
        "--reminders",
        type=_integers,
        metavar="N[,N...]",
        help="active reminders to reach with invented ones, judged by the engine: it starts "
        "only for the scores not kept yet",
    )
    again.set_defaults(command=_replay)

    convert = commands.add_parser(
        "convert",
        parents=[common, engine_options],
        help="the prototype's capture of a day into a copy of the log, judged by the engine",
    )
    convert.add_argument("capture", type=Path, help="a contesti-<day>.jsonl of the prototype")
    convert.add_argument(
        "--sample",
        type=Path,
        default=folders.SAMPLE,
        help="whose reminders the prototype judged (default: %(default)s)",
    )
    convert.set_defaults(command=_convert)

    measure_day = commands.add_parser(
        "report",
        parents=[common, copy_options, day_options],
        help="a day against the thresholds, numbers only, and a page with the texts",
    )
    measure_day.add_argument(
        "--monitor", type=Path, help="the monitor's rows (default: the day's, if there)"
    )
    measure_day.set_defaults(command=_report)
    return main_parser


def _sample(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    labelled = sample.load(options.sample)
    baseline = (
        None if options.baseline is None else sample.load_baseline(labelled, options.baseline)
    )
    log.info(
        "the sample: %d contexts, %d reminders", len(labelled.contexts), len(labelled.conditions)
    )
    with engine.running(options.models) as model:
        try:
            scores = sample.score(labelled, model)
        except ModelError as error:
            raise HarnessError(f"the engine: {error}") from None
    saved = sample.save(labelled, scores, data, datetime.now().astimezone())
    summary = sample.summarize(labelled, scores.d)
    compared = None
    if baseline is not None:
        differences = sample.compare(labelled, scores.d, baseline.d)
        compared = (baseline, sample.summarize(labelled, baseline.d), differences)
    print(sample.report(labelled, scores, summary, compared))
    log.info("the scores are in %s", saved)


def _monitor(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    log.info("monitoring every %s s; Ctrl+C stops", options.every)
    path = monitor.run(data, options.every)
    log.info("the rows are in %s", path)


def _snapshot(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    copy = snapshot.snapshot(options.database, data, datetime.now().astimezone())
    log.info("the copy is %s; forget deletes it once the analysis is done", copy)


def _forget(options: argparse.Namespace) -> None:
    deleted = snapshot.forget(folders.data_folder(options.data))
    log.info("%d copies of the log deleted", len(deleted))


def _statements(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    copy = options.copy or snapshot.latest(data)
    log.info("the page is %s", statements.page(snapshot.read(copy), copy, data, SystemClock()))


def _label(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    if options.owner is not None:
        path = labels.path_for(data, options.day) if options.day else _latest_labels(data)
        labelled = labels.load(path)
        server = page.LabelServer(labelled, labels.owner_share(labelled, options.owner))
        log.info(
            "%d pairs for the owner; answers go into %s. Ctrl+C stops.", len(server.keys), path
        )
        page.serve(server, open_browser=not options.no_browser)
        return
    copy = options.copy or snapshot.latest(data)
    clock = SystemClock()
    day = days.select(snapshot.read(copy), options.day, clock)
    if options.calls:
        path = calls.path_for(data, day.day)
        checked = calls.prepare(day.situations, day.evaluations, path, day.day)
        log.info(
            "%d calls and absences recorded; the owner's check goes into %s. Ctrl+C stops.",
            len(checked.stretches),
            path,
        )
        page.serve(page.CallsServer(checked, clock), open_browser=not options.no_browser)
        return
    path = labels.path_for(data, day.day)
    pairs = days.pairs(day)
    if options.reminders:
        pairs |= _invented_pairs(day, max(options.reminders), clock)
    labelled = labels.prepare(pairs, path, day.day)
    log.info(
        "%d pairs in %s: Claude labelled %d, the owner %d",
        len(labelled.pairs),
        path,
        len(labelled.claude),
        len(labelled.owner),
    )
    log.info("for Claude: %s", labels.INSTRUCTIONS)


def _report(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    copy = options.copy or snapshot.latest(data)
    clock = SystemClock()
    whole = snapshot.read(copy)
    day = days.select(whole, options.day, clock)
    labelled = _labels(data, day)
    final = _final(labelled, day)
    truth = _truth(data, day)
    monitor_path = options.monitor or data / f"monitor-{day.day.isoformat()}.csv"
    used = report.machine(monitor_path) if options.monitor or monitor_path.exists() else None
    engine = sleeps.summarize(whole, day, clock, () if used is None else used.engine_vram)
    summary = days.summarize(day, final, clock, truth)
    print(report.markdown(summary, labelled, used, engine, clock, truth))
    source = HARNESS.report.from_copy.format(copy=copy.name)
    path = data / f"report-{day.day.isoformat()}.html"
    log.info("the page is %s", report.page(day, final, clock, source, path, truth))


def _replay(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    copy = options.copy or snapshot.latest(data)
    whole = snapshot.read(copy)
    clock = SystemClock()
    day = days.select(whole, options.day, clock)
    labelled = _labels(data, day)
    final = _final(labelled, day)
    truth = _truth(data, day)
    rows: list[tuple[str, str, days.Day]] = [("as recorded", "", day)]
    if options.engine or options.reminders:
        rows += _judged(options, whole, day, data, clock)
    else:
        for threshold in options.threshold or [day.evaluations[0].threshold]:
            again = replay.Replay(whole, day, threshold=threshold)
            rows.append((f"threshold {threshold:g}", f"threshold-{threshold:g}", again.run()))
    # The table counts by the labels of `label`: Remind here's alone would count a few pairs.
    counted = final if labelled is not None else {}
    print(report.replays([(name, replayed) for name, _, replayed in rows], counted, clock, truth))
    if labelled is None:
        log.info("no labels for %s yet: run label", day.day)
    for name, slug, replayed in rows[1:]:
        path = data / f"replay-{day.day.isoformat()}-{slug}.html"
        source = HARNESS.report.replayed.format(name=name)
        report.page(replayed, final, clock, source, path, truth)
    log.info("the pages are in %s", data)


def _judged(
    options: argparse.Namespace, whole: Log, day: days.Day, data: Path, clock: Clock
) -> list[tuple[str, str, days.Day]]:
    """The day judged by the engine, by this checkout's engine and with invented reminders, at
    each threshold: from the scores kept in the data folder, the engine starting for the rest."""
    real = days.summarize(day, {}, clock).reminders
    runs: list[tuple[str, str, list[tuple[str, str]]]] = []
    if options.engine:
        runs.append(("this engine", "engine", []))
    for level in options.reminders or []:
        extra = fixtures.reminders(_extra(level, real))
        runs.append((f"{level} reminders", f"reminders-{level}", extra))
    rows = []
    with ExitStack() as stack:
        kept = scores.Kept(
            scores.path_for(data, day.day),
            lambda: stack.enter_context(engine.running(options.models)),
        )
        try:
            if options.engine:
                kept.engine()  # this checkout's engine, whatever the scores kept
            for name, slug, extra in runs:
                for threshold in options.threshold or [THRESHOLD]:
                    again = replay.Replay(
                        whole, day, kept, threshold=threshold, rewrite=True, extra=extra
                    )
                    if options.threshold:
                        name_at = f"{name}, threshold {threshold:g}"
                        slug_at = f"{slug}-threshold-{threshold:g}"
                        rows.append((name_at, slug_at, again.run()))
                    else:
                        rows.append((name, slug, again.run()))
        finally:
            kept.save()
    return rows


def _convert(options: argparse.Namespace) -> None:
    data = folders.data_folder(options.data)
    day = capture.read(options.capture)
    first = SystemClock().local(day.observations[0].at)
    copy = data / f"log-{first:%Y%m%d}-capture.db"
    reminders = sample.reminders(options.sample)
    with engine.running(options.models) as model:
        capture.convert(day, reminders, model, copy)
    converted = snapshot.read(copy)
    contexts = {evaluation.context for evaluation in converted.evaluations}
    log.info(
        "%s: %d evaluations of %d contexts, %d alerts",
        copy,
        len(converted.evaluations),
        len(contexts),
        len(converted.alerts),
    )


def _invented_pairs(day: days.Day, level: int, clock: Clock) -> dict[str, days.Pair]:
    """The pairs the invented reminders that reach `level` would have in the day's contexts,
    with the remainder `core` reads from each condition."""
    real = days.summarize(day, {}, clock).reminders
    contexts = dict.fromkeys(e.context for e in day.evaluations if not e.failed)
    start = clock.local(day.evaluations[0].context_since)
    pairs = {}
    for number, (condition, action) in enumerate(fixtures.reminders(_extra(level, real)), 1):
        remainder = read(condition, start).remainder
        if not remainder:  # only a time or situations: never judged, so no pair to label
            continue
        revision = Revision(-number, -number, 1, condition, action, remainder)
        for context in contexts:
            pair = days.Pair(context, revision)
            pairs[pair.key] = pair
    return pairs


def _extra(level: int, real: int) -> int:
    if level < real:
        raise HarnessError(f"the day has {real} reminders already, more than {level}")
    return level - real


def _labels(data: Path, day: days.Day) -> labels.Labels | None:
    path = labels.path_for(data, day.day)
    return labels.load(path) if path.exists() else None


def _final(labelled: labels.Labels | None, day: days.Day) -> dict[str, bool]:
    """The labels that count: the owner's, then the pairs the owner asked for with Remind here,
    then Claude's (ADR-0031)."""
    asked = labels.asked(day)
    return asked if labelled is None else labelled.final(asked)


def _truth(data: Path, day: days.Day) -> Truth:
    """The day's situations as they were: as the owner checked them with label --calls, else as
    recorded."""
    path = calls.path_for(data, day.day)
    return Truth.of(day.situations, calls.load(path) if path.exists() else None)


def _latest_labels(folder: Path) -> Path:
    found = sorted(folder.glob("labels-*.json"))
    if not found:
        raise HarnessError(f"there are no labels in {folder}: run label first")
    return found[-1]


def _integers(text: str) -> list[int]:
    try:
        return [int(part) for part in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"not whole numbers: {text}") from None


def _decimals(text: str) -> list[float]:
    try:
        return [float(part) for part in text.split(",")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"not numbers: {text}") from None


if __name__ == "__main__":
    sys.exit(main())
