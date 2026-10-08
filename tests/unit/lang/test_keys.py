"""The language files against the code that reads them (ADR-0026): every key the code asks for
exists, every key of the files is asked for, each text gets the placeholders it holds, and each
plural has its forms.

Python's own reads are typed, so mypy finds a key missing there; this reads the rest: QML's keys
by name, the harness's pages, and which keys the Python reaches, through the names it gives them
("texts = TEXTS.tray_list", "WORDS = TIME.write") and the parameters its calls fill
("fused(WORDS.of_the)").
"""

import ast
import re
import string
from collections.abc import Iterator, Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path

from jiffin.lang import Plural
from jiffin.lang.harness import HARNESS
from jiffin.lang.situations import SITUATIONS
from jiffin.lang.texts import TEXTS
from jiffin.lang.time import TIME

SOURCE = Path(__file__).resolve().parents[3] / "src" / "jiffin"
ROOTS: Mapping[str, object] = {
    "TEXTS": TEXTS,
    "TIME": TIME,
    "HARNESS": HARNESS,
    "SITUATIONS": SITUATIONS,
}
QML_KEY = re.compile(r'Catalog\.text\("([^"]+)"\)')
PAGE_KEY = re.compile(r"\bt\.([\w.]+)")
PAGE_FORMAT = re.compile(r"\bt\.([\w.]+)\.format\(([^)]*)\)")
SCRIPT_KEY = re.compile(r"\bT\.(\w+)")
SCRIPT_FILL = re.compile(r"\bfill\(T\.(\w+), \{([^}]*)\}\)")

type Key = tuple[str, ...]
"""A key by its path from the root: ("TEXTS", "alert", "done")."""


def leaves(node: object, path: Key) -> Iterator[tuple[Key, object]]:
    """Every key of a file, by its path from the root: a text, a plural, a list or a table."""
    if is_dataclass(node) and not isinstance(node, Plural | type):
        for field in fields(node):
            yield from leaves(getattr(node, field.name), (*path, field.name))
    else:
        yield path, node


def find(path: Key) -> object:
    """The value at `path`; KeyError when the files have no such key."""
    node = ROOTS[path[0]]
    for name in path[1:]:
        if not is_dataclass(node) or name not in {field.name for field in fields(node)}:
            raise KeyError(".".join(path))
        node = getattr(node, name)
    return node


def placeholders(text: str) -> set[str]:
    names = set()
    for _, name, _, _ in string.Formatter().parse(text):
        if name is not None:
            assert name.isidentifier(), f"{text!r}: a placeholder is named, {{name}}"
            names.add(name)
    return names


def holds(value: object) -> set[str]:
    if isinstance(value, Plural):
        return placeholders(value.one) | placeholders(value.other)
    assert isinstance(value, str), value
    return placeholders(value)


class Scope:
    """The names a module, or one of its functions, gives to the expressions it assigns, and the
    keys its parameters are given. A name stands for all its values wherever it is read: a
    function that gives one name texts with different placeholders fails
    test_each_text_gets_the_placeholders_it_holds, so it names them apart."""

    def __init__(self, nodes: list[ast.stmt], outer: "Scope | None" = None) -> None:
        self.outer = outer
        self.names: dict[str, list[ast.expr]] = {}
        self.parameters: dict[str, set[Key]] = {}
        for node in (child for statement in nodes for child in ast.walk(statement)):
            if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    self._bind(target, node.value)

    def _bind(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            self.names.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Tuple):
            # "once, once_every = ONCE[unit]": each name takes its place in the tuples.
            for index, element in enumerate(target.elts):
                if isinstance(element, ast.Name):
                    for row in self.rows(value):
                        if isinstance(row, ast.Tuple) and index < len(row.elts):
                            self.names.setdefault(element.id, []).append(row.elts[index])

    def values(self, name: str) -> list[ast.expr]:
        if name in self.names:
            return self.names[name]
        return [] if self.outer is None else self.outer.values(name)

    def rows(self, node: ast.expr) -> list[ast.expr]:
        """The values `node` may stand for when it takes an item of a table the code wrote,
        "ONCE[unit]"; none when it takes an item of something else."""
        if not (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)):
            return []
        tables = [table for table in self.values(node.value.id) if isinstance(table, ast.Dict)]
        return [value for table in tables for value in table.values]

    def paths(self, node: ast.expr, seen: frozenset[str] = frozenset()) -> set[Key]:
        """The paths from a root that `node` may stand for: none when it is not a key."""
        match node:
            case ast.Attribute(value=value, attr=attr):
                return {(*path, attr) for path in self.paths(value, seen)}
            case ast.Name(id=name) if name in ROOTS:
                return {(name,)}
            case ast.Name(id=name) if name not in seen:
                return self.parameters.get(name, set()) | {
                    path for value in self.values(name) for path in self.paths(value, seen | {name})
                }
            case ast.IfExp(body=body, orelse=orelse):
                return self.paths(body, seen) | self.paths(orelse, seen)
            case ast.Subscript(value=value):
                rows = self.rows(node)
                if not rows:
                    return self.paths(value, seen)  # an item of a table of the files
                return {path for row in rows for path in self.paths(row, seen)}
        return set()

    def passed(self, call: ast.Call) -> set[str]:
        """The names a call gives values to; a plural's count comes first, by position."""
        names = {"count"} if call.args else set()
        for keyword in call.keywords:
            if keyword.arg is not None:
                names.add(keyword.arg)
            elif isinstance(keyword.value, ast.Name):
                for table in self.values(keyword.value.id):
                    assert isinstance(table, ast.Dict), ast.unparse(call)
                    names |= {
                        key.value
                        for key in table.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    }
        return names


def scopes() -> Iterator[tuple[Path, Scope, list[ast.AST]]]:
    """Each module of the app and the harness, and each of its functions, with the nodes that
    are theirs alone."""
    for module_path in sorted(SOURCE.rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        inner = {id(child) for function in functions for child in ast.walk(function)}
        module = Scope(
            [
                statement
                for statement in tree.body
                if not isinstance(statement, ast.FunctionDef | ast.ClassDef)
            ]
        )
        own = {function: Scope(function.body, module) for function in functions}
        give_parameters(tree, module, own)
        yield module_path, module, [node for node in ast.walk(tree) if id(node) not in inner]
        for function, scope in own.items():
            yield module_path, scope, list(ast.walk(function))


def give_parameters(tree: ast.Module, module: Scope, own: Mapping[ast.FunctionDef, Scope]) -> None:
    """Give the parameters of the module's functions the keys its calls pass them, one call deep:
    after "fused(WORDS.of_the)", fused's "preposition.joined" is TIME.read.of_the.joined."""
    definitions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    callers = {id(child): scope for function, scope in own.items() for child in ast.walk(function)}
    given: list[tuple[Scope, str, set[Key]]] = []
    for call in ast.walk(tree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            continue
        definition = definitions.get(call.func.id)
        if definition is None:
            continue
        caller = callers.get(id(call), module)
        arguments = (*definition.args.posonlyargs, *definition.args.args)
        pairs = [
            *zip((argument.arg for argument in arguments), call.args),
            *((keyword.arg, keyword.value) for keyword in call.keywords),
        ]
        given += [
            (own[definition], name, caller.paths(value))
            for name, value in pairs
            if name is not None
        ]
    for scope, name, keys in given:
        scope.parameters.setdefault(name, set()).update(keys)


def python_reads() -> set[Key]:
    return {
        path
        for _, scope, nodes in scopes()
        for node in nodes
        if isinstance(node, ast.Attribute | ast.Subscript)
        for path in scope.paths(node)
    }


def python_formats() -> Iterator[tuple[str, set[Key], set[str]]]:
    """Each `.format()` of a key: where, the keys it may be, and the names it passes."""
    for module_path, scope, nodes in scopes():
        for node in nodes:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            keys = scope.paths(node.func.value) if node.func.attr == "format" else set()
            if keys:
                yield f"{module_path.name}:{node.lineno}", keys, scope.passed(node)


def pages() -> Iterator[tuple[str, str]]:
    for page in sorted((SOURCE / "harness" / "pages").glob("*.html")):
        yield page.name, page.read_text(encoding="utf-8")


def section(page: str) -> str:
    """The texts a page's script gets as `T`: those of the section named as the page,
    "label.html" those of [label]."""
    return Path(page).stem


def page_formats() -> Iterator[tuple[str, set[Key], set[str]]]:
    for name, text in pages():
        for found in PAGE_FORMAT.finditer(text):
            names = set(re.findall(r"(\w+)\s*=", found[2]))
            yield name, {("HARNESS", *found[1].split("."))}, names
        for found in SCRIPT_FILL.finditer(text):
            names = {part.split(":")[0].strip() for part in found[2].split(",")}
            yield name, {("HARNESS", section(name), found[1])}, names


def qml_keys() -> set[Key]:
    return {
        ("TEXTS", *key.split("."))
        for qml in sorted((SOURCE / "ui" / "qml").glob("*.qml"))
        for key in QML_KEY.findall(qml.read_text(encoding="utf-8"))
    }


def page_keys() -> set[Key]:
    keys = set()
    for name, text in pages():
        keys |= {("HARNESS", *key.split(".")) for key in PAGE_KEY.findall(text)}
        keys |= {("HARNESS", section(name), key) for key in SCRIPT_KEY.findall(text)}
    return {key[:-1] if key[-1] == "format" else key for key in keys}


def test_every_key_qml_asks_for_is_a_text() -> None:
    for key in qml_keys():
        assert isinstance(find(key), str), ".".join(key)


def test_every_key_a_page_asks_for_exists() -> None:
    for key in page_keys():
        find(key)


def test_every_key_the_python_reaches_exists() -> None:
    for key in {key for _, keys, _ in python_formats() for key in keys}:
        find(key)


def test_every_key_of_the_files_is_used() -> None:
    used = python_reads() | qml_keys() | page_keys()
    unused = [
        ".".join(path)
        for root, value in ROOTS.items()
        for path, _ in leaves(value, (root,))
        if not any(read[: len(path)] == path for read in used)
    ]
    assert unused == []


def test_each_text_gets_the_placeholders_it_holds() -> None:
    for where, keys, passed in [*python_formats(), *page_formats()]:
        held = [holds(find(key)) for key in keys]
        for key, names in zip(keys, held, strict=True):
            assert names <= passed, f"{where}: {'.'.join(key)} holds {names - passed} too"
        assert passed <= set().union(*held), f"{where}: {passed - set().union(*held)} unused"


def test_each_text_with_placeholders_is_filled_somewhere() -> None:
    filled = {key for _, keys, _ in [*python_formats(), *page_formats()] for key in keys}
    unfilled = [
        ".".join(path)
        for root, value in ROOTS.items()
        for path, text in leaves(value, (root,))
        if isinstance(text, str | Plural) and holds(text) and path not in filled
    ]
    assert unfilled == []


def test_each_plural_has_its_forms() -> None:
    plurals = [
        (path, value)
        for root, value in ROOTS.items()
        for path, value in leaves(value, (root,))
        if isinstance(value, Plural)
    ]
    assert plurals
    for path, plural in plurals:
        assert plural.one and plural.other and plural.one != plural.other, ".".join(path)
        assert placeholders(plural.one) - {"count"} == placeholders(plural.other) - {"count"}
