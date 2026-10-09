"""The networks' labels, as the interface keeps them (ADR-0028): which network is home and which
the office, by the id Windows gives each one, never its name. The context capture says which
networks are connected now; a label goes on the network in use, on all those connected at once,
since the user knows where they are, not which network is which. Each change goes to be kept,
and to the capture, which counts it at once (#153).
"""

from collections.abc import Callable, Iterable, Mapping

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtQml import QmlElement, QmlUncreatable, QQmlEngine

from jiffin.core.situations import HOME, OFFICE, Situation, Term

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1


@QmlElement
@QmlUncreatable("The interface makes it.")
class Networks(QObject):  # type: ignore[operator]  # QmlUncreatable's stub has no __call__
    """Lives on the interface thread. `keep` takes every label at each change, for the app to
    store and give the capture; the app sets the kept ones with `restore` at the start."""

    changed = Signal()

    def __init__(self, engine: QQmlEngine, keep: Callable[[Mapping[str, str]], None]) -> None:
        # The engine owns this object, as the windows' own: no binding reads it gone.
        super().__init__(engine)
        self._keep = keep
        self._labels: dict[str, str] = {}
        self._connected: frozenset[str] = frozenset()

    def restore(self, labels: Mapping[str, str]) -> None:
        """The labels kept, at the start."""
        self._labels = dict(labels)
        self.changed.emit()

    def show(self, connected: frozenset[str]) -> None:
        """The ids of the networks connected now, as the capture reads them."""
        if connected != self._connected:
            self._connected = connected
            self.changed.emit()

    def unknown(self, situations: Iterable[Term]) -> str:
        """The first place the situations name, home or the office, that no network is labelled
        for yet: a reminder there could never ring (ADR-0028); "" for none."""
        known = set(self._labels.values())
        for term in situations:
            place = term.value
            if (
                term.situation is Situation.NETWORK
                and place in (HOME, OFFICE)
                and place not in known
            ):
                return str(place)
        return ""

    @Property(bool, notify=changed)
    def connected(self) -> bool:
        """A network is in use."""
        return bool(self._connected)

    @Property(str, notify=changed)
    def label(self) -> str:
        """What the network in use is, as the capture tells `core`: "home", "office", "" for
        neither, and both, "home office", for networks of both connected at once."""
        return " ".join(sorted({self._labels[n] for n in self._connected if n in self._labels}))

    @Slot(str)
    def labelInUse(self, label: str) -> None:
        """The network in use is home or the office, or "" neither: every network connected
        takes it."""
        if not self._connected:
            return
        for network in self._connected:
            if label:
                self._labels[network] = label
            else:
                self._labels.pop(network, None)
        self._keep(dict(self._labels))
        self.changed.emit()
