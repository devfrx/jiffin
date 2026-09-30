"""What the user is working on: the foreground app, its title and the tab address (ADR-0004)."""

import re
from dataclasses import dataclass

BROWSER_SUFFIXES = {
    "vivaldi.exe": " - Vivaldi",
    "chrome.exe": " - Google Chrome",
    "brave.exe": " - Brave",
}
"""The suffix each supported browser adds to the titles of its tab windows, by app."""
_COUNTER = re.compile(r"^\(\d+\+?\) ")
_MARKER_AT_START = re.compile(r"^[●*]\s*")
_MARKER_AT_END = re.compile(r"\s*[●*]$")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_QUERY_OR_FRAGMENT = re.compile(r"[?#].*", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Context:
    """A normalized context: the key of the debounce, of the pair cache and of "not here".

    Two contexts are the same when all three values are equal. Build one from what Windows
    shows with `normalize`; the constructor takes values that are normalized already.
    """

    app: str
    title: str
    address: str | None
    """Only in the supported browsers, and None when the address bar cannot be read."""


@dataclass(frozen=True, slots=True)
class Observation:
    """What was in the foreground at a moment: what the context port delivers."""

    at: int
    """UTC milliseconds."""
    context: Context | None
    """None when the foreground is not a context: a private window, or one of Jiffin's."""


def normalize(app: str, title: str, address: str | None) -> Context:
    return Context(_app(app), _title(title), _address(address))


def _app(app: str) -> str:
    return app.lower()


def _title(title: str) -> str:
    title = title.strip()
    for suffix in BROWSER_SUFFIXES.values():
        title = title.removesuffix(suffix)
    title = _COUNTER.sub("", title)
    title = _MARKER_AT_START.sub("", title)
    title = _MARKER_AT_END.sub("", title)
    return title.strip()


def _address(address: str | None) -> str | None:
    if address is None:
        return None
    address = _SCHEME.sub("", address.strip())
    address = address.removeprefix("www.")
    address = _QUERY_OR_FRAGMENT.sub("", address)
    return address.removesuffix("/") or None
