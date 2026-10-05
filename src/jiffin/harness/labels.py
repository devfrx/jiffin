"""`label`: whether each remainder is true in each context the engine judged (ADR-0003, ADR-0021).

Every (evaluated context, reminder) pair of a day goes into `labels-<day>.json` in the data
folder. Claude labels them all, with the texts in front of it, as on 2026-09-28; then the owner
labels a share of them on a local page, without seeing Claude's labels, and where both labelled
a pair the owner's label counts. A label is on the remainder, the condition without its time:
the code checks the time. Labels are keyed by the texts, so they outlive a new copy of the log,
a replay or another threshold.
"""

import json
import os
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jiffin.harness.day import Pair
from jiffin.harness.errors import HarnessError

FORMAT = 2
"""Format 1 named the condition: from 0.2 a pair carries the remainder (ADR-0021)."""
OWNER_SHARE = 30
"""Pairs the owner labels by default: as many alerts as the owner judged on 2026-09-28."""

INSTRUCTIONS = (
    "For every pair, decide whether the reminder's remainder (the Quando box without its time: "
    "the code checks the time) is true in that context: not whether the reminder would have been "
    'useful. Put true or false under "claude", by key, and list under "uncertain" the keys you '
    "are unsure about."
)


@dataclass(slots=True)
class Labels:
    path: Path
    day: date
    pairs: list[dict[str, Any]]
    """The pairs to label, texts included: key, app, title, address, remainder, action."""
    claude: dict[str, bool] = field(default_factory=dict)
    uncertain: list[str] = field(default_factory=list)
    owner: dict[str, bool] = field(default_factory=dict)

    def final(self) -> dict[str, bool]:
        """The owner's label where there is one, Claude's elsewhere."""
        return self.claude | self.owner

    def agreement(self) -> tuple[int, int]:
        """On how many of the pairs both labelled the owner agrees with Claude."""
        both = [key for key in self.owner if key in self.claude]
        return sum(self.owner[key] == self.claude[key] for key in both), len(both)

    def answer(self, key: str, relevant: object) -> None:
        """The owner's label for one pair, saved at once."""
        if key not in {pair["key"] for pair in self.pairs}:
            raise ValueError("unknown pair")
        if not isinstance(relevant, bool):
            raise TypeError("a label is true or false")
        self.owner[key] = relevant
        self.save()

    def save(self) -> None:
        record = {
            "format": FORMAT,
            "day": self.day.isoformat(),
            "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "instructions": INSTRUCTIONS,
            "pairs": self.pairs,
            "claude": self.claude,
            "uncertain": self.uncertain,
            "owner": self.owner,
        }
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)


def path_for(folder: Path, day: date) -> Path:
    return folder / f"labels-{day.isoformat()}.json"


def load(path: Path) -> Labels:
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise HarnessError(f"the labels cannot be read: {error.strerror}: run label") from None
    except json.JSONDecodeError as error:
        raise HarnessError(f"{path.name} is not valid JSON: {error}") from None
    if record.get("format") != FORMAT:
        raise HarnessError(
            f"{path.name} has format {record.get('format')}, not {FORMAT}: "
            "move it away and run label again"
        )
    return Labels(
        path,
        date.fromisoformat(record["day"]),
        record["pairs"],
        _labels(record.get("claude", {}), "claude"),
        list(record.get("uncertain", [])),
        _labels(record.get("owner", {}), "owner"),
    )


def prepare(pairs: Mapping[str, Pair], path: Path, day: date) -> Labels:
    """Write the day's pairs, keeping every label already given."""
    labels = load(path) if path.exists() else Labels(path, day, [])
    labels.pairs = [
        {
            "key": pair_key,
            "app": pair.context.app,
            "title": pair.context.title,
            "address": pair.context.address,
            "remainder": pair.revision.remainder,
            "action": pair.revision.action,
        }
        for pair_key, pair in pairs.items()
    ]
    labels.save()
    return labels


def owner_share(labels: Labels, size: int) -> list[str]:
    """The pairs for the owner: those Claude is unsure about first, then others at random."""
    keys = [pair["key"] for pair in labels.pairs]
    unsure = [key for key in keys if key in labels.uncertain]
    others = [key for key in keys if key not in labels.uncertain]
    random.Random(labels.day.isoformat()).shuffle(others)
    return (unsure + others)[:size]


def _labels(values: Mapping[str, object], who: str) -> dict[str, bool]:
    if not all(isinstance(value, bool) for value in values.values()):
        raise HarnessError(f'every label under "{who}" must be true or false')
    return {key: bool(value) for key, value in values.items()}
