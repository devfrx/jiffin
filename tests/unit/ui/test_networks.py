"""The networks' labels as the interface keeps them (ADR-0028, #153)."""

from collections.abc import Iterator, Mapping

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine

from jiffin.core.situations import HOME, OFFICE, OFFLINE, Ends, Holds, Situation
from jiffin.ui.networks import Networks

HOME_ID = "6f1d2c3b-0000-4000-8000-000000000001"
OFFICE_ID = "6f1d2c3b-0000-4000-8000-000000000002"
VPN_ID = "6f1d2c3b-0000-4000-8000-000000000003"


class Kept:
    def __init__(self) -> None:
        self.labels: list[dict[str, str]] = []

    def __call__(self, labels: Mapping[str, str]) -> None:
        self.labels.append(dict(labels))


@pytest.fixture
def engine(qapp: QGuiApplication) -> Iterator[QQmlEngine]:
    """Owns the networks, as the interface's does: they go with it."""
    engine = QQmlEngine()
    yield engine
    engine.deleteLater()


def make(engine: QQmlEngine) -> tuple[Networks, Kept]:
    kept = Kept()
    networks = Networks(engine, kept)
    networks.restore({OFFICE_ID: "office"})
    return networks, kept


def test_the_network_in_use_says_its_label(engine: QQmlEngine) -> None:
    networks, _ = make(engine)
    assert (networks.property("connected"), networks.property("label")) == (False, "")
    networks.show(frozenset({OFFICE_ID}))
    assert (networks.property("connected"), networks.property("label")) == (True, "office")
    networks.show(frozenset({HOME_ID}))
    assert networks.property("label") == ""
    # A network without a label beside one with it: the capture gives only the label.
    networks.show(frozenset({OFFICE_ID, VPN_ID}))
    assert networks.property("label") == "office"


def test_a_label_goes_on_every_network_connected_and_is_kept(engine: QQmlEngine) -> None:
    networks, kept = make(engine)
    networks.show(frozenset({HOME_ID, VPN_ID}))
    networks.labelInUse("home")
    assert kept.labels == [{OFFICE_ID: "office", HOME_ID: "home", VPN_ID: "home"}]
    assert networks.property("label") == "home"
    networks.labelInUse("")
    assert kept.labels[-1] == {OFFICE_ID: "office"}
    assert networks.property("label") == ""


def test_without_a_network_no_label_is_put(engine: QQmlEngine) -> None:
    networks, kept = make(engine)
    networks.labelInUse("home")
    assert kept.labels == []


def test_a_place_no_network_is_labelled_for_is_unknown(engine: QQmlEngine) -> None:
    networks, _ = make(engine)
    at_home = (Holds(Situation.CALL), Ends(Situation.NETWORK, HOME))
    assert networks.unknown(at_home) == "home"
    assert networks.unknown((Holds(Situation.NETWORK, OFFICE),)) == ""
    assert networks.unknown((Holds(Situation.NETWORK, OFFLINE),)) == ""  # no label needed
    networks.show(frozenset({HOME_ID}))
    networks.labelInUse("home")
    assert networks.unknown(at_home) == ""
