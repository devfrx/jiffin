"""Italian only where ADR-0026 allows it: a pre-commit hook that fails on an Italian word in the
code, in its comments or in its docs.

A word is Italian when it has an accented vowel, or when it is a word of the language files
themselves, but for the few that are English too (`ENGLISH`). It may stand between quotes, as an
example of what the user writes ("quando apro Figma dopo le 23"), and in a code span. Elsewhere
it fails:

- in comments and docstrings, everywhere but the language files, `src/jiffin/lang/it/`;
- in the string literals and the pages of `src`, but for the examples of what the user writes
  in `ui/__main__.py` and in the rewrite prompt (`EXAMPLES`), and a few names (`NAMES`);
- in `docs/design/` and the README;
- in the migrations after 0002, which may name the answers 0.2 stored to translate them.

The accepted ADRs, the CHANGELOG, the mockups, the tests' literals and the fixtures are not read.
Given file names, it checks those; without, every file git tracks, as the hook runs it. It uses
the standard library only.
"""

import io
import re
import subprocess
import sys
import tokenize
import tomllib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent.parent
LANGUAGE = PurePosixPath("src/jiffin/lang/it")
EXAMPLES = (
    PurePosixPath("src/jiffin/ui/__main__.py"),
    PurePosixPath("src/jiffin/engine/prompts.py"),
)
"""Files whose literals are examples of what the user writes: those of a developer's tool
(ADR-0026), and those the rewrite prompt shows the model, which change only with its version
(ADR-0008)."""
MIGRATIONS = PurePosixPath("src/jiffin/store/migrations")
ANSWERS = frozenset({"fatto", "utile", "rimanda", "non_qui", "chiuso"})
"""The answers version 0.2 stored, which migration 0003 translates: the migrations may name them
to translate them."""
NAMES = {
    PurePosixPath("src/jiffin/harness/folders.py"): frozenset({"etichette.json"}),
    PurePosixPath("src/jiffin/platform/address.py"): frozenset({
        "Registrazione con videocamera e microfono",
        "Registrazione con microfono",
        "Contenuti del desktop condivisi",
    }),
}  # fmt: skip
"""Literals a file may hold whole, as names: a file of the prototype's that keeps its name, and
what Chromium writes in Italian on a tab that records, which Jiffin reads in any language of its
own."""
NOT_READ = (
    PurePosixPath("docs/adr"),
    PurePosixPath("docs/design/mockups"),
    PurePosixPath("tests/fixtures"),
    LANGUAGE,
)
ENGLISH = frozenset({
    # English words.
    "in", "no", "per", "due", "come", "end", "fine", "era", "meta", "solo", "precise", "state",
    "app", "file", "menu", "log", "download", "video", "byte", "email", "mail", "slide", "week",
    "weekend", "min", "prompt", "call", "monitor", "computer", "offline", "internet", "via", "wi",
    "fi",
    # Names, keys and units.
    "jiffin", "windows", "win", "alt", "backspace", "chrome", "brave", "vivaldi", "mica", "ai",
    "pc", "gb", "sha", "km", "euro", "changelog",
})  # fmt: skip
"""Words of the language files that are English too, or names: "file", "menu", "Chrome"."""

ACCENTED = re.compile(r"[àèéìíòóùúÀÈÉÌÍÒÓÙÚ]")
WORD = re.compile(r"[^\W\d_]+['’]?")
"""A word, with the apostrophe of an elision: "l'", "un'ora" is "un'" and "ora"."""
QUOTED = re.compile(r'"[^"]*"|«[^»]*»|“[^”]*”|`[^`]*`')
"""An example between quotes, or a code span; it may run over lines."""
FENCE = re.compile(r"^ *```.*$", re.MULTILINE)
PLACEHOLDER = re.compile(r"\{[^{}]*\}")
ESCAPE = re.compile(r"\\[nrt]")
HEXADECIMAL = re.compile(r"\b(?:0[xX])?(?=[0-9A-Fa-f]*\d)[0-9A-Fa-f]+\b")
"""A hexadecimal number, as an error's code or the parts of a GUID: its letters, "1DA5D803",
are no words."""


@dataclass(frozen=True, slots=True)
class Finding:
    path: PurePosixPath
    line: int
    word: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.word}"


def vocabulary(folder: Path = REPO / LANGUAGE) -> frozenset[str]:
    """The words of the language files, in lower case: the words of their texts, and the keys of
    their tables of words by number ("ventitré" = 23)."""
    words: set[str] = set()
    for path in sorted(folder.glob("*.toml")):
        with path.open("rb") as file:
            words.update(_words(tomllib.load(file)))
    return frozenset(words)


def _words(node: object) -> Iterator[str]:
    if isinstance(node, str):
        yield from (word.lower() for word in WORD.findall(PLACEHOLDER.sub(" ", node)))
    elif isinstance(node, dict):
        if node and all(type(value) is int for value in node.values()):
            yield from (word.lower() for key in node for word in WORD.findall(key))
        for value in node.values():
            yield from _words(value)
    elif isinstance(node, list):
        for value in node:
            yield from _words(value)


def italian(
    text: str, words: frozenset[str], line: int = 1, *, quotes: bool = True
) -> Iterator[tuple[int, str]]:
    """The Italian words of `text`, with their lines, counted from `line`; with `quotes`, only
    those outside quotes and code spans."""
    if quotes:
        text = QUOTED.sub(lambda quoted: re.sub(r"[^\n]", " ", quoted[0]), text)
    for number, row in enumerate(text.split("\n"), start=line):
        for word in WORD.findall(HEXADECIMAL.sub(" ", row)):
            lower = word.lower()
            # An English possessive, "Rimanda's", is the word without its apostrophe.
            forms = (lower, lower.rstrip("'’"))
            if len(lower) > 1 and (
                ACCENTED.search(lower)
                or any(form in words and form not in ENGLISH for form in forms)
            ):
                yield number, word


def findings(path: PurePosixPath, text: str, words: frozenset[str]) -> list[Finding]:
    """The Italian words of a file where ADR-0026 does not allow them."""
    found = [Finding(path, line, word) for line, word in _check(path, text, words)]
    return sorted(found, key=lambda finding: finding.line)


def _check(path: PurePosixPath, text: str, words: frozenset[str]) -> Iterator[tuple[int, str]]:
    if any(path.is_relative_to(folder) for folder in NOT_READ):
        return
    in_src = path.parts[0] == "src"
    match path.suffix:
        case ".py" | ".spec":
            yield from _python(path, text, words, literals=in_src and path not in EXAMPLES)
        case ".qml" if in_src:
            yield from _qml(text, words)
        case ".md" if path.parent == PurePosixPath("docs/design") or path.name == "README.md":
            yield from italian(FENCE.sub(lambda fence: " " * len(fence[0]), text), words)
        case ".html" | ".css" | ".js" if in_src:
            # A page of `src` holds no Italian at all, quoted or not.
            yield from italian(text, words, quotes=False)
        case ".sql" if path.parent == MIGRATIONS and int(path.name[:4]) > 2:
            yield from _sql(text, words)
        case ".toml" | ".yaml" | ".yml" | ".ini":
            yield from _hash_comments(text, words)
        case _ if path.name in (".gitignore", ".gitattributes"):
            yield from _hash_comments(text, words)


def _python(
    path: PurePosixPath, text: str, words: frozenset[str], *, literals: bool
) -> Iterator[tuple[int, str]]:
    """Comments and docstrings; with `literals`, every other string too."""
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    comments: list[tokenize.TokenInfo] = []
    for token in tokens:
        if token.type == tokenize.COMMENT:
            if comments and token.start[0] != comments[-1].start[0] + 1:
                yield from _comment_block(comments, words)
                comments = []
            comments.append(token)
    if comments:
        yield from _comment_block(comments, words)
    for token, statement in _strings(tokens):
        inner = _inner(token)
        if statement or (literals and inner not in NAMES.get(path, ())):
            yield from italian(ESCAPE.sub(" ", inner), words, token.start[0])


def _comment_block(
    comments: list[tokenize.TokenInfo], words: frozenset[str]
) -> Iterator[tuple[int, str]]:
    """Comments on lines in a row, as one text: an example may run over lines."""
    text = "\n".join(comment.string.lstrip("#") for comment in comments)
    yield from italian(text, words, comments[0].start[0])


def _strings(tokens: list[tokenize.TokenInfo]) -> Iterator[tuple[tokenize.TokenInfo, bool]]:
    """Each string token, and whether it stands as a statement of its own, as a docstring does.
    The parts of an f-string are literals."""
    skip = {tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
    logical: list[tokenize.TokenInfo] = []
    for token in tokens:
        if token.type in skip:
            continue
        if token.type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            statement = all(part.type == tokenize.STRING for part in logical)
            for part in logical:
                if part.type in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
                    yield part, statement
            logical = []
        else:
            logical.append(token)


def _inner(token: tokenize.TokenInfo) -> str:
    """A string token's text without its prefix and its quotes."""
    if token.type == tokenize.FSTRING_MIDDLE:
        return token.string
    body = token.string.lstrip("rRbBuUfF")
    quote = body[:3] if body[:3] in ('"""', "'''") else body[:1]
    if not body.startswith(quote) or not body.endswith(quote):
        return body
    return body[len(quote) : len(body) - len(quote)]


def _qml(text: str, words: frozenset[str]) -> Iterator[tuple[int, str]]:
    """Comments and string literals, found by a scanner that knows QML's strings and comments."""
    block: list[tuple[int, str]] = []
    index, line = 0, 1
    while index < len(text):
        char = text[index]
        if text.startswith("//", index):
            end = text.find("\n", index)
            end = len(text) if end == -1 else end
            if block and line != block[-1][0] + 1:
                yield from _qml_block(block, words)
                block = []
            block.append((line, text[index + 2 : end]))
            index = end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end == -1 else end
            yield from italian(text[index + 2 : end], words, line)
            line += text.count("\n", index, end)
            index = end + 2
        elif char in "\"'`":
            end = index + 1
            while end < len(text) and text[end] != char:
                end += 2 if text[end] == "\\" else 1
            yield from italian(ESCAPE.sub(" ", text[index + 1 : end]), words, line)
            line += text.count("\n", index, end)
            index = end + 1
        else:
            line += char == "\n"
            index += 1
    if block:
        yield from _qml_block(block, words)


def _qml_block(block: list[tuple[int, str]], words: frozenset[str]) -> Iterator[tuple[int, str]]:
    yield from italian("\n".join(comment for _, comment in block), words, block[0][0])


def _sql(text: str, words: frozenset[str]) -> Iterator[tuple[int, str]]:
    """Comments and literals; an answer of 0.2, `'non_qui'`, may be named to be translated."""
    answers = re.compile("|".join(f"'{answer}'" for answer in sorted(ANSWERS)))
    yield from italian(answers.sub(lambda answer: " " * len(answer[0]), text), words)


def _hash_comments(text: str, words: frozenset[str]) -> Iterator[tuple[int, str]]:
    """The comments of a configuration file: from a "#" outside quotes to the end of its line."""
    for number, row in enumerate(text.split("\n"), start=1):
        quote = ""
        for index, char in enumerate(row):
            if quote:
                quote = "" if char == quote else quote
            elif char in "\"'":
                quote = char
            elif char in "#;" and (char == "#" or index == 0):
                yield from italian(row[index + 1 :], words, number)
                break


def _tracked() -> list[str]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [name for name in listing.split("\0") if name]


def main(arguments: Iterable[str]) -> int:
    # The words found are Italian: on a pipe Python would write them in the code page.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    names = list(arguments) or _tracked()
    words = vocabulary()
    found: list[Finding] = []
    for name in names:
        path = Path(name)
        if not path.is_absolute():
            path = REPO / path
        if not path.is_file():
            continue
        relative = PurePosixPath(path.resolve().relative_to(REPO).as_posix())
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        found += findings(relative, text, words)
    for finding in found:
        print(finding)
    if found:
        print(
            f"{len(found)} Italian words outside the language files (ADR-0026): move the text "
            "to src/jiffin/lang/it/, write it in English, or quote it as an example of what the "
            "user writes."
        )
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
