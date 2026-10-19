"""MCP access: endpoint file, the application's tool server, `figscribe mcp`."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from figscribe.assistant import endpoint
from figscribe.assistant.mcpserver import NOT_RUNNING, forward, to_result
from figscribe.assistant.toolserver import ToolServer
from figscribe.gui import Document, MainWindow

pytest.importorskip("mcp")


@pytest.fixture(autouse=True)
def state_dir(tmp_path: Path, monkeypatch) -> Path:
    """Keep the endpoint file out of the user's real directory."""
    directory = tmp_path / "state"
    monkeypatch.setenv(endpoint.ENV_DIR, str(directory))
    return directory


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def server(qtbot, document: Document) -> ToolServer:
    tool_server = ToolServer(lambda: document)
    tool_server.start()
    yield tool_server
    tool_server.stop()


# --- the endpoint file -----------------------------------------------------------


def test_publish_and_withdraw(state_dir: Path) -> None:
    mine = endpoint.Endpoint(port=4242, token=endpoint.new_token(), pid=1)
    path = endpoint.publish(mine)
    assert endpoint.read() == mine
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600

    other = endpoint.Endpoint(port=1, token="someone else", pid=2)
    endpoint.withdraw(other)  # not ours: stays
    assert endpoint.read() == mine
    endpoint.withdraw(mine)
    assert endpoint.read() is None


def test_a_broken_endpoint_file_reads_as_none(state_dir: Path) -> None:
    state_dir.mkdir(parents=True)
    endpoint.endpoint_file().write_text("{not json", encoding="utf-8")
    assert endpoint.read() is None


# --- the tool server ------------------------------------------------------------


def _request(server: ToolServer, tool: str, **arguments) -> dict:
    return server.handle(
        {"token": server.endpoint.token, "tool": tool, "arguments": arguments}
    )


def test_requests_need_the_token(server: ToolServer) -> None:
    assert server.handle({"tool": "get_project", "arguments": {}}) == {
        "ok": False,
        "error": "not authorized",
    }
    assert server.handle({"token": "guess", "tool": "get_project"})["ok"] is False


def test_a_tool_call_changes_the_open_document(server, document, qtbot) -> None:
    figure = document.project.figures[0]
    with qtbot.waitSignal(document.changed):
        response = _request(
            server, "set_field", object_id=figure.id, path=["name"], value="Via MCP"
        )
    assert response["ok"] and response["result"]["undo_step"] == "Set name"
    assert document.figure.name == "Via MCP"
    assert document.history.can_undo


def test_refusals_and_bugs_come_back_as_errors(server, monkeypatch) -> None:
    response = _request(server, "set_field", object_id=None, path=["nope"], value=1)
    assert response == {"ok": False, "error": "Project has no field 'nope'"}

    from figscribe.tools import Toolbox

    def broken(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(Toolbox, "tool_get_schema", broken)
    response = _request(server, "get_schema")
    assert not response["ok"] and "internal error" in response["error"]


def test_the_preview_travels_as_base64(server, document) -> None:
    document.allow_preview = True
    result = _request(server, "render_preview")["result"]
    assert base64.b64decode(result["png_base64"]).startswith(b"\x89PNG")


def test_requests_over_the_socket(server, qtbot) -> None:
    """A real client on localhost, as `figscribe mcp` connects."""
    replies: list[dict] = []
    target = endpoint.read()

    def client() -> None:
        with socket.create_connection(("127.0.0.1", target.port)) as conn:
            for message in (
                {"token": target.token, "tool": "list_columns", "arguments": {}},
                {"token": "wrong", "tool": "list_columns", "arguments": {}},
            ):
                conn.sendall(endpoint.encode(message))
                replies.append(endpoint.decode(conn.makefile("rb").readline()))
            conn.sendall(b"not json\n")
            replies.append(endpoint.decode(conn.makefile("rb").readline()))

    thread = threading.Thread(target=client)
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=10_000)
    assert replies[0]["ok"] and len(replies[0]["result"]["columns"]) == 3
    assert replies[1] == {"ok": False, "error": "not authorized"}
    assert "malformed" in replies[2]["error"]


# --- figscribe mcp ----------------------------------------------------------------


def test_forward_without_a_running_figscribe() -> None:
    assert asyncio.run(forward("get_project", {})) == {
        "ok": False,
        "error": NOT_RUNNING,
    }


def test_results_become_mcp_content() -> None:
    ok = to_result({"ok": True, "result": {"id": "abc"}})
    assert not ok.is_error and json.loads(ok.content[0].text) == {"id": "abc"}

    error = to_result({"ok": False, "error": "no such field"})
    assert error.is_error and error.content[0].text == "no such field"

    png = base64.b64encode(b"\x89PNG...").decode()
    image = to_result({"ok": True, "result": {"png_base64": png}})
    assert (
        image.content[0].type == "image" and image.content[0].mime_type == "image/png"
    )
    assert len(image.content) == 1


def _run_mcp_client(state_dir: Path, calls: list[tuple[str, dict]], out: list) -> None:
    """Start `figscribe mcp` as a client would and make the calls."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def session() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "figscribe", "mcp"],
            env={**os.environ, endpoint.ENV_DIR: str(state_dir)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                out.append(await client.list_tools())
                for name, arguments in calls:
                    out.append(await client.call_tool(name, arguments))

    try:
        asyncio.run(session())
    except BaseException as exc:  # reported by the test, not lost in the thread
        out.append(exc)


def test_an_mcp_client_drives_the_window(qtbot, example: Path, state_dir: Path) -> None:
    window = MainWindow(Document.open(example))
    qtbot.addWidget(window)
    window.ask = lambda title, question: True
    window.mcp_action.trigger()
    assert window.tool_server.listening

    figure = window.document.figure
    out: list = []
    calls = [
        ("get_project", {}),
        ("set_field", {"object_id": figure.id, "path": ["name"], "value": "From MCP"}),
        ("set_field", {"object_id": figure.id, "path": ["dpi"], "value": "high"}),
    ]
    thread = threading.Thread(target=_run_mcp_client, args=(state_dir, calls, out))
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=60_000)

    assert not any(isinstance(item, BaseException) for item in out), out
    tools, project, changed, refused = out
    assert "apply_changes" in {tool.name for tool in tools.tools}
    assert (
        json.loads(project.content[0].text)["project"]["figures"][0]["id"] == figure.id
    )
    assert not changed.is_error
    assert refused.is_error and "valid number" in refused.content[0].text
    assert window.document.figure.name == "From MCP"
    assert window.undo_action.text() == "&Undo Set name"


def test_figscribe_mcp_reports_a_closed_application(qtbot, state_dir: Path) -> None:
    out: list = []
    thread = threading.Thread(
        target=_run_mcp_client, args=(state_dir, [("get_project", {})], out)
    )
    thread.start()
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=60_000)
    assert not any(isinstance(item, BaseException) for item in out), out
    result = out[1]
    assert result.is_error and "start figscribe" in result.content[0].text


# --- the window's switches --------------------------------------------------------


def test_the_mcp_switch_publishes_and_withdraws(qtbot, state_dir: Path) -> None:
    window = MainWindow(Document())
    qtbot.addWidget(window)
    window.mcp_action.trigger()
    assert endpoint.read() == window.tool_server.endpoint
    assert "MCP" in window._mcp_status.text()
    window.mcp_action.trigger()
    assert endpoint.read() is None and not window.tool_server.listening


def test_closing_the_window_withdraws_the_endpoint(qtbot, state_dir: Path) -> None:
    window = MainWindow(Document())
    qtbot.addWidget(window)
    window.mcp_action.trigger()
    window.close()
    assert endpoint.read() is None


def test_the_preview_permission_follows_new_documents(qtbot) -> None:
    window = MainWindow(Document())
    qtbot.addWidget(window)
    window.ask = lambda title, question: True
    window.preview_action.trigger()
    assert window.document.allow_preview
    window.new_project()
    assert window.document.allow_preview


def test_switches_are_remembered(qtbot, tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(Document(), settings=settings)
    qtbot.addWidget(window)
    window.preview_action.trigger()
    window.mcp_action.trigger()
    window.close()

    again = MainWindow(Document(), settings=settings)
    qtbot.addWidget(again)
    assert again.preview_action.isChecked() and again.document.allow_preview
    assert again.tool_server.listening
    again.close()


# --- found while hardening -----------------------------------------------------


async def _serve_once(reply: bytes | None, delay: float = 0.0):
    """A stand-in for figscribe that answers one request with `reply`."""

    async def handle(reader, writer):
        await reader.readline()
        await asyncio.sleep(delay)
        if reply is not None:
            writer.write(reply)
            await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    endpoint.publish(endpoint.Endpoint(port=port, token="t", pid=os.getpid()))
    return server


@pytest.mark.parametrize(
    ("reply", "message"),
    [(None, "closed the connection"), (b"not json\n", "lost the connection")],
)
def test_forward_turns_a_broken_answer_into_an_error(reply, message) -> None:
    async def run():
        server = await _serve_once(reply)
        async with server:
            return await forward("get_project", {})

    response = asyncio.run(run())
    assert response["ok"] is False and message in response["error"]


def test_forward_gives_up_after_the_timeout(monkeypatch) -> None:
    import figscribe.assistant.mcpserver as bridge

    monkeypatch.setattr(bridge, "TIMEOUT", 0.2)

    async def run():
        server = await _serve_once(b'{"ok": true}\n', delay=2.0)
        async with server:
            return await forward("get_project", {})

    response = asyncio.run(run())
    assert "did not answer" in response["error"]


def test_a_stale_endpoint_file_reads_as_not_running() -> None:
    with socket.socket() as s:  # a port nobody listens on once closed
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    endpoint.publish(endpoint.Endpoint(port=port, token="t", pid=1))
    assert asyncio.run(forward("get_project", {})) == {
        "ok": False,
        "error": NOT_RUNNING,
    }


def test_no_listening_without_the_endpoint_file(qtbot, document, monkeypatch) -> None:
    def fail(_):
        raise PermissionError("read-only")

    monkeypatch.setattr(endpoint, "publish", fail)
    tool_server = ToolServer(lambda: document)
    with pytest.raises(PermissionError):
        tool_server.start()
    assert not tool_server.listening and tool_server.endpoint is None


@pytest.mark.parametrize(
    ("argument", "expected"),
    [("--help", "usage: figscribe"), ("--version", "figscribe 0.")],
)
def test_command_line_help_and_version(argument, expected) -> None:
    import subprocess

    out = subprocess.run(
        [sys.executable, "-m", "figscribe", argument],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.startswith(expected)
