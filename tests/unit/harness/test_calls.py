import json
from datetime import UTC, date
from pathlib import Path

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.model import EngineBuild
from jiffin.core.records import Evaluation
from jiffin.core.situations import NO, YES, Situation, SituationStretch
from jiffin.harness import calls
from jiffin.harness.errors import HarnessError

T0 = 1_791_190_800_000  # 2026-10-05 09:00 UTC
DAY = date(2026, 10, 5)
MINUTE = 60_000
BUILD = EngineBuild(1, "0.1.0", "b11081", "79de5cb8", 1, 2)
MAIL = Context("outlook.exe", "Posta in arrivo", None)
FIGMA = Context("figma.exe", "Icone - Figma", None)


def at(minutes: float) -> int:
    return T0 + round(minutes * MINUTE)


def stretch(kind: Situation, value: str, since: float, until: float) -> SituationStretch:
    return SituationStretch(kind, value, at(since), at(until))


ZOOM = stretch(Situation.CALL, "zoom.exe", 60, 90)
LUNCH = stretch(Situation.AWAY, YES, 180, 200)
RECORDED = (
    stretch(Situation.AWAY, NO, 0, 180),
    stretch(Situation.POWER, "plugged", 0, 240),
    ZOOM,
    LUNCH,
)
EVALUATIONS = (
    Evaluation(1, at(1), MAIL, at(0), 0.97, BUILD, ()),
    Evaluation(2, at(76), FIGMA, at(75), 0.97, BUILD, ()),  # during the Zoom call
)


def test_the_page_lists_the_calls_and_absences_with_the_apps_in_front(tmp_path: Path) -> None:
    path = calls.path_for(tmp_path, DAY)
    prepared = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    assert [(s["kind"], s["value"]) for s in prepared.stretches] == [
        ("call", "zoom.exe"),
        ("away", YES),
    ]
    zoom, lunch = prepared.stretches
    assert (zoom["since"], zoom["until"]) == (ZOOM.since, ZOOM.until)
    assert (zoom["before"], zoom["after"]) == ("outlook.exe", "figma.exe")
    assert (lunch["before"], lunch["after"]) == ("figma.exe", "figma.exe")
    assert zoom["key"] == calls.key(ZOOM) != calls.key(LUNCH)
    assert calls.load(path).stretches == prepared.stretches


def test_a_new_copy_keeps_the_owners_marks_and_asks_for_the_check_again(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    path = calls.path_for(tmp_path, DAY)
    owners = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    owners.mark(calls.key(ZOOM), True)
    owners.add("away", None, "13:00", "13:30", clock)
    owners.check(clock.local(at(300)))
    same = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    assert (same.wrong, len(same.added), same.checked) == ([calls.key(ZOOM)], 1, owners.checked)
    later = stretch(Situation.CALL, "ms-teams.exe", 220, 230)
    again = calls.prepare((*RECORDED, later), EVALUATIONS, path, DAY)
    assert (again.wrong, len(again.added), again.checked) == ([calls.key(ZOOM)], 1, None)


def test_the_owner_marks_and_unmarks_a_stretch_at_once(tmp_path: Path) -> None:
    path = calls.path_for(tmp_path, DAY)
    owners = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    owners.mark(calls.key(LUNCH), True)
    assert calls.load(path).wrong == [calls.key(LUNCH)]
    owners.mark(calls.key(LUNCH), False)
    assert calls.load(path).wrong == []
    with pytest.raises(ValueError, match="unknown stretch"):
        owners.mark("0123456789abcdef", True)
    with pytest.raises(TypeError):
        owners.mark(calls.key(LUNCH), "sì")


def test_an_added_call_is_on_an_app_a_condition_names(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    owners = calls.prepare(RECORDED, EVALUATIONS, calls.path_for(tmp_path, DAY), DAY)
    owners.add("call", "ms-teams.exe", "11:00", "11:20", clock)
    owners.add("call", calls.OTHER, "12:00", "12:05", clock)
    owners.add("away", "anything", "13:00", "13:30", clock)  # an absence is yes
    assert owners.added == [
        {"kind": "call", "value": "ms-teams.exe", "since": at(120), "until": at(140)},
        {"kind": "call", "value": calls.OTHER, "since": at(180), "until": at(185)},
        {"kind": "away", "value": YES, "since": at(240), "until": at(270)},
    ]
    assert calls.APPS["ms-teams.exe"] == "Microsoft Teams"
    assert calls.APPS["meet.google.com"] == "Google Meet"  # an app with no executable


@pytest.mark.parametrize(
    ("kind", "value", "start", "end", "error"),
    [
        ("call", "vlc.exe", "11:00", "11:20", ValueError),
        ("power", None, "11:00", "11:20", ValueError),
        ("call", "zoom.exe", "11:20", "11:00", ValueError),
        ("call", "zoom.exe", "11:00", "11:00", ValueError),
        ("call", "zoom.exe", "le 11", "11:20", ValueError),
        ("call", "zoom.exe", 1100, "11:20", TypeError),
    ],
)
def test_an_added_stretch_that_cannot_be_is_refused(
    tmp_path: Path, kind: str, value: object, start: object, end: object, error: type[Exception]
) -> None:
    path = calls.path_for(tmp_path, DAY)
    owners = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    with pytest.raises(error):
        owners.add(kind, value, start, end, SimulatedClock(T0, UTC))
    assert calls.load(path).added == []


def test_an_added_stretch_is_removed_by_its_place(tmp_path: Path) -> None:
    clock = SimulatedClock(T0, UTC)
    path = calls.path_for(tmp_path, DAY)
    owners = calls.prepare(RECORDED, EVALUATIONS, path, DAY)
    owners.add("away", None, "13:00", "13:30", clock)
    owners.add("away", None, "14:00", "14:30", clock)
    owners.remove(0)
    assert [a["since"] for a in calls.load(path).added] == [at(300)]
    with pytest.raises(TypeError):
        owners.remove(True)
    with pytest.raises(IndexError):
        owners.remove(1)


def test_a_file_of_another_format_or_not_json_is_refused(tmp_path: Path) -> None:
    path = calls.path_for(tmp_path, DAY)
    path.write_text(json.dumps({"format": 99, "day": DAY.isoformat()}), encoding="utf-8")
    with pytest.raises(HarnessError, match="format 99"):
        calls.load(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(HarnessError, match="not valid JSON"):
        calls.load(path)
