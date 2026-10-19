"""Where the running figscribe can be reached, and the wire format.

The application listens on 127.0.0.1 at a free port and writes the port and a
random token to a file only the user can read. `figscribe mcp` reads that file
to connect. TCP on localhost works the same on every platform; the token keeps
other local processes and users from driving the application.

Requests and responses are single lines of JSON:

    {"token": "...", "tool": "set_field", "arguments": {...}}
    {"ok": true, "result": {...}}  or  {"ok": false, "error": "..."}

Pure Python, no Qt: both sides import it.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_DIR = "FIGSCRIBE_STATE_DIR"
"""Overrides the directory of the endpoint file, e.g. in tests."""

MAX_LINE = 64 * 1024 * 1024
"""Upper bound for one message; a preview image is well below it."""


@dataclass(frozen=True)
class Endpoint:
    port: int
    token: str
    pid: int


def state_dir() -> Path:
    """The per-user directory for figscribe's runtime files."""
    if os.environ.get(ENV_DIR):
        return Path(os.environ[ENV_DIR])
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "figscribe"


def endpoint_file() -> Path:
    return state_dir() / "mcp-endpoint.json"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def publish(endpoint: Endpoint) -> Path:
    """Write the endpoint file, readable by the user only."""
    path = endpoint_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(
        {"port": endpoint.port, "token": endpoint.token, "pid": endpoint.pid}
    )
    # Created with owner-only permissions before the token goes in.
    # Owner-only permissions before the token goes in, also when the file
    # already existed with others. On Windows the per-user directory protects it.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    return path


def withdraw(endpoint: Endpoint) -> None:
    """Remove the endpoint file if it is still this endpoint's."""
    current = read()
    if current is not None and current.token == endpoint.token:
        endpoint_file().unlink(missing_ok=True)


def read() -> Endpoint | None:
    """The published endpoint, or None if figscribe is not listening."""
    try:
        data = json.loads(endpoint_file().read_text(encoding="utf-8"))
        return Endpoint(
            port=int(data["port"]), token=str(data["token"]), pid=int(data["pid"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def encode(message: dict) -> bytes:
    return json.dumps(message).encode("utf-8") + b"\n"


def decode(line: bytes) -> dict:
    message = json.loads(line.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("a message must be a JSON object")
    return message
