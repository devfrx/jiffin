"""How the interface looks: Windows' settings, followed live, and the chosen material (ADR-0010).

QML reads the look through the `Look` singleton; the colours of each theme are in Colors.qml.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import Property, QEvent, QObject, Signal
from PySide6.QtGui import QGuiApplication, QPalette, Qt
from PySide6.QtQml import QmlElement, QmlSingleton, QQmlEngine

from jiffin.ui import win32

QML_IMPORT_NAME = "Jiffin"
QML_IMPORT_MAJOR_VERSION = 1

VEIL = 0.9
"""The opacity of B's veil, set by eye next to Windows' menus (ADR-0010)."""


class Material(StrEnum):
    """The surface of the alert and of the tray list, chosen in the settings (ADR-0010)."""

    ACRYLIC = "a"
    MENU_ACRYLIC = "b"
    """Acrylic with the veil of Windows' menus: the default."""
    MICA = "c"
    MICA_ALT = "d"


_BACKDROPS = {
    Material.ACRYLIC: win32.DWMSBT_TRANSIENTWINDOW,
    Material.MENU_ACRYLIC: win32.DWMSBT_TRANSIENTWINDOW,
    Material.MICA: win32.DWMSBT_MAINWINDOW,
    Material.MICA_ALT: win32.DWMSBT_TABBEDWINDOW,
}
_PROVIDED = "jiffinLook"
"""The engine's dynamic property that holds its Look."""


@dataclass(frozen=True, slots=True)
class Settings:
    """What the look follows of Windows."""

    dark: bool
    accent: str
    """#RRGGBB: the shade Qt reads from Windows, which is the one WinUI fills with, Light2 of
    the accent palette in dark and Dark1 in light (checked on the owner's machine)."""
    transparency: bool
    animations: bool


def read_settings() -> Settings:
    app = QGuiApplication.instance()
    assert isinstance(app, QGuiApplication)
    return Settings(
        dark=app.styleHints().colorScheme() == Qt.ColorScheme.Dark,
        accent=app.palette().color(QPalette.ColorRole.Accent).name(),
        transparency=win32.transparency(),
        animations=win32.animations(),
    )


@QmlElement
@QmlSingleton
class Look(QObject):
    """The look, for QML and for the glass; `changed` says any of it changed."""

    changed = Signal()

    def __init__(self, read: Callable[[], Settings] = read_settings) -> None:
        super().__init__()
        self._read = read
        self._settings = read()
        self._material = Material.MENU_ACRYLIC

    def provide(self, engine: QQmlEngine) -> None:
        """Be the Look of this engine's QML. Python keeps it alive, and the engine never deletes
        it."""
        QQmlEngine.setObjectOwnership(self, QQmlEngine.ObjectOwnership.CppOwnership)
        engine.setProperty(_PROVIDED, self)

    @staticmethod
    def create(engine: QQmlEngine) -> "Look":
        """The instance QML sees: the one provided for the engine, not a new one."""
        look = engine.property(_PROVIDED)
        assert isinstance(look, Look), "provide() a Look before loading QML"
        return look

    def follow(self, app: QGuiApplication) -> None:
        """Follow the theme and the accent as Qt sees them change; the rest comes from Glass."""
        app.styleHints().colorSchemeChanged.connect(self.refresh)
        app.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self.refresh()
        return False

    def refresh(self) -> None:
        settings = self._read()
        if settings != self._settings:
            self._settings = settings
            self.changed.emit()

    @property
    def settings(self) -> Settings:
        """For Python: the Qt properties below are for QML."""
        return self._settings

    @property
    def material(self) -> Material:
        return self._material

    @material.setter
    def material(self, material: Material) -> None:
        if material != self._material:
            self._material = material
            self.changed.emit()

    @property
    def backdrop(self) -> int:
        """The DWM backdrop of the alerts and the list: the chosen material's."""
        return self.backdrop_for(self._material)

    def backdrop_for(self, material: Material) -> int:
        """The material's DWM backdrop, or none when the surface is solid."""
        return win32.DWMSBT_NONE if self._solid() else _BACKDROPS[material]

    def _solid(self) -> bool:
        return not self._settings.transparency

    @Property(bool, notify=changed)
    def dark(self) -> bool:
        return self._settings.dark

    @Property(str, notify=changed)
    def accent(self) -> str:
        return self._settings.accent

    @Property(bool, notify=changed)
    def solid(self) -> bool:
        """No glass: transparency is off, and QML paints the surface."""
        return self._solid()

    @Property(bool, notify=changed)
    def animations(self) -> bool:
        return self._settings.animations

    @Property(float, notify=changed)
    def veilOpacity(self) -> float:
        """B's veil over the glass; none for the other materials or on a solid surface."""
        return VEIL if self._material == Material.MENU_ACRYLIC and not self._solid() else 0.0
