"""The situations of a condition as JSON, in the `situations` column of `revision` (ADR-0028)."""

import json

import pytest

from jiffin.core.situations import BATTERY, HOME, YES, Ends, Holds, Lasts, Situation, Term
from jiffin.store import terms


@pytest.mark.parametrize(
    "situations",
    [
        (),
        (Holds(Situation.CALL),),
        (Holds(Situation.CALL, "zoom"), Lasts(60, Situation.CALL, "zoom")),
        (Ends(Situation.AWAY, YES),),
        (Lasts(20),),
        (Holds(Situation.NETWORK, HOME), Holds(Situation.POWER, BATTERY), Ends(Situation.CALL)),
    ],
    ids=[
        "none",
        "any call",
        "a call on an app, lasting",
        "the end of away",
        "the thing the judge checks, lasting",
        "several, in the order written",
    ],
)
def test_every_kind_of_term_comes_back(situations: tuple[Term, ...]) -> None:
    assert terms.loads(terms.dumps(situations)) == situations


def test_the_shape_is_the_one_the_module_documents() -> None:
    written = terms.dumps((Holds(Situation.CALL, "zoom"), Lasts(20)))
    assert json.loads(written) == [
        {"holds": {"situation": "call", "value": "zoom"}},
        {"lasts": {"minutes": 20, "situation": None, "value": None}},
    ]
    assert terms.dumps(()) == "[]"


def test_a_term_of_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        terms.loads(json.dumps([{"starts": {"situation": "call", "value": None}}]))
