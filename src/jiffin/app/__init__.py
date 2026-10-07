"""The composition root: creates the adapters, connects the ports, starts the threads and Qt."""

import sys

from jiffin.app import win32
from jiffin.lang import CatalogError

UNREADABLE = "Jiffin cannot start: its language files cannot be read.\n\n{error}"
"""The one message the language files cannot hold: technical, in English (ADR-0026)."""


def main() -> None:
    """Start the app. Its parts read the language files as they are imported: when the files
    cannot be read, Windows' own message box says so, and the app ends."""
    try:
        from jiffin.app import root
    except CatalogError as error:
        win32.show_error(UNREADABLE.format(error=error))
        sys.exit(1)
    root.main()
