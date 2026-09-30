"""`python -m jiffin.harness <command>`: the measurements of ADR-0017."""

import argparse
import logging
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from jiffin.core.model import ModelError
from jiffin.harness import engine, folders, monitor, sample
from jiffin.harness.errors import HarnessError

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
    engine_options = argparse.ArgumentParser(add_help=False)
    engine_options.add_argument(
        "--models",
        type=Path,
        default=folders.app_folder() / "models",
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


if __name__ == "__main__":
    sys.exit(main())
