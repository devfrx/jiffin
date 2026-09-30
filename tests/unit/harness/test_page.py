import http.client
import json
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from jiffin.core.context import Context
from jiffin.core.records import Revision
from jiffin.harness import labels, page
from jiffin.harness.day import Pair

DAY = date(2026, 10, 5)
ICONS = Revision(10, 1, 1, "quando apro Figma", "esportare le icone")
PAIRS = {
    pair.key: pair
    for pair in (
        Pair(Context("figma.exe", "<script>alert(1)</script>", None), ICONS),
        Pair(Context("vivaldi.exe", "Banca Rossi", "bancarossi.it"), ICONS),
        Pair(Context("outlook.exe", "Posta in arrivo", None), ICONS),
    )
}
SCRIPT, BANK, MAIL = PAIRS


@pytest.fixture
def server(tmp_path: Path) -> Iterator[page.LabelServer]:
    labelled = labels.prepare(PAIRS, labels.path_for(tmp_path, DAY), DAY)
    labelled.claude = {SCRIPT: True, BANK: False}
    labelled.save()
    started = page.LabelServer(labelled, [BANK, SCRIPT])
    thread = threading.Thread(target=started.serve_forever, daemon=True)
    thread.start()
    yield started
    started.shutdown()
    started.server_close()


def request(
    server: page.LabelServer,
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


def test_texts_reach_the_page_only_as_data(server: page.LabelServer) -> None:
    html = request(server, "GET", "/")[1]
    assert "<script>alert(1)</script>" not in html
    assert "textContent" in html
