"""Where the app keeps its data (ADR-0013): one folder, outside Velopack's install folder, so
that updates and uninstalls never touch it (ADR-0015)."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Folders:
    """The data folder: the database, with the logs and the models beside it."""

    root: Path

    @classmethod
    def app(cls) -> "Folders":
        """The app's own: Jiffin, in the user's local application data."""
        return cls(Path(os.environ["LOCALAPPDATA"]) / "Jiffin")

    @property
    def database(self) -> Path:
        return self.root / "jiffin.db"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def models(self) -> Path:
        return self.root / "models"
