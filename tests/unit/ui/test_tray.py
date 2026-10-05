import math
from dataclasses import replace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQml import QQmlEngine
from pytestqt.qtbot import QtBot

from jiffin.core.alerts import AlertsView
from jiffin.core.reminders import Pause, RemindersView
from jiffin.ui import win32
from jiffin.ui.look import Look, Settings
from jiffin.ui.tray import Corner, Icons, Tray, address, draw

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
        self.pauses: list[Pause] = []
        self.resumes = 0
        self.tray = Tray(
            self.engine, self.look, self._click, self._settings, self.pauses.append, self._resume
        )
        self.changes = 0
        self.tray.changed.connect(self._changed)

    def _click(self) -> None:
        self.clicks += 1

    def _settings(self) -> None:
        self.settings += 1

    def _resume(self) -> None:
        self.resumes += 1

    def _changed(self) -> None:
        self.changes += 1


def test_the_glyph_takes_the_taskbars_ink(qtbot: QtBot) -> None:
    assert colours(draw(SIZE, True, None, Corner.NONE), 0, 0, SIZE, SIZE) == {"#ffffff"}
    assert colours(draw(SIZE, False, None, Corner.NONE), 0, 0, SIZE, SIZE) == {"#1a1a1a"}


def test_the_dot_sits_at_the_top_right_in_the_accent(qtbot: QtBot) -> None:
    icon = draw(SIZE, True, "#d8d8d8", Corner.NONE)
    assert icon.pixelColor(16, 4).name() == "#d8d8d8"
    assert "#d8d8d8" not in colours(icon, 0, SIZE // 2, SIZE, SIZE)


@pytest.mark.parametrize(
    ("dark", "badge", "mark"), [(True, "#fce100", "#000000"), (False, "#9d5d00", "#ffffff")]
)
def test_the_warning_sits_at_the_bottom_right_in_the_caution_colours(
    qtbot: QtBot, dark: bool, badge: str, mark: str
) -> None:
    icon = draw(SIZE, dark, None, Corner.WARNING)
    corner = colours(icon, SIZE // 2, SIZE // 2, SIZE, SIZE)
    assert {badge, mark} <= corner
    assert badge not in colours(icon, 0, 0, SIZE // 2, SIZE // 2)


@pytest.mark.parametrize(
    ("dark", "disc", "bars"), [(True, "#ffffff", "#1a1a1a"), (False, "#1a1a1a", "#ffffff")]
)
def test_the_pause_sits_at_the_bottom_right_in_the_glyphs_ink(
    qtbot: QtBot, dark: bool, disc: str, bars: str
) -> None:
    icon = draw(SIZE, dark, None, Corner.PAUSED)
    # Across the badge's middle: two bars 2 px wide, 2 px apart, on whole pixels.
    across = [icon.pixelColor(x, 14).name() for x in range(11, 19)]
    assert across == [disc, bars, bars, disc, disc, bars, bars, disc]


@pytest.mark.parametrize(
    ("dot", "corner", "centre", "radius"),
    [
        ("#d8d8d8", Corner.NONE, (25.5, 6.5), 6.5),
        (None, Corner.WARNING, (24, 24), 8),
        (None, Corner.PAUSED, (24, 24), 8),
    ],
    ids=["dot", "warning", "pause"],
)
def test_a_badge_is_cut_out_of_the_glyph_with_a_clear_ring(
    qtbot: QtBot, dot: str | None, corner: Corner, centre: tuple[float, float], radius: float
) -> None:
    """At 32 px, 200%, where the ring is 2 px wide; each badge is the first drawn."""
    size = 32
    x0, y0 = centre
    ring = [
        (x, y)
        for x in range(size)
        for y in range(size)
        if radius + 0.75 < math.hypot(x + 0.5 - x0, y + 0.5 - y0) < radius + 1.25
    ]
    plain = draw(size, True, None, Corner.NONE)
    assert any(plain.pixelColor(x, y).alpha() > 0 for x, y in ring)
    badged = draw(size, True, dot, corner)
    assert all(badged.pixelColor(x, y).alpha() == 0 for x, y in ring)


def test_the_provider_draws_the_icon_its_address_names(qtbot: QtBot) -> None:
    name = address(SIZE, True, "#d8d8d8", Corner.WARNING)
    assert name == "image://tray/20/dark/d8d8d8/warning"
    size = QSize()
    image = Icons().requestImage(name.removeprefix("image://tray/"), size, QSize())
    assert image == draw(SIZE, True, "#d8d8d8", Corner.WARNING)
    assert size == QSize(SIZE, SIZE)


def test_the_icon_follows_the_alerts_the_browsers_and_the_taskbar(qtbot: QtBot) -> None:
    scene = Scene()
    small = win32.small_icon_size()
    assert scene.tray.property("icon") == address(small, True, None, Corner.NONE)
    scene.tray.show_alerts(AlertsView((), 1, ()))
    assert scene.tray.property("icon") == address(small, True, "#d8d8d8", Corner.NONE)
    scene.tray.show_unreadable(frozenset({"chrome.exe"}))
    assert scene.tray.property("icon") == address(small, True, "#d8d8d8", Corner.WARNING)
    scene.windows.settings = replace(DARK_TASKBAR, taskbar_dark=False, taskbar_accent="#b2b2b2")
    scene.look.refresh()
    assert scene.tray.property("icon") == address(small, False, "#b2b2b2", Corner.WARNING)
    scene.tray.show_alerts(AlertsView((), 0, ()))
    scene.tray.show_unreadable(frozenset())
    assert scene.tray.property("icon") == address(small, False, None, Corner.NONE)
    assert scene.changes == 5


def test_the_pause_takes_the_corner_of_the_warning_until_it_ends(qtbot: QtBot) -> None:
    scene = Scene()
    small = win32.small_icon_size()
    scene.tray.show_unreadable(frozenset({"chrome.exe"}))
    assert not scene.tray.property("paused")
    scene.tray.show_reminders(RemindersView((), 1_790_003_600_000))
    assert scene.tray.property("paused")
    assert scene.tray.property("icon") == address(small, True, None, Corner.PAUSED)
    scene.tray.show_reminders(RemindersView((), 1_790_086_400_000))
    scene.tray.show_reminders(RemindersView(()))
    assert not scene.tray.property("paused")
    assert scene.tray.property("icon") == address(small, True, None, Corner.WARNING)
    assert scene.changes == 3


def test_the_menu_pauses_for_an_hour_or_until_tomorrow_and_riprendi_resumes(
    qtbot: QtBot,
) -> None:
    scene = Scene()
    scene.tray.pauseHour()
    scene.tray.pauseTomorrow()
    scene.tray.resume()
    assert (scene.pauses, scene.resumes) == ([Pause.HOUR, Pause.TOMORROW], 1)


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
