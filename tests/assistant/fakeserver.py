"""A local HTTP server standing in for the Anthropic or an OpenAI-compatible
API in tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer


@contextmanager
def serve(answer: Callable[[str, str, dict | None], tuple[int, str, bytes]]):
    """An HTTP server on localhost; `answer(method, path, body)` gives the
    status, content type and body of each response."""
    requests: list[tuple[str, str, dict | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, method: str) -> None:
            length = int(self.headers.get("content-length", 0))
            body = json.loads(self.rfile.read(length)) if length else None
            requests.append((method, self.path, body))
            status, kind, data = answer(method, self.path, body)
            self.send_response(status)
            self.send_header("content-type", kind)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802 - http.server naming
            self._reply("GET")

        def do_POST(self):  # noqa: N802
            self._reply("POST")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()


def json_reply(status: int, value) -> tuple[int, str, bytes]:
    return status, "application/json", json.dumps(value).encode()


def sse(*chunks: dict) -> tuple[int, str, bytes]:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]
    return 200, "text/event-stream", "".join(lines).encode()


def chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "local",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
