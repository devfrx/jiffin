"""The invented reminders of `tests/fixtures`, in Italian: the extra ones of `replay --reminders`.

They are invented, as everything in the repository is (ADR-0017), and varied: names to find,
types of work, vague wishes, negations, sites and apps.
"""

import json

from jiffin.harness.errors import HarnessError
from jiffin.harness.folders import REPOSITORY

REMINDERS = REPOSITORY / "tests" / "fixtures" / "reminders.json"


def reminders(count: int) -> list[tuple[str, str]]:
    """The first `count` invented reminders, as (condition, action)."""
    found = json.loads(REMINDERS.read_text(encoding="utf-8"))
    if count > len(found):
        raise HarnessError(f"there are {len(found)} invented reminders, not {count}")
    return [(reminder["condition"], reminder["action"]) for reminder in found[:count]]
