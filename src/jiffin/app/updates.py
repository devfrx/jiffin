"""The installed app's side of Velopack (ADR-0015): its hooks at start, and its updates.

An update comes from the folder the build wrote its releases to, whose path the build leaves
beside this module; a checkout has none. It is applied at start, before anything opens:
Velopack's updater waits for this process to end, replaces the app and starts it again.
"""

import logging
import sys
from pathlib import Path

import velopack

log = logging.getLogger(__name__)

SOURCE = Path(__file__).with_name("update-source.txt")
"""Written by scripts/package.py into the packaged app: the folder of its releases, on the
machine that built them."""


def hooks() -> None:
    """Velopack's start, the first thing the packaged app does: the hooks of install, update and
    uninstall end the process here, and an update downloaded earlier is applied."""
    if getattr(sys, "frozen", False):
        velopack.App().run()


def update() -> None:
    """Apply a newer release and start again, or return: with no source, nothing newer, or a
    problem, which is logged."""
    if not SOURCE.is_file():
        return
    try:
        manager = velopack.UpdateManager(SOURCE.read_text(encoding="utf-8").strip())
        found = manager.check_for_updates()
        if found is None:
            return
        log.info("updating to %s", found.TargetFullRelease.Version)
        manager.download_updates(found)
        manager.apply_updates_and_restart(found)  # Velopack ends the process
    except Exception:
        log.exception("no update")
