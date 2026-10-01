import ctypes
from ctypes import wintypes
from dataclasses import replace

import pytest
from pytestqt.qtbot import QtBot

from jiffin.ui import glass as glass_module
from jiffin.ui import win32
from jiffin.ui.glass import Glass
from jiffin.ui.look import Look, Material, Settings

DARK = Settings(dark=True, accent="#4cc2ff", transparency=True, animations=True)
OURS, OTHER = 0x1234, 0x5678
"""A window of ours, with the glass, and one that is not."""
FRAMED = 0x9ABC
"""The creation window: Windows' own frame, with Mica."""
ANSWER = 1
"""What DefWindowProcW answers to the WM_NCACTIVATE the filter passes on."""
SPI_SETANIMATION = 0x0049
"""Sent with "WindowMetrics" when the animation effects change, before SPI_SETCLIENTAREAANIMATION."""
SETTLED_MS = 200
"""Longer than the settling of these tests."""


class Windows:
    """Windows' settings, as the look reads them, and how many times it read them."""

    def __init__(self) -> None:
        self.settings = DARK
        self.reads = 0

    def read(self) -> Settings:
        self.reads += 1
        return self.settings


@pytest.fixture
def windows() -> Windows:
    return Windows()


@pytest.fixture
def look(windows: Windows) -> Look:
    return Look(windows.read)


@pytest.fixture
def glass(
    qtbot: QtBot,
    monkeypatch: pytest.MonkeyPatch,
    look: Look,
    dwm: list[tuple[object, ...]],
) -> Glass:
    monkeypatch.setattr(glass_module, "SETTLE_MS", 50)

    def active_frame_answer(hwnd: int, lparam: int) -> int:
        dwm.append(("active_frame_answer", hwnd, lparam))
        return ANSWER

    monkeypatch.setattr(win32, "active_frame_answer", active_frame_answer)
    glass = Glass(look)
    glass.add(OURS)
    dwm.clear()
    return glass


def send(
    glass: Glass, code: int, hwnd: int = OURS, wparam: int = 0, setting: str | None = None
) -> tuple[bool, int]:
    """Pass a message through the filter, as Qt does with each message of the interface thread;
    `setting` is the name a WM_SETTINGCHANGE carries."""
    name = None if setting is None else ctypes.create_unicode_buffer(setting)
    lparam = 0 if name is None else ctypes.addressof(name)
    msg = wintypes.MSG(hWnd=hwnd, message=code, wParam=wparam, lParam=lparam)
    return glass.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))


def test_a_window_gets_the_glass_of_the_chosen_material(
    look: Look, dwm: list[tuple[object, ...]]
) -> None:
    look.material = Material.MICA
    Glass(look).add(OURS)
    assert dwm == [("set_backdrop", OURS, True, win32.DWMSBT_MAINWINDOW)]


def test_a_window_is_nudged_once_after_its_first_show(
    glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    glass.shown(OURS)
    glass.shown(OURS)
    assert dwm == [("activate_frame", OURS), ("nudge", OURS), ("activate_frame", OURS)]


def test_the_frame_of_our_windows_is_never_shown_and_always_active(
    glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    assert send(glass, win32.WM_NCCALCSIZE, wparam=1) == (True, 0)
    assert send(glass, win32.WM_NCCALCSIZE, wparam=0) == (False, 0)
    assert send(glass, win32.WM_NCACTIVATE, wparam=0) == (True, ANSWER)
    assert dwm == [("active_frame_answer", OURS, 0)]
    assert send(glass, win32.WM_NCCALCSIZE, hwnd=OTHER, wparam=1) == (False, 0)
    assert send(glass, win32.WM_NCACTIVATE, hwnd=OTHER) == (False, 0)
    assert len(dwm) == 1


@pytest.mark.parametrize(
    ("code", "setting"),
    [
        (win32.WM_SETTINGCHANGE, "ImmersiveColorSet"),
        (win32.WM_THEMECHANGED, None),
        (win32.WM_DWMCOLORIZATIONCOLORCHANGED, None),
    ],
)
def test_a_change_of_colours_recreates_the_glass_once_it_has_settled(
    qtbot: QtBot,
    windows: Windows,
    glass: Glass,
    dwm: list[tuple[object, ...]],
    code: int,
    setting: str | None,
) -> None:
    windows.settings = replace(DARK, dark=False)
    for _ in range(3):  # every window gets the message
        assert send(glass, code, setting=setting) == (False, 0)
    assert dwm == []
    qtbot.waitUntil(lambda: len(dwm) == 3)
    qtbot.wait(SETTLED_MS)
    assert dwm == [
        ("set_backdrop", OURS, False, win32.DWMSBT_TRANSIENTWINDOW),
        ("activate_frame", OURS),
        ("recreate_backdrop", OURS, win32.DWMSBT_TRANSIENTWINDOW),
    ]


def test_a_change_of_animations_is_read_and_leaves_the_glass_alone(
    qtbot: QtBot, windows: Windows, look: Look, glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    windows.settings = replace(DARK, animations=False)
    send(glass, win32.WM_SETTINGCHANGE, wparam=SPI_SETANIMATION, setting="WindowMetrics")
    send(glass, win32.WM_SETTINGCHANGE, wparam=win32.SPI_SETCLIENTAREAANIMATION, setting="")
    qtbot.waitUntil(lambda: look.property("animations") is False)
    qtbot.wait(SETTLED_MS)
    assert all(call[0] != "recreate_backdrop" for call in dwm)


@pytest.mark.parametrize(
    ("wparam", "setting"),
    [(0, "Environment"), (0, "intl"), (0, None), (SPI_SETANIMATION, "WindowMetrics")],
)
def test_other_setting_changes_are_ignored(
    qtbot: QtBot,
    windows: Windows,
    glass: Glass,
    dwm: list[tuple[object, ...]],
    wparam: int,
    setting: str | None,
) -> None:
    reads = windows.reads
    assert send(glass, win32.WM_SETTINGCHANGE, wparam=wparam, setting=setting) == (False, 0)
    qtbot.wait(SETTLED_MS)
    assert (windows.reads, dwm) == (reads, [])


def test_a_solid_surface_gets_no_glass_back(
    qtbot: QtBot, windows: Windows, look: Look, glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    windows.settings = replace(DARK, transparency=False)
    send(glass, win32.WM_SETTINGCHANGE, setting="ImmersiveColorSet")
    qtbot.waitUntil(lambda: look.property("solid") is True)
    qtbot.wait(SETTLED_MS)
    assert dwm == [("set_backdrop", OURS, True, win32.DWMSBT_NONE), ("activate_frame", OURS)]


def test_a_new_look_reaches_every_window(
    look: Look, glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    glass.add(OTHER)
    dwm.clear()
    look.material = Material.MICA_ALT
    assert sorted(dwm, key=str) == sorted(
        [
            ("set_backdrop", OURS, True, win32.DWMSBT_TABBEDWINDOW),
            ("activate_frame", OURS),
            ("set_backdrop", OTHER, True, win32.DWMSBT_TABBEDWINDOW),
            ("activate_frame", OTHER),
        ],
        key=str,
    )


def test_a_framed_window_gets_mica_whatever_the_material(
    look: Look, dwm: list[tuple[object, ...]]
) -> None:
    look.material = Material.ACRYLIC
    Glass(look).add_framed(FRAMED)
    assert dwm == [("set_backdrop", FRAMED, True, win32.DWMSBT_MAINWINDOW)]


def test_the_frame_of_a_framed_window_is_left_to_windows(
    glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    glass.add_framed(FRAMED)
    dwm.clear()
    assert send(glass, win32.WM_NCCALCSIZE, hwnd=FRAMED, wparam=1) == (False, 0)
    assert send(glass, win32.WM_NCACTIVATE, hwnd=FRAMED) == (False, 0)
    assert dwm == []


def test_a_framed_window_follows_the_look_and_keeps_mica(
    qtbot: QtBot, windows: Windows, look: Look, glass: Glass, dwm: list[tuple[object, ...]]
) -> None:
    glass.add_framed(FRAMED)
    dwm.clear()
    look.material = Material.MICA_ALT
    assert ("set_backdrop", FRAMED, True, win32.DWMSBT_MAINWINDOW) in dwm
    dwm.clear()
    windows.settings = replace(DARK, dark=False, transparency=False)
    send(glass, win32.WM_SETTINGCHANGE, setting="ImmersiveColorSet")
    qtbot.waitUntil(lambda: look.property("solid") is True)
    qtbot.wait(SETTLED_MS)
    framed = [call for call in dwm if call[1] == FRAMED]
    assert framed == [("set_backdrop", FRAMED, False, win32.DWMSBT_NONE)]
