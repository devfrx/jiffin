"""The owner's pages: the labelling page, and the check of the day's calls and absences. Each is a
local server on 127.0.0.1, behind a random token.

As the prototype's page of 2026-09-28 (`NO_GIT\\sibyl-campione\\giudica.py`): the Host check
stops DNS rebinding, the token stops any other page or local program, and every answer is saved
at once. The labelling page never learns Claude's labels, nor any score.
"""

import hmac
import json
import logging
import secrets
import webbrowser
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, cast
from urllib.parse import SplitResult, parse_qs, urlsplit

from jiffin.core.clock import Clock
from jiffin.core.situations import Situation
from jiffin.harness import render
from jiffin.harness.calls import APPS, OTHER, Calls
from jiffin.harness.labels import Labels
from jiffin.lang.harness import HARNESS

log = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'"
    ),
}
BODY_LIMIT = 64 * 1024
"""The longest body the page reads: an answer takes some 40 bytes."""


class PageServer(HTTPServer):
    """Serves a page, its data at /data, and the answers it posts to its `routes`."""

    routes: frozenset[str] = frozenset()

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = secrets.token_urlsafe(16)
        self.host = f"127.0.0.1:{self.server_address[1]}"
        self.url = f"http://{self.host}/?t={self.token}"

    def page(self) -> str:
        raise NotImplementedError

    def data(self) -> dict[str, object]:
        raise NotImplementedError

    def post(self, route: str, answer: Any) -> None:
        """Save an answer the page posted to one of its `routes`, or refuse it with ValueError,
        LookupError or TypeError."""
        raise NotImplementedError


class LabelServer(PageServer):
    """Serves the page for some of the pairs of `labels`."""

    routes = frozenset({"/label"})

    def __init__(self, labels: Labels, keys: list[str]) -> None:
        super().__init__()
        self.labels = labels
        self.keys = keys

    def page(self) -> str:
        return render.text("label.html", texts=asdict(HARNESS.label))

    def data(self) -> dict[str, object]:
        chosen = set(self.keys)
        pairs = [pair for pair in self.labels.pairs if pair["key"] in chosen]
        pairs.sort(key=lambda pair: self.keys.index(pair["key"]))
        answers = {key: self.labels.owner[key] for key in self.keys if key in self.labels.owner}
        return {"pairs": pairs, "answers": answers}

    def post(self, route: str, answer: Any) -> None:
        if answer["key"] not in self.keys:
            raise ValueError("a pair outside this page")
        self.labels.answer(answer["key"], answer["relevant"])


class CallsServer(PageServer):
    """Serves the page of the day's calls and absences, where the owner marks the wrong ones,
    adds the missing ones and closes with "Controllato" (ADR-0031). Its times are local."""

    routes = frozenset({"/wrong", "/add", "/remove", "/checked"})

    def __init__(self, calls: Calls, clock: Clock) -> None:
        super().__init__()
        self.calls = calls
        self.clock = clock

    def page(self) -> str:
        texts = asdict(HARNESS.calls)
        return render.text("calls.html", texts=texts, day=self.calls.day.isoformat())

    def data(self) -> dict[str, object]:
        checked = self.calls.checked
        return {
            "stretches": [
                self._stretch(stretch) | {key: stretch[key] for key in ("key", "before", "after")}
                for stretch in self.calls.stretches
            ],
            "wrong": self.calls.wrong,
            "added": [self._stretch(added) for added in self.calls.added],
            "apps": [[value, name] for value, name in APPS.items()],
            "other": OTHER,
            "checked": None if checked is None else f"{datetime.fromisoformat(checked):%H:%M}",
        }

    def post(self, route: str, answer: Any) -> None:
        if route == "/wrong":
            self.calls.mark(answer["key"], answer["wrong"])
        elif route == "/add":
            start, end = answer["start"], answer["end"]
            self.calls.add(answer["kind"], answer["app"], start, end, self.clock)
        elif route == "/remove":
            self.calls.remove(answer["index"])
        else:
            self.calls.check(self.clock.local(self.clock.now()))

    def _stretch(self, stretch: dict[str, Any]) -> dict[str, object]:
        """A call or an absence as the page shows it: an absence has no app."""
        call = stretch["kind"] == Situation.CALL.value
        return {
            "kind": stretch["kind"],
            "app": stretch["value"] if call else None,
            "start": f"{self.clock.local(stretch['since']):%H:%M}",
            "end": f"{self.clock.local(stretch['until']):%H:%M}",
        }


def serve(server: PageServer, open_browser: bool = True) -> None:
    """Until Ctrl+C."""
    log.info("the page: %s", server.url)
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class _Handler(BaseHTTPRequestHandler):
    timeout = 2
    """Seconds a read or a write may wait: a browser sends its request at once. The page serves one
    connection at a time, so a client that goes silent is dropped instead of holding up others."""

    def log_message(self, format: str, *args: object) -> None:
        pass  # the console is for whoever labels, not for the requests

    @property
    def _server(self) -> PageServer:
        return cast(PageServer, self.server)

    def _target(self) -> SplitResult | None:
        """The request's target, or None if it is no URL, as `http://[::1/` is not."""
        try:
            return urlsplit(self.path)
        except ValueError:
            return None

    def _allowed(self, target: SplitResult) -> bool:
        token = parse_qs(target.query).get("t", [""])[0]
        server = self._server
        return self.headers.get("Host") == server.host and hmac.compare_digest(
            token.encode(), server.token.encode()
        )

    def _body(self) -> bytes | None:
        """The whole body, or None if its length is not a number from 0 to `BODY_LIMIT`.

        Read before any answer: closing a connection with part of the request unread resets it,
        and on Windows the client then loses the answer. A body refused stays unread.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        return self.rfile.read(length) if 0 <= length <= BODY_LIMIT else None

    def _send(
        self, status: int, body: str, content_type: str = "text/plain; charset=utf-8"
    ) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        target = self._target()
        if target is None:
            return self._send(400, "Invalid target")
        if not self._allowed(target):
            return self._send(403, "Forbidden")
        route = target.path
        if route == "/":
            return self._send(200, self._server.page(), "text/html; charset=utf-8")
        if route == "/data":
            body = json.dumps(self._server.data(), ensure_ascii=False)
            return self._send(200, body, "application/json")
        self._send(404, "Not found")

    def do_POST(self) -> None:
        body = self._body()
        target = self._target()
        if target is None:
            return self._send(400, "Invalid target")
        if not self._allowed(target) or target.path not in self._server.routes:
            return self._send(403, "Forbidden")
        if body is None:
            return self._send(400, f"Invalid length: up to {BODY_LIMIT} bytes")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send(415, "JSON only")
        try:
            self._server.post(target.path, json.loads(body))
        except (ValueError, LookupError, TypeError) as error:
            return self._send(400, f"Invalid answer: {error}")
        self._send(200, '{"ok": true}', "application/json")
