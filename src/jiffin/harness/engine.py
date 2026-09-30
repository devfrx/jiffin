"""The app's own engine, started through `client` as the app starts it (ADR-0011, ADR-0017)."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jiffin.client import model_file
from jiffin.client.supervisor import State, Status, Supervisor
from jiffin.core.clock import SystemClock
from jiffin.harness import gpu
from jiffin.harness.errors import HarnessError

log = logging.getLogger(__name__)


@contextmanager
def running(models: Path) -> Iterator[Supervisor]:
    """An engine ready to judge, shut down on the way out; any failure stops the harness."""
    gpu.require_free()
    if not (models / model_file.MODEL.name).is_file():
        raise HarnessError(f"the model is not in {models}: pass --models")
    try:
        # The file is there, so this only checks its size and sha256: a few seconds.
        model = model_file.ensure(model_file.MODEL, models, lambda progress: None)
    except model_file.ModelFileError as error:
        raise HarnessError(f"the model: {error}") from None
    supervisor = Supervisor(model, model_file.MODEL.sha256, SystemClock(), _status, lambda: None)
    supervisor.start()
    try:
        status = supervisor.status
        if status.state is not State.READY:
            raise HarnessError(f"the engine did not start: {status.stop_reason or status.state}")
        yield supervisor
    finally:
        supervisor.close()


def _status(status: Status) -> None:
    log.info("engine: %s", status.state.name.lower())
