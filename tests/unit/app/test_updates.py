"""Velopack's side of the installed app (#45), with Velopack played by the test."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import velopack

from jiffin.app import updates

RELEASES = r"C:\EVERYTHING\DEV\MY_REPOS\jiffin\releases"


@dataclass(frozen=True, slots=True)
class Asset:
    Version: str


@dataclass(frozen=True, slots=True)
class Found:
    """What `check_for_updates` gives for a newer release."""

    TargetFullRelease: Asset


class Manager:
    """`velopack.UpdateManager`, with the release the test put in the folder, or a failure."""

    def __init__(self, found: Found | None = None, failure: Exception | None = None) -> None:
        self._found = found
        self._failure = failure
        self.sources: list[str] = []
        self.asked: list[tuple[str, Found | None]] = []

    def __call__(self, source: str) -> "Manager":
        self.sources.append(source)
        return self

    def check_for_updates(self) -> Found | None:
        self.asked.append(("check", None))
        if self._failure is not None:
            raise self._failure
        return self._found

    def download_updates(self, found: Found) -> None:
        self.asked.append(("download", found))

    def apply_updates_and_restart(self, found: Found) -> None:
        self.asked.append(("apply", found))


@pytest.fixture
def source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file the build leaves in the packaged app, with the releases' folder."""
    path = tmp_path / "update-source.txt"
    path.write_text(RELEASES + "\n", encoding="utf-8")
    monkeypatch.setattr(updates, "SOURCE", path)
    return path


def use(manager: Manager, monkeypatch: pytest.MonkeyPatch) -> Manager:
    monkeypatch.setattr(velopack, "UpdateManager", manager)
    return manager


def test_a_checkout_looks_for_no_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(updates, "SOURCE", tmp_path / "update-source.txt")
    manager = use(Manager(), monkeypatch)
    updates.update()
    assert manager.sources == []


@pytest.mark.usefixtures("source")
def test_with_nothing_newer_the_app_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = use(Manager(), monkeypatch)
    updates.update()
    assert manager.sources == [RELEASES]
    assert manager.asked == [("check", None)]


@pytest.mark.usefixtures("source")
def test_a_newer_release_is_downloaded_then_applied(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=updates.__name__)
    found = Found(Asset("0.1.1"))
    manager = use(Manager(found), monkeypatch)
    updates.update()
    assert manager.asked == [("check", None), ("download", found), ("apply", found)]
    assert "updating to 0.1.1" in caplog.text


@pytest.mark.usefixtures("source")
def test_a_failed_update_lets_the_app_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    use(Manager(failure=RuntimeError("the folder is gone")), monkeypatch)
    updates.update()
    assert "no update" in caplog.text
    assert "the folder is gone" in caplog.text


class App:
    """`velopack.App`, counting its runs."""

    runs = 0

    def run(self) -> None:
        App.runs += 1


def test_velopack_starts_only_the_packaged_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(velopack, "App", App)
    monkeypatch.setattr(App, "runs", 0)
    updates.hooks()
    assert App.runs == 0
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    updates.hooks()
    assert App.runs == 1
