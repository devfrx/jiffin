from dataclasses import replace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlEngine
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.ui import win32
from jiffin.ui.look import Look, Settings
from jiffin.ui.tray import Icons, Tray, address, draw

DARK_TASKBAR = Settings(
    dark=True,
    accent="#4cc2ff",
    transparency=True,
    animations=True,
    taskbar_dark=True,
    taskbar_accent="#d8d8d8",
)
SIZE = 20
"""The small icon at 125%."""


def colours(image: QImage, left: int, top: int, right: int, bottom: int) -> set[str]:
    """The opaque colours in a part of the image, as #rrggbb."""
    return {
        image.pixelColor(x, y).name()
        for x in range(left, right)
        for y in range(top, bottom)
        if image.pixelColor(x, y).alpha() == 255
    }


class Windows:
    """Windows' settings, as the look reads them; the test changes them."""

    def __init__(self) -> None:
        self.settings = DARK_TASKBAR

    def read(self) -> Settings:
        return self.settings


class Scene:
    """A tray icon's state, without the icon itself: the offscreen platform has no tray."""

    def __init__(self) -> None:
        self.windows = Windows()
        self.look = Look(self.windows.read)
        self.engine = QQmlEngine()
        self.look.provide(self.engine)
        self.clicks = 0
        self.settings = 0
        self.tray = Tray(self.engine, self.look, self._click, self._settings)
        self.changes = 0
        self.tray.changed.connect(self._changed)

    def _click(self) -> None:
        self.clicks += 1

    def _settings(self) -> None:
        self.settings += 1

    def _changed(self) -> None:
        self.changes += 1


def test_the_glyph_takes_the_taskbars_ink(qtbot: QtBot) -> None:
    assert colours(draw(SIZE, True, None, False), 0, 0, SIZE, SIZE) == {"#ffffff"}
    assert colours(draw(SIZE, False, None, False), 0, 0, SIZE, SIZE) == {"#1a1a1a"}


def test_the_dot_sits_at_the_top_right_in_the_accent(qtbot: QtBot) -> None:
    icon = draw(SIZE, True, "#d8d8d8", False)
    assert icon.pixelColor(16, 4).name() == "#d8d8d8"
    assert "#d8d8d8" not in colours(icon, 0, SIZE // 2, SIZE, SIZE)


@pytest.mark.parametrize(
    ("dark", "badge", "mark"), [(True, "#fce100", "#000000"), (False, "#9d5d00", "#ffffff")]
)
def test_the_warning_sits_at_the_bottom_right_in_the_caution_colours(
    qtbot: QtBot, dark: bool, badge: str, mark: str
) -> None:
    icon = draw(SIZE, dark, None, True)
    corner = colours(icon, SIZE // 2, SIZE // 2, SIZE, SIZE)
    assert {badge, mark} <= corner
    assert badge not in colours(icon, 0, 0, SIZE // 2, SIZE // 2)


def test_the_provider_draws_the_icon_its_address_names(qtbot: QtBot) -> None:
    name = address(SIZE, True, "#d8d8d8", True)
    assert name == "image://tray/20/dark/d8d8d8/warning"
    size = QSize()
    image = Icons().requestImage(name.removeprefix("image://tray/"), size, QSize())
    assert image == draw(SIZE, True, "#d8d8d8", True)
    assert size == QSize(SIZE, SIZE)


def test_the_icon_follows_the_alerts_the_browsers_and_the_taskbar(qtbot: QtBot) -> None:
    scene = Scene()
    small = win32.small_icon_size()
    assert scene.tray.property("icon") == address(small, True, None, False)
    scene.tray.show_alerts(AlertsView((), 1, ()))
    assert scene.tray.property("icon") == address(small, True, "#d8d8d8", False)
    scene.tray.show_unreadable(frozenset({"chrome.exe"}))
    assert scene.tray.property("icon") == address(small, True, "#d8d8d8", True)
    scene.windows.settings = replace(DARK_TASKBAR, taskbar_dark=False, taskbar_accent="#b2b2b2")
    scene.look.refresh()
    assert scene.tray.property("icon") == address(small, False, "#b2b2b2", True)
    scene.tray.show_alerts(AlertsView((), 0, ()))
    scene.tray.show_unreadable(frozenset())
    assert scene.tray.property("icon") == address(small, False, None, False)
    assert scene.changes == 5


def test_a_click_opens_the_list_impostazioni_the_settings_and_esci_quits(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = Scene()
    scene.tray.click()
    assert (scene.clicks, scene.settings) == (1, 0)
    scene.tray.settings()
    assert (scene.clicks, scene.settings) == (1, 1)
    quits: list[str] = []
    monkeypatch.setattr(QGuiApplication, "quit", lambda: quits.append("quit"))
    scene.tray.quit()
    assert quits == ["quit"]
