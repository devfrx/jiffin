from dataclasses import replace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication, Qt
from PySide6.QtQml import QQmlEngine

from jiffin.ui import win32
from jiffin.ui.look import VEIL, Look, Material, Settings

DARK = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#4cc2ff",
)


class Windows:
    """Windows' settings, as the look reads them; the test changes them."""

    def __init__(self) -> None:
        self.settings = DARK

    def read(self) -> Settings:
        return self.settings


class Scene:
    """A look on Windows' settings, and how many times it said it changed."""

    def __init__(self) -> None:
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.changes = 0
        self.look.changed.connect(self._changed)

    def qml(self, *names: str) -> tuple[object, ...]:
        """Properties of the look, as QML reads them."""
        return tuple(self.look.property(name) for name in names)

    def _changed(self) -> None:
        self.changes += 1


@pytest.fixture
def scene() -> Scene:
    return Scene()


def test_the_look_says_it_changed_only_when_a_setting_did(scene: Scene) -> None:
    scene.look.refresh()
    assert scene.changes == 0
    scene.windows.settings = replace(DARK, dark=False, accent="#005fb8")
    scene.look.refresh()
    assert scene.changes == 1
    assert scene.qml("dark", "accent") == (False, "#005fb8")
    assert scene.look.settings == scene.windows.settings


@pytest.mark.parametrize(
    ("material", "backdrop", "veil"),
    [
        (Material.ACRYLIC, win32.DWMSBT_TRANSIENTWINDOW, 0.0),
        (Material.MENU_ACRYLIC, win32.DWMSBT_TRANSIENTWINDOW, VEIL),
        (Material.MICA, win32.DWMSBT_MAINWINDOW, 0.0),
        (Material.MICA_ALT, win32.DWMSBT_TABBEDWINDOW, 0.0),
    ],
)
def test_each_material_has_its_backdrop_and_only_b_a_veil(
    scene: Scene, material: Material, backdrop: int, veil: float
) -> None:
    scene.look.material = material
    assert scene.look.backdrop == backdrop
    assert scene.qml("veilOpacity", "solid") == (veil, False)


def test_b_is_the_material_until_another_is_chosen(scene: Scene) -> None:
    assert scene.look.material == Material.MENU_ACRYLIC
    scene.look.material = Material.MENU_ACRYLIC
    assert scene.changes == 0
    scene.look.material = Material.MICA
    assert scene.changes == 1


@pytest.mark.parametrize("material", list(Material))
def test_without_transparency_the_surface_is_solid_with_no_glass(
    scene: Scene, material: Material
) -> None:
    scene.look.material = material
    scene.windows.settings = replace(DARK, transparency=False)
    scene.look.refresh()
    assert scene.look.backdrop == win32.DWMSBT_NONE
    assert scene.qml("solid", "veilOpacity") == (True, 0.0)


def test_the_look_follows_the_theme_and_the_accent_that_qt_reports(
    qapp: QGuiApplication, scene: Scene
) -> None:
    scene.look.follow(qapp)
    scene.windows.settings = replace(DARK, accent="#005fb8")
    QCoreApplication.sendEvent(qapp, QEvent(QEvent.Type.ApplicationPaletteChange))
    assert scene.qml("accent") == ("#005fb8",)
    scene.windows.settings = replace(DARK, dark=False)
    qapp.styleHints().colorSchemeChanged.emit(Qt.ColorScheme.Light)
    assert scene.qml("dark") == (False,)
    assert scene.changes == 2


def test_qml_gets_the_look_provided_for_its_engine(scene: Scene) -> None:
    engine = QQmlEngine()
    with pytest.raises(AssertionError, match="provide"):
        Look.create(engine)
    scene.look.provide(engine)
    assert Look.create(engine) is scene.look
