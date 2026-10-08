"""The situations of a condition as JSON, for the `situations` column of `revision` (ADR-0028).

The shape is the store's, on the terms of `core.situations`, in the order the condition wrote
them; none is `[]`:

    [{"holds": {"situation": "call", "value": "zoom"}},
     {"lasts": {"minutes": 60, "situation": "call", "value": null}},
     {"ends": {"situation": "away", "value": "yes"}}]

A null `situation` in `lasts` is the thing the judge checks; a null `value` is any call.
"""

import json
from collections.abc import Iterable
from typing import Any

from jiffin.core.situations import Ends, Holds, Lasts, Situation, Term


def dumps(terms: Iterable[Term]) -> str:
    return json.dumps([_term(term) for term in terms])


def loads(text: str) -> tuple[Term, ...]:
    return tuple(_term_of(found) for found in json.loads(text))


def _term(term: Term) -> dict[str, Any]:
    match term:
        case Holds(situation, value):
            return {"holds": {"situation": situation.value, "value": value}}
        case Ends(situation, value):
            return {"ends": {"situation": situation.value, "value": value}}
        case Lasts(minutes, situation, value):
            kind = None if situation is None else situation.value
            return {"lasts": {"minutes": minutes, "situation": kind, "value": value}}


def _term_of(found: dict[str, Any]) -> Term:
    [(kind, term)] = found.items()
    match kind:
        case "holds":
            return Holds(Situation(term["situation"]), term["value"])
        case "ends":
            return Ends(Situation(term["situation"]), term["value"])
        case "lasts":
            situation = None if term["situation"] is None else Situation(term["situation"])
            return Lasts(term["minutes"], situation, term["value"])
    raise ValueError(f"a term of an unknown kind: {kind}")
