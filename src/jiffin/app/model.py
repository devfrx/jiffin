"""The model file's own thread: its check at every start, its download when it is missing, and
Riprova (#39, docs/design/first-run.md).

What it says of the file reaches the first-run window as a `ModelState`. A network problem is
tried again on its own, so a connection that comes back resumes the download without Riprova;
the other problems wait for Riprova, since only the user can mend them.
"""

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from jiffin.client import model_file
from jiffin.client.model_file import ModelFileError, Phase, PinnedFile, Problem, Progress
from jiffin.ui.first_run import FirstRun, ModelState

log = logging.getLogger(__name__)

RETRY_SECONDS = 30.0
"""How long a network problem waits before it is tried again; Riprova tries at once."""

_STAGES = {Phase.DOWNLOADING: FirstRun.Stage.DOWNLOADING, Phase.CHECKING: FirstRun.Stage.CHECKING}
_PROBLEMS = {
    Problem.NETWORK: FirstRun.Stage.NETWORK,
    Problem.SPACE: FirstRun.Stage.SPACE,
    Problem.DISK: FirstRun.Stage.DISK,
    Problem.MISMATCH: FirstRun.Stage.MISMATCH,
}


class ModelFetch:
    """`model_file.ensure` on a thread of its own, one call at a time. What it says of the file
    goes to `on_state`, on that thread; once the file is checked, `on_ready` is called too."""

    def __init__(
        self,
        file: PinnedFile,
        folder: Path,
        on_state: Callable[[ModelState], None],
        on_ready: Callable[[], None],
        *,
        retry_seconds: float = RETRY_SECONDS,
    ) -> None:
        self._file = file
        self._folder = folder
        self._on_state = on_state
        self._on_ready = on_ready
        self._retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._wanted = False
        """A call was asked for since the last one began."""
        self._running = False
        self._now = threading.Event()
        """Set by a call asked for: a network problem waiting to be tried again stops waiting."""

    def fetch(self) -> None:
        """At the start, and Riprova; from any thread."""
        with self._lock:
            self._wanted = True
            self._now.set()
            if self._running:
                return
            self._running = True
        # A daemon: a download cut short by quitting leaves its part, which the next start resumes.
        threading.Thread(target=self._run, name="model file", daemon=True).start()

    def _run(self) -> None:
        try:
            while self._take():
                if self._ensure():
                    self._now.wait(self._retry_seconds)
                    with self._lock:
                        self._wanted = True
        except BaseException:
            with self._lock:
                self._running = False
            raise

    def _take(self) -> bool:
        """Whether a call was asked for; if none was, the thread ends."""
        with self._lock:
            if not self._wanted:
                self._running = False
                return False
            self._wanted = False
            self._now.clear()
            return True

    def _ensure(self) -> bool:
        """One call; whether it met a network problem, to be tried again."""
        try:
            model_file.ensure(self._file, self._folder, self._progress)
        except ModelFileError as error:
            # Its message names files and numbers, never a folder.
            log.warning("the model file: %s", error)
            self._on_state(ModelState(_PROBLEMS[error.problem], missing=error.missing))
            return error.problem is Problem.NETWORK
        self._on_state(ModelState(FirstRun.Stage.READY))
        self._on_ready()
        return False

    def _progress(self, progress: Progress) -> None:
        self._on_state(ModelState(_STAGES[progress.phase], progress.done, progress.total))
