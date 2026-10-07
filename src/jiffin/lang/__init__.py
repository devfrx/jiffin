"""The app's language (ADR-0026): the Italian it shows, in the files of `it/`, and the rules that
write it. No Qt, and nothing else from jiffin: every part may import it.

Each language file has a module of its own that reads it once, at import, into frozen
dataclasses: a file that cannot be read, a key missing or one too many raise `CatalogError`,
which stops the tests and the start. This module reads nothing, so that the app can still say it
cannot start.
"""

import tomllib
import types
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any, cast, get_type_hints

FOLDER: Traversable = resources.files("jiffin.lang") / "it"
"""The files of the app's language, Italian."""


class CatalogError(Exception):
    """A language file that cannot be read, or whose keys are not the ones the code reads."""


@dataclass(frozen=True, slots=True)
class Plural:
    """A text with a form for each count, by the Italian rule: `one` for 1, `other` for any other
    count, 0 included."""

    one: str
    other: str

    def format(self, count: int, **values: object) -> str:
        """The form for `count`, with `{count}` and the other placeholders filled."""
        return (self.one if count == 1 else self.other).format(count=count, **values)


def read[T](kind: type[T], name: str) -> T:
    """The language file `name`, as `kind`: a frozen dataclass whose fields are the file's keys.
    A field is a text, a `Plural`, a table of texts by key (`Mapping[str, str]`) or a table of
    its own, another such dataclass."""
    try:
        with (FOLDER / name).open("rb") as file:
            table = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise CatalogError(f"{name}: {error}") from error
    return cast(T, _table(kind, table, name, ""))


def _table(kind: type[Any], table: dict[str, Any], name: str, path: str) -> object:
    hints = get_type_hints(kind)
    keys = [field.name for field in fields(kind)]
    missing = [key for key in keys if key not in table]
    extra = [key for key in table if key not in keys]
    if missing or extra:
        problems = [f"{path}{key} is missing" for key in missing]
        problems += [f"{path}{key} is not read" for key in extra]
        raise CatalogError(f"{name}: {', '.join(problems)}")
    return kind(**{key: _value(hints[key], table[key], name, path + key) for key in keys})


def _value(kind: object, value: object, name: str, key: str) -> object:
    if kind is str:
        if not isinstance(value, str):
            raise CatalogError(f"{name}: {key} is not a text")
        return value
    if kind == Mapping[str, str]:
        if not isinstance(value, dict) or not all(isinstance(text, str) for text in value.values()):
            raise CatalogError(f"{name}: {key} is not a table of texts")
        return types.MappingProxyType(value)
    if isinstance(kind, type) and is_dataclass(kind):
        if not isinstance(value, dict):
            raise CatalogError(f"{name}: {key} is not a table")
        return _table(kind, value, name, f"{key}.")
    raise TypeError(f"{key}: a field of type {kind} cannot be read from a language file")
