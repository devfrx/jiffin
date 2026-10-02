"""Where the harness finds and writes things (ADR-0017).

The harness runs from a checkout, never from the packaged app: the private working files sit in
`NO_GIT` beside the repository, and anything with titles, addresses or reminder texts goes to
the data folder there.
"""

from pathlib import Path

from jiffin.harness.errors import HarnessError

REPOSITORY = Path(__file__).resolve().parents[3]
NO_GIT = REPOSITORY.parent / "NO_GIT"
DATA = NO_GIT / "jiffin-prove"
"""The default data folder; `--data` changes it."""
SAMPLE = NO_GIT / "sibyl-campione" / "etichette.json"
"""The labelled sample of the prototype: 106 contexts, 9 reminders (ADR-0007)."""


def data_folder(path: Path) -> Path:
    """The data folder, created inside a parent that must exist already."""
    try:
        path.mkdir(exist_ok=True)
    except FileNotFoundError:
        raise HarnessError(f"{path.parent} does not exist: pass --data") from None
    return path
