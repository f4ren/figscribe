"""The application side: runs tool requests from `figscribe mcp` on the GUI thread.

Every request goes through the Toolbox of the current Document, so changes
are commands on its history, appear in the window at once and can be undone
there. Requests are handled on the GUI thread, one after the other.
"""

from __future__ import annotations

import base64
import os
import secrets
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from figscribe.assistant import endpoint
from figscribe.tools import Toolbox, ToolError, Workspace


class ToolServer(QObject):
    clients_changed = Signal(int)
    """Number of connected clients."""
    tool_called = Signal(str)
    """Name of a tool that was just run, for a status line."""

    def __init__(
        self, workspace: Callable[[], Workspace], parent: QObject | None = None
    ):
        super().__init__(parent)
        self._workspace = workspace
        self._server = QTcpServer(self)
        self._server.newConnection.connect(self._accept)
        self._buffers: dict[QTcpSocket, bytearray] = {}
        self.endpoint: endpoint.Endpoint | None = None

    @property
    def listening(self) -> bool:
        return self._server.isListening()

    def start(self) -> None:
        """Listen on localhost and publish where."""
        if self.listening:
            return
        if not self._server.listen(
            QHostAddress(QHostAddress.SpecialAddress.LocalHost), 0
        ):
            raise OSError(self._server.errorString())
        self.endpoint = endpoint.Endpoint(
            port=self._server.serverPort(), token=endpoint.new_token(), pid=os.getpid()
        )
        endpoint.publish(self.endpoint)

    def stop(self) -> None:
        if self.endpoint is not None:
            endpoint.withdraw(self.endpoint)
            self.endpoint = None
        for socket in list(self._buffers):
            socket.disconnectFromHost()
        self._server.close()

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        """Run one request; never raises."""
        token = message.get("token")
        if (
            self.endpoint is None
            or not isinstance(token, str)
            or not secrets.compare_digest(token, self.endpoint.token)
        ):
            return {"ok": False, "error": "not authorized"}
        name = message.get("tool")
        arguments = message.get("arguments") or {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return {"ok": False, "error": "a request needs a tool name and arguments"}
        try:
            result = Toolbox(self._workspace()).call(name, arguments)
        except ToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:  # a bug must not take the window down
            return {"ok": False, "error": f"internal error in {name}: {exc!r}"}
        self.tool_called.emit(name)
        return {"ok": True, "result": _wire(result)}

    # --- sockets ----------------------------------------------------------------

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._drop(s))
        self.clients_changed.emit(len(self._buffers))

    def _read(self, socket: QTcpSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer += bytes(socket.readAll())
        while b"\n" in buffer:
            line, _, rest = bytes(buffer).partition(b"\n")
            buffer[:] = rest
            try:
                response = self.handle(endpoint.decode(line))
            except ValueError as exc:
                response = {"ok": False, "error": f"malformed request: {exc}"}
            socket.write(endpoint.encode(response))
        if len(buffer) > endpoint.MAX_LINE:
            socket.write(endpoint.encode({"ok": False, "error": "request too large"}))
            socket.disconnectFromHost()

    def _drop(self, socket: QTcpSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()
        self.clients_changed.emit(len(self._buffers))


def _wire(result: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe: bytes (the preview image) travel as base64."""
    return {
        (f"{k}_base64" if isinstance(v, bytes) else k): (
            base64.b64encode(v).decode("ascii") if isinstance(v, bytes) else v
        )
        for k, v in result.items()
    }
