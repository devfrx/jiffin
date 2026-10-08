import contextlib
import http.client
import json
import select
import threading
from collections.abc import Iterator
from datetime import UTC, date
from pathlib import Path

import pytest

from jiffin.core.clock import SimulatedClock
from jiffin.core.context import Context
from jiffin.core.records import Revision
from jiffin.core.situations import NO, YES, Situation, SituationStretch
from jiffin.harness import calls, labels, page
from jiffin.harness.day import Pair
from jiffin.lang.harness import HARNESS

DAY = date(2026, 10, 5)
ICONS = Revision(10, 1, 1, "quando apro Figma", "esportare le icone", "quando apro Figma")
PAIRS = {
    pair.key: pair
    for pair in (
        Pair(Context("figma.exe", "<script>alert(1)</script>", None), ICONS),
        Pair(Context("vivaldi.exe", "Banca Rossi", "bancarossi.it"), ICONS),
        Pair(Context("outlook.exe", "Posta in arrivo", None), ICONS),
    )
}
SCRIPT, BANK, MAIL = PAIRS
QUIET = 0.2
"""Seconds without an answer that show the server still waits: it answers in milliseconds."""
T0 = 1_791_190_800_000  # 2026-10-05 09:00 UTC
ZOOM = SituationStretch(Situation.CALL, "zoom.exe", T0 + 3_600_000, T0 + 5_400_000)
LUNCH = SituationStretch(Situation.AWAY, YES, T0 + 10_800_000, T0 + 12_000_000)
RECORDED = (SituationStretch(Situation.AWAY, NO, T0, T0 + 10_800_000), ZOOM, LUNCH)


def running[S: page.PageServer](started: S) -> Iterator[S]:
    thread = threading.Thread(
        target=started.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    yield started
    started.shutdown()
    started.server_close()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[page.LabelServer]:
    labelled = labels.prepare(PAIRS, labels.path_for(tmp_path, DAY), DAY)
    labelled.claude = {SCRIPT: True, BANK: False}
    labelled.save()
    yield from running(page.LabelServer(labelled, [BANK, SCRIPT]))


@pytest.fixture
def calls_server(tmp_path: Path) -> Iterator[page.CallsServer]:
    prepared = calls.prepare(RECORDED, (), calls.path_for(tmp_path, DAY), DAY)
    yield from running(page.CallsServer(prepared, SimulatedClock(T0, UTC)))


def request(
    server: page.PageServer,
    method: str,
    path: str,
    body: object = None,
    *,
    token: str | None = None,
    host: str | None = None,
    content_type: str = "application/json",
) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    target = f"{path}?t={server.token if token is None else token}"
    headers = {"Host": host or server.host, "Content-Type": content_type}
    connection.request(method, target, None if body is None else json.dumps(body), headers)
    response = connection.getresponse()
    status, text = response.status, response.read().decode("utf-8")
    connection.close()
    return status, text


def send_head(
    server: page.PageServer,
    length: str,
    path: str = "/label",
    *,
    token: str | None = None,
    host: str | None = None,
    content_type: str = "application/json",
) -> http.client.HTTPConnection:
    """A POST's line and headers, without the body they announce."""
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    target = f"{path}?t={server.token if token is None else token}"
    connection.putrequest("POST", target, skip_host=True)
    connection.putheader("Host", host or server.host)
    connection.putheader("Content-Type", content_type)
    connection.putheader("Content-Length", length)
    connection.endheaders()
    return connection


def test_the_page_needs_the_token_and_the_host(server: page.LabelServer) -> None:
    assert request(server, "GET", "/")[0] == 200
    assert request(server, "GET", "/", token="guessed")[0] == 403
    assert request(server, "GET", "/", host="attacker.example:80")[0] == 403


def test_the_page_gets_its_share_without_claudes_labels(server: page.LabelServer) -> None:
    status, text = request(server, "GET", "/data")
    data = json.loads(text)
    assert status == 200
    assert [pair["key"] for pair in data["pairs"]] == [BANK, SCRIPT]
    assert data["answers"] == {}
    assert "claude" not in text


def test_an_answer_is_saved_at_once(server: page.LabelServer) -> None:
    assert request(server, "POST", "/label", {"key": BANK, "relevant": True})[0] == 200
    assert labels.load(server.labels.path).owner == {BANK: True}
    assert json.loads(request(server, "GET", "/data")[1])["answers"] == {BANK: True}


@pytest.mark.parametrize(
    ("body", "content_type", "status"),
    [
        ({"key": MAIL, "relevant": True}, "application/json", 400),  # not in this share
        ({"key": BANK, "relevant": "sì"}, "application/json", 400),
        ({"key": BANK}, "application/json", 400),
        ({"key": BANK, "relevant": True}, "text/plain", 415),
    ],
)
def test_a_wrong_answer_is_refused_and_not_saved(
    server: page.LabelServer, body: object, content_type: str, status: int
) -> None:
    assert request(server, "POST", "/label", body, content_type=content_type)[0] == status
    assert labels.load(server.labels.path).owner == {}


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"token": "guessed"}, 403),
        ({"host": "attacker.example:80"}, 403),
        ({"path": "/data"}, 403),
        ({"content_type": "text/plain"}, 415),
        ({}, 200),
    ],
)
def test_the_page_answers_only_after_the_whole_body(
    server: page.LabelServer, changes: dict[str, str], status: int
) -> None:
    # A body not read whole when the connection closes makes Windows reset it, and the client
    # then loses the answer: about 1 time in 10 for the 403 and the 415, on 2026-10-01.
    body = json.dumps({"key": BANK, "relevant": True}).encode()
    with contextlib.closing(send_head(server, str(len(body)), **changes)) as connection:
        connection.send(body[:-1])
        assert select.select([connection.sock], [], [], QUIET)[0] == []
        connection.send(body[-1:])
        assert connection.getresponse().status == status


@pytest.mark.parametrize("length", ["many", "-1", str(page.BODY_LIMIT + 1)])
def test_the_page_refuses_a_length_it_will_not_read(server: page.LabelServer, length: str) -> None:
    with contextlib.closing(send_head(server, length)) as connection:
        assert connection.getresponse().status == 400
    assert labels.load(server.labels.path).owner == {}


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_the_page_refuses_a_target_that_is_no_url(server: page.LabelServer, method: str) -> None:
    body = {"key": BANK, "relevant": True} if method == "POST" else None
    assert request(server, method, "http://[::1/label", body)[0] == 400
    assert labels.load(server.labels.path).owner == {}


def test_a_stalled_request_does_not_hold_the_page(server: page.LabelServer) -> None:
    # The page serves one connection at a time: a client that stops in the middle of its
    # request would hold it, and a test waiting on the page would then hang instead of failing.
    # The page's timeout must stay under the 5 s that `request()` waits.
    with contextlib.closing(send_head(server, "40")):
        assert request(server, "GET", "/data")[0] == 200


def test_texts_reach_the_page_only_as_data(server: page.LabelServer) -> None:
    html = request(server, "GET", "/")[1]
    assert "<script>alert(1)</script>" not in html
    assert "textContent" in html


def test_the_calls_page_shows_the_days_calls_and_absences_in_local_time(
    calls_server: page.CallsServer,
) -> None:
    html = request(calls_server, "GET", "/")[1]
    assert HARNESS.calls.heading.format(day="2026-10-05") in html
    data = json.loads(request(calls_server, "GET", "/data")[1])
    assert data["stretches"] == [
        {
            "kind": "call",
            "app": "zoom.exe",
            "start": "10:00",
            "end": "10:30",
            "key": calls.key(ZOOM),
            "before": None,
            "after": None,
        },
        {
            "kind": "away",
            "app": None,
            "start": "12:00",
            "end": "12:20",
            "key": calls.key(LUNCH),
            "before": None,
            "after": None,
        },
    ]
    assert ["zoom.exe", "Zoom"] in data["apps"]
    assert (data["other"], data["wrong"], data["added"], data["checked"]) == (
        calls.OTHER,
        [],
        [],
        None,
    )


def test_the_owners_check_is_saved_at_once(calls_server: page.CallsServer) -> None:
    def post(route: str, answer: object) -> int:
        return request(calls_server, "POST", route, answer)[0]

    assert post("/wrong", {"key": calls.key(ZOOM), "wrong": True}) == 200
    teams = {"kind": "call", "app": "ms-teams.exe", "start": "11:00", "end": "11:20"}
    assert post("/add", teams) == 200
    assert post("/add", {"kind": "away", "app": None, "start": "13:00", "end": "13:30"}) == 200
    assert post("/remove", {"index": 0}) == 200
    assert post("/checked", {}) == 200
    saved = calls.load(calls_server.calls.path)
    assert saved.wrong == [calls.key(ZOOM)]
    assert saved.added == [
        {"kind": "away", "value": YES, "since": T0 + 14_400_000, "until": T0 + 16_200_000}
    ]
    assert saved.checked == "2026-10-05T09:00:00+00:00"
    data = json.loads(request(calls_server, "GET", "/data")[1])
    assert data["added"] == [{"kind": "away", "app": None, "start": "13:00", "end": "13:30"}]
    assert (data["wrong"], data["checked"]) == ([calls.key(ZOOM)], "09:00")


@pytest.mark.parametrize(
    ("route", "answer"),
    [
        ("/wrong", {"key": "0123456789abcdef", "wrong": True}),
        ("/wrong", {"key": calls.key(ZOOM), "wrong": "sì"}),
        ("/add", {"kind": "call", "app": "vlc.exe", "start": "11:00", "end": "11:20"}),
        ("/add", {"kind": "call", "app": "zoom.exe", "start": "11:20", "end": "11:00"}),
        ("/add", {"kind": "call", "start": "11:00", "end": "11:20"}),
        ("/remove", {"index": 0}),  # nothing added
        ("/remove", {"index": "0"}),
    ],
)
def test_a_wrong_change_is_refused_and_not_saved(
    calls_server: page.CallsServer, route: str, answer: object
) -> None:
    status = request(calls_server, "POST", route, answer)[0]
    saved = calls.load(calls_server.calls.path)
    assert (status, saved.wrong, saved.added, saved.checked) == (400, [], [], None)


def test_each_page_takes_only_its_own_answers(
    server: page.LabelServer, calls_server: page.CallsServer
) -> None:
    assert request(calls_server, "POST", "/label", {"key": BANK, "relevant": True})[0] == 403
    assert request(server, "POST", "/checked", {})[0] == 403
