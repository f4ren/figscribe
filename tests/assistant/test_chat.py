"""The built-in chat: the tool loop, with a scripted model instead of the API."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from figscribe.assistant.chat import (
    MAX_ROUNDS,
    Chat,
    ChatError,
    tool_definitions,
)
from figscribe.gui import Document
from figscribe.gui.chatpanel import ChatPanel
from figscribe.tools import TOOLS, Toolbox


def text(value: str):
    return SimpleNamespace(type="text", text=value)


def use(name: str, arguments, uid: str = "t1"):
    return SimpleNamespace(type="tool_use", id=uid, name=name, input=arguments)


def message(*blocks, stop: str | None = None):
    if stop is None:
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


class ScriptedModel:
    """Answers with the given messages in turn, streaming their text."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen: list[list] = []

    def respond(self, messages, on_text):
        self.seen.append(list(messages))
        response = self.responses.pop(0)
        for block in response.content:
            if block.type == "text":
                on_text(block.text)
        return response


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


def _run(chat: Chat, document: Document) -> list[tuple]:
    """Drive the loop the way the GUI does; return the tool calls heard."""
    heard = []
    while True:
        response = chat.respond(lambda _: None)
        more = chat.handle(
            response,
            lambda name, args: Toolbox(document).call(name, args),
            lambda *call: heard.append(call),
        )
        if not more:
            return heard


def test_every_tool_is_offered_with_eager_input() -> None:
    definitions = tool_definitions()
    assert [d["name"] for d in definitions] == [spec.name for spec in TOOLS]
    assert all(d["eager_input_streaming"] for d in definitions)


def test_a_tool_round_changes_the_project(document: Document) -> None:
    figure = document.figure
    model = ScriptedModel(
        message(
            text("Renaming."),
            use("set_field", {"object_id": figure.id, "path": ["name"], "value": "B"}),
        ),
        message(text("Done.")),
    )
    chat = Chat(model)
    chat.ask("call it B")
    heard = _run(chat, document)
    assert document.figure.name == "B"
    assert document.history.undo_text == "Set name"
    assert heard == [
        ("set_field", {"object_id": figure.id, "path": ["name"], "value": "B"}, None)
    ]
    result = chat.messages[2]["content"][0]
    assert result["tool_use_id"] == "t1" and "is_error" not in result
    assert model.seen[1][-1]["role"] == "user"  # the result went back


def test_a_refused_tool_is_reported_to_the_model(document: Document) -> None:
    model = ScriptedModel(
        message(use("remove", {"object_id": "nope"})),
        message(text("That does not exist.")),
    )
    chat = Chat(model)
    chat.ask("remove nope")
    heard = _run(chat, document)
    result = chat.messages[2]["content"][0]
    assert result["is_error"] and "nope" in result["content"]
    assert heard[0][2] is not None
    assert not document.history.can_undo


def test_a_malformed_input_is_an_error_result(document: Document) -> None:
    model = ScriptedModel(message(use("remove", "not json")), message(text("Sorry.")))
    chat = Chat(model)
    chat.ask("x")
    _run(chat, document)
    assert chat.messages[2]["content"][0]["is_error"]


def test_the_preview_goes_back_as_an_image(document: Document) -> None:
    document.allow_preview = True
    model = ScriptedModel(
        message(use("render_preview", {})), message(text("Looks fine."))
    )
    chat = Chat(model)
    chat.ask("check it")
    _run(chat, document)
    block = chat.messages[2]["content"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


def test_stops_on_refusal_truncation_and_endless_loops(document: Document) -> None:
    chat = Chat(ScriptedModel(message(text("No."), stop="refusal")))
    chat.ask("x")
    with pytest.raises(ChatError, match="declined"):
        _run(chat, document)

    cut = message(use("get_project", {}), stop="max_tokens")
    chat = Chat(ScriptedModel(cut))
    chat.ask("x")
    with pytest.raises(ChatError, match="cut off"):
        _run(chat, document)

    endless = [message(use("get_project", {})) for _ in range(MAX_ROUNDS + 1)]
    chat = Chat(ScriptedModel(*endless))
    chat.ask("x")
    with pytest.raises(ChatError, match="too many"):
        _run(chat, document)


def test_pause_turn_continues(document: Document) -> None:
    chat = Chat(
        ScriptedModel(message(text("…"), stop="pause_turn"), message(text("ok")))
    )
    chat.ask("x")
    _run(chat, document)
    assert [m["role"] for m in chat.messages] == ["user", "assistant", "assistant"]


# --- the panel --------------------------------------------------------------


@pytest.fixture
def panel(qtbot, document: Document) -> ChatPanel:
    widget = ChatPanel(document)
    qtbot.addWidget(widget)
    return widget


def test_the_panel_runs_a_request(panel: ChatPanel, document: Document) -> None:
    figure = document.figure
    model = ScriptedModel(
        message(
            use(
                "set_field",
                {"object_id": figure.id, "path": ["width_mm"], "value": 175},
            )
        ),
        message(text("Now two columns wide.")),
    )
    panel.make_model = lambda key: model
    panel.input.setText("make it double column")
    panel.send()
    assert panel.busy
    panel.wait()
    assert not panel.busy and panel.send_button.isEnabled()
    assert document.figure.width_mm == 175
    shown = panel.transcript.toPlainText()
    assert "make it double column" in shown
    assert "→ set_field" in shown and "Now two columns wide." in shown


def test_missing_credentials_ask_for_a_key(panel: ChatPanel) -> None:
    def no_key(key):
        if key is None:
            raise ChatError("No valid API key. Set ANTHROPIC_API_KEY …")
        return ScriptedModel(message(text("Hello.")))

    panel.make_model = no_key
    panel.input.setText("hi")
    panel.send()
    assert "No valid API key" in panel.transcript.toPlainText()

    failing = ScriptedModel()
    failing.respond = lambda messages, on_text: (_ for _ in ()).throw(
        ChatError("No valid API key. Set ANTHROPIC_API_KEY …")
    )
    panel.make_model = lambda key: failing
    panel.input.setText("hi")
    panel.send()
    panel.wait()
    assert not panel.key.isHidden() and panel.chat is None

    panel.make_model = no_key
    panel.key.setText("sk-test")
    panel.input.setText("hi")
    panel.send()
    panel.wait()
    assert "Hello." in panel.transcript.toPlainText()


def test_a_new_document_starts_over(panel: ChatPanel) -> None:
    panel.make_model = lambda key: ScriptedModel(message(text("Hi.")))
    panel.input.setText("hello")
    panel.send()
    panel.wait()
    panel.set_document(Document())
    assert panel.chat is None and panel.transcript.toPlainText() == ""


def test_the_real_client_reports_a_refused_key(monkeypatch) -> None:
    """The SDK path, against a local server that refuses every request."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from figscribe.assistant.chat import ClaudeModel

    received = []

    class Refuse(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - http.server naming
            length = int(self.headers.get("content-length", 0))
            received.append(json.loads(self.rfile.read(length)))
            body = json.dumps(
                {
                    "type": "error",
                    "error": {
                        "type": "authentication_error",
                        "message": "invalid x-api-key",
                    },
                }
            ).encode()
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Refuse)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv(
            "ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}"
        )
        model = ClaudeModel(api_key="sk-wrong")
        with pytest.raises(ChatError, match="API key"):
            model.respond([{"role": "user", "content": "hi"}], lambda _: None)
    finally:
        server.shutdown()
    request = received[0]
    assert request["model"] == "claude-opus-5-5" and request["stream"] is True
    assert request["fallbacks"] == "default"
    assert {t["name"] for t in request["tools"]} == {spec.name for spec in TOOLS}
