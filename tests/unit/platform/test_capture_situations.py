"""The situations as the context thread reads them (ADR-0028): Windows' sources are played by the
test, on simulated time."""

import logging
from collections.abc import Callable

import comtypes
import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.situations import (
    AWAY_MS,
    BATTERY,
    HOME,
    NO,
    OFFICE,
    OFFLINE,
    PLUGGED,
    YES,
    Situation,
    SituationObservation,
)
from jiffin.platform import win32
from jiffin.platform.capture import RETRY_MS, TICK_MS, Situations

START = 1_790_000_000_000  # 2026-09-21, in UTC milliseconds
DISCORD, CHROME, VIVALDI, UNKNOWN = 11, 22, 33, 99
PROGRAMS = {DISCORD: "Discord.exe", CHROME: "chrome.exe", VIVALDI: "vivaldi.exe"}
CHROME_WINDOW, VIVALDI_WINDOW, NOTEPAD_WINDOW = 7, 8, 9
MEET = Context("chrome.exe", "Riunione", "meet.google.com/abc-defg-hij")
MAIL = Context("chrome.exe", "Posta in arrivo", "mail.example.it/inbox")
NOTES = Context("notepad.exe", "appunti.txt - Blocco note", None)
HOME_ID = "6f1d2c3b-0000-4000-8000-000000000001"
OFFICE_ID = "6f1d2c3b-0000-4000-8000-000000000002"
CAFE_ID = "6f1d2c3b-0000-4000-8000-000000000003"
COM_FAILURE = comtypes.COMError(0x80004005 - 2**32, None, None)  # E_FAIL
DENIED = OSError(0, "denied", None, 5)  # ERROR_ACCESS_DENIED


class FakeAudio:
    """Core Audio, as the scene plays it."""

    def __init__(self, scene: "Scene", on_change: Callable[[], None]) -> None:
        scene.check("audio start")
        self._scene = scene
        self.on_change = on_change
        scene.started.append("audio")

    def capturing(self) -> frozenset[int]:
        self._scene.check("audio")
        self._scene.audio_reads += 1
        return frozenset(self._scene.capturing)

    def headphones(self) -> bool:
        return self._scene.headphones

    def close(self) -> None:
        self._scene.closed.append("audio")


class FakeMedia:
    """Windows' media controls, as the scene plays them."""

    def __init__(self, scene: "Scene") -> None:
        scene.check("media start")
        self._scene = scene
        scene.started.append("media")

    def playing(self) -> frozenset[str]:
        self._scene.check("media")
        return frozenset(self._scene.playing)

    def close(self) -> None:
        self._scene.closed.append("media")


class FakeNetworks:
    """The Network List Manager, as the scene plays it."""

    def __init__(self, scene: "Scene", on_change: Callable[[], None]) -> None:
        scene.check("networks start")
        self._scene = scene
        self.on_change = on_change
        scene.started.append("networks")

    def connected(self) -> frozenset[str]:
        self._scene.check("networks")
        return frozenset(self._scene.connected)

    def close(self) -> None:
        self._scene.closed.append("networks")


class Scene:
    """The situations over a machine the test plays: plugged in, on the home network, nothing
    capturing or playing, the last input at the start."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.clock = SimulatedClock(START)
        self.last_input = START
        self.capturing: set[int] = set()
        self.headphones = False
        self.playing: set[str] = set()
        self.connected = {HOME_ID}
        self.plugged = True
        self.display = False
        self.recording: dict[int, bool | None] = {}
        """Whether the tab in front of a window records, as UI Automation tells it."""
        self.failing: dict[str, Exception] = {}
        """What fails, and how: "audio start", "audio", "media", "idle", "power"…"""
        self.started: list[str] = []
        self.closed: list[str] = []
        self.audio_reads = 0
        self.reads: list[int] = []
        """The windows whose tab was read."""
        self.posted: list[int] = []
        """The messages posted to the thread, not taken yet."""
        self.observations: list[SituationObservation] = []
        monkeypatch.setattr(
            win32, "idle_ms", lambda: self._machine("idle", self.clock.now() - self.last_input)
        )
        monkeypatch.setattr(win32, "plugged_in", lambda: self._machine("power", self.plugged))
        monkeypatch.setattr(
            win32, "external_display", lambda: self._machine("displays", self.display)
        )
        monkeypatch.setattr(win32, "program_of", PROGRAMS.get)
        monkeypatch.setattr(win32, "post", lambda thread, message: self.posted.append(message))
        self.made: list[FakeAudio | FakeNetworks] = []
        self.situations = Situations(
            self.clock,
            self.observations.append,
            self,
            audio=self._audio,
            media=lambda: FakeMedia(self),
            networks=self._networks,
            labels={HOME_ID: HOME, OFFICE_ID: OFFICE},
        )

    def check(self, what: str) -> None:
        if what in self.failing:
            raise self.failing[what]

    def records(self, hwnd: int, app: str) -> bool | None:
        self.reads.append(hwnd)
        return self.recording.get(hwnd)

    def start(self) -> None:
        self.situations.start()

    def tick(self, times: int = 1) -> None:
        for _ in range(times):
            self.clock.advance(TICK_MS)
            self.situations.tick()

    def touch(self) -> None:
        """A key or the mouse, now."""
        self.last_input = self.clock.now()

    def front(self, window: int | None, context: Context | None) -> None:
        self.situations.front(window, context)

    def notice(self, notice: win32.Notice) -> None:
        self.situations.on_notice(notice)

    def audio_changes(self) -> None:
        """Core Audio tells of a change, and the thread takes its message."""
        self.audio.on_change()
        self.deliver()

    def networks_change(self) -> None:
        self.networks.on_change()
        self.deliver()

    def deliver(self) -> None:
        posted, self.posted = self.posted, []
        for message in posted:
            self.situations.on_message(message)

    def value(self, situation: Situation) -> frozenset[str] | None:
        """What went out last of a situation."""
        return {seen.situation: seen.values for seen in self.observations}[situation]

    @property
    def audio(self) -> FakeAudio:
        return next(made for made in reversed(self.made) if isinstance(made, FakeAudio))

    @property
    def networks(self) -> FakeNetworks:
        return next(made for made in reversed(self.made) if isinstance(made, FakeNetworks))

    def _audio(self, on_change: Callable[[], None]) -> FakeAudio:
        made = FakeAudio(self, on_change)
        self.made.append(made)
        return made

    def _networks(self, on_change: Callable[[], None]) -> FakeNetworks:
        made = FakeNetworks(self, on_change)
        self.made.append(made)
        return made

    def _machine[T](self, what: str, value: T) -> T:
        self.check(what)
        return value


@pytest.fixture
def scene(monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(monkeypatch)


def test_every_situation_goes_out_at_start_all_at_one_time(scene: Scene) -> None:
    scene.start()
    assert scene.observations == [
        SituationObservation(START, Situation.CALL, frozenset()),
        SituationObservation(START, Situation.AWAY, frozenset({NO})),
        SituationObservation(START, Situation.POWER, frozenset({PLUGGED})),
        SituationObservation(START, Situation.DISPLAY, frozenset({NO})),
        SituationObservation(START, Situation.HEADPHONES, frozenset({NO})),
        SituationObservation(START, Situation.NETWORK, frozenset({HOME})),
        SituationObservation(START, Situation.PLAYBACK, frozenset()),
    ]


def test_only_a_change_goes_out(scene: Scene) -> None:
    scene.start()
    scene.tick(10)
    scene.audio_changes()
    scene.networks_change()
    assert len(scene.observations) == len(Situation)
    scene.plugged, scene.display, scene.playing = False, True, {"spotify.exe"}
    scene.tick()
    at = START + 11 * TICK_MS
    assert scene.observations[len(Situation) :] == [
        SituationObservation(at, Situation.POWER, frozenset({BATTERY})),
        SituationObservation(at, Situation.DISPLAY, frozenset({YES})),
        SituationObservation(at, Situation.PLAYBACK, frozenset({"spotify.exe"})),
    ]


def test_nothing_goes_out_before_the_start(scene: Scene) -> None:
    scene.front(NOTEPAD_WINDOW, NOTES)
    scene.notice(win32.Notice.LOCKED)
    scene.situations.tick()
    assert scene.observations == []
    scene.start()
    assert scene.value(Situation.AWAY) == frozenset({YES})  # locked before it


def test_a_call_is_the_programs_that_capture_in_lower_case(scene: Scene) -> None:
    scene.start()
    scene.capturing = {DISCORD, UNKNOWN}  # a program that cannot be opened is left out
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"discord.exe"})
    scene.capturing = set()
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset()


def test_headphones_follow_the_default_output(scene: Scene) -> None:
    scene.start()
    scene.headphones = True
    scene.audio_changes()
    assert scene.value(Situation.HEADPHONES) == frozenset({YES})


def test_the_tab_in_front_that_records_gives_the_call_its_site(scene: Scene) -> None:
    scene.start()
    scene.front(CHROME_WINDOW, MEET)
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = True
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"meet.google.com"})


def test_the_call_keeps_its_site_while_the_browser_captures(scene: Scene) -> None:
    scene.start()
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = True
    scene.front(CHROME_WINDOW, MEET)
    scene.audio_changes()
    scene.recording[CHROME_WINDOW] = False
    scene.front(CHROME_WINDOW, MAIL)  # another tab, while the call goes on
    scene.front(NOTEPAD_WINDOW, NOTES)
    assert scene.value(Situation.CALL) == frozenset({"meet.google.com"})
    scene.capturing = set()
    scene.audio_changes()
    scene.capturing = {CHROME}
    scene.front(CHROME_WINDOW, MAIL)
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"chrome.exe"})  # the site left with the call


def test_the_tab_that_records_moves_the_site(scene: Scene) -> None:
    scene.start()
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = True
    scene.front(CHROME_WINDOW, MEET)
    scene.audio_changes()
    scene.front(CHROME_WINDOW, Context("chrome.exe", "Zoom", "app.zoom.us/wc/123"))
    assert scene.value(Situation.CALL) == frozenset({"app.zoom.us"})


def test_a_browser_whose_tab_cannot_tell_counts_whole(scene: Scene) -> None:
    scene.start()
    scene.capturing = {VIVALDI}
    scene.recording[VIVALDI_WINDOW] = None
    scene.front(VIVALDI_WINDOW, Context("vivaldi.exe", "Riunione", "meet.google.com/abc"))
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"vivaldi.exe"})
    assert scene.reads == [VIVALDI_WINDOW]


def test_the_tab_of_a_window_that_is_no_context_is_never_read(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.start()
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = True
    scene.front(CHROME_WINDOW, None)  # a private window, or one in full screen
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"chrome.exe"})
    scene.tick()
    assert scene.reads == []
    assert "could not be read" not in caplog.text


def test_a_mark_that_comes_after_the_capture_is_read_at_a_tick(scene: Scene) -> None:
    scene.start()
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = False  # the tab is not marked yet
    scene.front(CHROME_WINDOW, MEET)
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({"chrome.exe"})
    scene.recording[CHROME_WINDOW] = True
    scene.tick()
    assert scene.value(Situation.CALL) == frozenset({"meet.google.com"})
    reads = len(scene.reads)
    scene.tick(3)
    assert len(scene.reads) == reads  # known: no more reads at the ticks


@pytest.mark.parametrize(
    ("address", "call"),
    [
        ("localhost:8080/call", "localhost"),
        ("[::1]:8443/call", "::1"),
        ("Teams.Microsoft.com/v2", "teams.microsoft.com"),
        (None, "chrome.exe"),
    ],
    ids=["port", "ipv6", "upper case", "no address"],
)
def test_the_site_is_the_host_of_the_address(scene: Scene, address: str | None, call: str) -> None:
    scene.start()
    scene.capturing = {CHROME}
    scene.recording[CHROME_WINDOW] = True
    scene.front(CHROME_WINDOW, Context("chrome.exe", "Chiamata", address))
    scene.audio_changes()
    assert scene.value(Situation.CALL) == frozenset({call})


def test_away_comes_after_three_minutes_without_input_and_goes_with_the_next(
    scene: Scene,
) -> None:
    scene.start()
    scene.tick(AWAY_MS // TICK_MS - 1)
    assert scene.value(Situation.AWAY) == frozenset({NO})
    scene.tick()
    assert scene.observations[-1] == SituationObservation(
        START + AWAY_MS, Situation.AWAY, frozenset({YES})
    )
    scene.clock.advance(400)
    scene.touch()
    scene.tick()
    assert scene.observations[-1] == SituationObservation(
        START + AWAY_MS + 1_400, Situation.AWAY, frozenset({NO})
    )


def test_something_playing_keeps_away_off_and_its_end_is_no_return(scene: Scene) -> None:
    scene.start()
    scene.playing = {"spotify.exe"}
    scene.tick(600)  # ten minutes of music without a key
    assert scene.value(Situation.AWAY) == frozenset({NO})
    scene.playing = set()
    scene.tick(AWAY_MS // TICK_MS - 1)
    assert scene.value(Situation.AWAY) == frozenset({NO})
    scene.tick()
    assert scene.observations[-1] == SituationObservation(
        START + 600_000 + AWAY_MS, Situation.AWAY, frozenset({YES})
    )


def test_a_call_keeps_away_off_until_three_minutes_after_its_end(scene: Scene) -> None:
    scene.start()
    scene.capturing = {DISCORD}
    scene.audio_changes()
    scene.tick(600)
    scene.capturing = set()
    scene.audio_changes()
    scene.tick(AWAY_MS // TICK_MS - 1)
    assert scene.value(Situation.AWAY) == frozenset({NO})
    scene.tick()
    assert scene.value(Situation.AWAY) == frozenset({YES})


def test_a_lock_or_a_sleep_is_away_at_once_until_both_are_over(scene: Scene) -> None:
    scene.start()
    scene.playing = {"spotify.exe"}  # music does not keep a locked PC near
    scene.tick()
    scene.notice(win32.Notice.LOCKED)
    assert scene.observations[-1] == SituationObservation(
        START + TICK_MS, Situation.AWAY, frozenset({YES})
    )
    for notice in (win32.Notice.SLEEPING, win32.Notice.AWAKE):
        scene.clock.advance(60_000)
        scene.notice(notice)
    assert scene.value(Situation.AWAY) == frozenset({YES})
    scene.clock.advance(5_000)
    scene.touch()
    scene.notice(win32.Notice.UNLOCKED)
    assert scene.observations[-1] == SituationObservation(
        START + TICK_MS + 125_000, Situation.AWAY, frozenset({NO})
    )


def test_a_pc_that_sleeps_without_a_lock_is_away_until_it_wakes(scene: Scene) -> None:
    scene.start()
    scene.notice(win32.Notice.SLEEPING)
    assert scene.value(Situation.AWAY) == frozenset({YES})
    scene.clock.advance(60_000)
    scene.touch()  # the key that woke it
    scene.notice(win32.Notice.AWAKE)
    assert scene.value(Situation.AWAY) == frozenset({NO})


@pytest.mark.parametrize(
    ("connected", "network"),
    [
        ({HOME_ID}, {HOME}),
        ({HOME_ID, OFFICE_ID}, {HOME, OFFICE}),
        ({CAFE_ID}, set()),
        ({CAFE_ID, OFFICE_ID}, {OFFICE}),
        (set(), {OFFLINE}),
    ],
    ids=["home", "both", "no label", "one labelled", "offline"],
)
def test_the_networks_give_their_labels(
    scene: Scene, connected: set[str], network: set[str]
) -> None:
    scene.start()
    scene.connected = connected
    scene.networks_change()
    assert scene.value(Situation.NETWORK) == frozenset(network)


def test_a_burst_of_changes_wakes_the_thread_once(scene: Scene) -> None:
    scene.start()
    reads = scene.audio_reads
    for _ in range(3):
        scene.audio.on_change()
    assert len(scene.posted) == 1
    scene.deliver()
    assert scene.audio_reads == reads + 1
    scene.audio.on_change()  # after the thread took the message
    assert len(scene.posted) == 1


def test_a_source_that_cannot_start_is_not_read_and_starts_again_later(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.failing["audio start"] = COM_FAILURE
    with caplog.at_level(logging.INFO, logger="jiffin.platform.capture"):
        scene.start()
        assert scene.value(Situation.CALL) is None
        assert scene.value(Situation.HEADPHONES) is None
        scene.tick(RETRY_MS // TICK_MS - 1)
        assert "audio" not in scene.started
        del scene.failing["audio start"]
        scene.touch()
        scene.tick()
    assert scene.value(Situation.CALL) == frozenset()
    assert scene.value(Situation.HEADPHONES) == frozenset({NO})
    assert caplog.text.count("Core Audio cannot be read: error 0x80004005") == 1
    assert "Core Audio read again" in caplog.text


def test_a_source_that_fails_gives_its_situations_no_value_until_it_reads(scene: Scene) -> None:
    scene.capturing, scene.headphones = {DISCORD}, True
    scene.start()
    scene.failing["audio"] = COM_FAILURE  # the audio service went away
    scene.audio_changes()
    assert (scene.value(Situation.CALL), scene.value(Situation.HEADPHONES)) == (None, None)
    del scene.failing["audio"]
    scene.tick(RETRY_MS // TICK_MS)
    assert scene.value(Situation.CALL) == frozenset({"discord.exe"})
    assert scene.value(Situation.HEADPHONES) == frozenset({YES})


def test_a_source_that_fails_a_read_is_closed_and_started_again(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.start()
    scene.failing["media"] = DENIED
    with caplog.at_level(logging.INFO, logger="jiffin.platform.capture"):
        scene.tick()
        assert (scene.value(Situation.PLAYBACK), scene.closed) == (None, ["media"])
        del scene.failing["media"]
        scene.tick(RETRY_MS // TICK_MS - 1)
        assert scene.started.count("media") == 1
        scene.tick()
    assert scene.started.count("media") == 2
    assert scene.value(Situation.PLAYBACK) == frozenset()
    assert "the media controls cannot be read: error 0x00000005" in caplog.text
    assert "the media controls read again" in caplog.text


def test_a_state_that_cannot_be_read_has_no_value_until_it_reads(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    scene.start()
    scene.failing["power"] = scene.failing["idle"] = DENIED
    with caplog.at_level(logging.INFO, logger="jiffin.platform.capture"):
        scene.tick(3)
        assert (scene.value(Situation.POWER), scene.value(Situation.AWAY)) == (None, None)
        scene.failing.clear()
        scene.tick()
    assert scene.value(Situation.POWER) == frozenset({PLUGGED})
    assert scene.value(Situation.AWAY) == frozenset({NO})
    assert caplog.text.count("the power cannot be read: error 0x00000005") == 1
    assert caplog.text.count("the time since the last input read again") == 1


def test_the_log_names_programs_and_labels_but_never_a_site_or_a_network(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="jiffin.platform.capture"):
        scene.start()
        scene.capturing = {DISCORD, CHROME}
        scene.recording[CHROME_WINDOW] = True
        scene.front(CHROME_WINDOW, MEET)
        scene.audio_changes()
    assert "network: home" in caplog.text
    assert "call: discord.exe, 1 site" in caplog.text
    assert "meet.google.com" not in caplog.text
    assert HOME_ID not in caplog.text


def test_closing_closes_every_source(scene: Scene) -> None:
    scene.start()
    scene.situations.close()
    assert sorted(scene.closed) == ["audio", "media", "networks"]
