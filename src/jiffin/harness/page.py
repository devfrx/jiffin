"""The owner's labelling page: a local server on 127.0.0.1, behind a random token.

As the prototype's page of 2026-09-28 (`NO_GIT\\sibyl-campione\\giudica.py`): the Host check
stops DNS rebinding, the token stops any other page or local program, and every answer is saved
at once. The page never learns Claude's labels, nor any score.
"""

import hmac
import json
import logging
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from typing import cast
from urllib.parse import parse_qs, urlsplit

from jiffin.harness.labels import Labels

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


class LabelServer(HTTPServer):
    """Serves the page for some of the pairs of `labels`."""

    def __init__(self, labels: Labels, keys: list[str]) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.labels = labels
        self.keys = keys
        self.token = secrets.token_urlsafe(16)
        self.host = f"127.0.0.1:{self.server_address[1]}"
        self.url = f"http://{self.host}/?t={self.token}"

    def data(self) -> dict[str, object]:
        chosen = set(self.keys)
        pairs = [pair for pair in self.labels.pairs if pair["key"] in chosen]
        pairs.sort(key=lambda pair: self.keys.index(pair["key"]))
        answers = {key: self.labels.owner[key] for key in self.keys if key in self.labels.owner}
        return {"pairs": pairs, "answers": answers}


def serve(server: LabelServer, open_browser: bool = True) -> None:
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
    def log_message(self, format: str, *args: object) -> None:
        pass  # the console is for whoever labels, not for the requests

    @property
    def _server(self) -> LabelServer:
        return cast(LabelServer, self.server)

    def _allowed(self) -> bool:
        token = parse_qs(urlsplit(self.path).query).get("t", [""])[0]
        server = self._server
        return self.headers.get("Host") == server.host and hmac.compare_digest(
            token.encode(), server.token.encode()
        )

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
        if not self._allowed():
            return self._send(403, "Forbidden")
        route = urlsplit(self.path).path
        if route == "/":
            page = resources.files("jiffin.harness") / "pages" / "label.html"
            return self._send(200, page.read_text(encoding="utf-8"), "text/html; charset=utf-8")
        if route == "/data":
            body = json.dumps(self._server.data(), ensure_ascii=False)
            return self._send(200, body, "application/json")
        self._send(404, "Not found")

    def do_POST(self) -> None:
        body = self._body()
        if not self._allowed() or urlsplit(self.path).path != "/label":
            return self._send(403, "Forbidden")
        if body is None:
            return self._send(400, f"Invalid length: up to {BODY_LIMIT} bytes")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._send(415, "JSON only")
        try:
            answer = json.loads(body)
            if answer["key"] not in self._server.keys:
                raise ValueError("a pair outside this page")
            self._server.labels.answer(answer["key"], answer["relevant"])
        except (ValueError, KeyError, TypeError) as error:
            return self._send(400, f"Invalid answer: {error}")
        self._send(200, '{"ok": true}', "application/json")

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
