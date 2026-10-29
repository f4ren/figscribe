"""The built-in chat: the tool loop with a scripted model, and both API paths
against local fake servers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from figscribe.assistant.chat import (
    MAX_ROUNDS,
    Chat,
    ChatError,
    ClaudeModel,
    OpenAIModel,
    Provider,
    Reply,
    ToolCall,
    ToolResult,
    _anthropic_messages,
    list_models,
    tool_definitions,
)
from figscribe.gui import Document
from figscribe.gui.chatpanel import ChatPanel
from figscribe.tools import TOOLS, Toolbox

from .fakeserver import chunk, json_reply, serve, sse


def call(name: str, arguments, uid: str = "t1") -> ToolCall:
    return ToolCall(uid, name, arguments, json.dumps(arguments))


def reply(text: str = "", *calls: ToolCall, stop: str | None = None) -> Reply:
    if stop is None:
        stop = "tool_use" if calls else "end"
    return Reply(text, list(calls), stop)


class ScriptedModel:
    """Answers with the given replies in turn, streaming their text."""

    name = "scripted"

    def __init__(self, *replies: Reply):
        self.replies = list(replies)
        self.seen: list[list] = []

    def respond(self, turns, on_text):
        self.seen.append(list(turns))
        answer = self.replies.pop(0)
        if answer.text:
            on_text(answer.text)
        return answer


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


def _run(chat: Chat, document: Document) -> list[tuple]:
    """Drive the loop the way the GUI does; return the tool calls heard."""
    heard = []
    while True:
        answer = chat.respond(lambda _: None)
        more = chat.handle(
            answer,
            lambda name, args: Toolbox(document).call(name, args),
            lambda *heard_call: heard.append(heard_call),
        )
        if not more:
            return heard


def test_every_tool_is_offered_with_eager_input() -> None:
    definitions = tool_definitions()
    assert [d["name"] for d in definitions] == [spec.name for spec in TOOLS]
    assert all(d["eager_input_streaming"] for d in definitions)
    blind = {d["name"] for d in tool_definitions(vision=False)}
    assert "render_preview" not in blind and "get_project" in blind


def test_a_tool_round_changes_the_project(document: Document) -> None:
    figure = document.figure
    arguments = {"object_id": figure.id, "path": ["name"], "value": "B"}
    model = ScriptedModel(
        reply("Renaming.", call("set_field", arguments)), reply("Done.")
    )
    chat = Chat(model)
    chat.ask("call it B")
    heard = _run(chat, document)
    assert document.figure.name == "B"
    assert document.history.undo_text == "Set name"
    assert heard == [("set_field", arguments, None)]
    [result] = chat.turns[2]
    assert result.id == "t1" and not result.is_error
    assert model.seen[1][-1] == chat.turns[2]  # the result went back


def test_a_refused_tool_is_reported_to_the_model(document: Document) -> None:
    model = ScriptedModel(
        reply("", call("remove", {"object_id": "nope"})),
        reply("That does not exist."),
    )
    chat = Chat(model)
    chat.ask("remove nope")
    heard = _run(chat, document)
    [result] = chat.turns[2]
    assert result.is_error and "nope" in result.content
    assert heard[0][2] is not None
    assert not document.history.can_undo


def test_a_malformed_input_is_an_error_result(document: Document) -> None:
    garbled = ToolCall("t1", "remove", '{"object_id": ', '{"object_id": ')
    model = ScriptedModel(reply("", garbled), reply("Sorry."))
    chat = Chat(model)
    chat.ask("x")
    _run(chat, document)
    [result] = chat.turns[2]
    assert result.is_error and "JSON object" in result.content


def test_the_preview_goes_back_as_an_image(document: Document) -> None:
    document.allow_preview = True
    model = ScriptedModel(reply("", call("render_preview", {})), reply("Looks fine."))
    chat = Chat(model)
    chat.ask("check it")
    _run(chat, document)
    [result] = chat.turns[2]
    assert result.image is not None and result.image.startswith(b"\x89PNG")
    [message] = _anthropic_messages([chat.turns[2]])
    block = message["content"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/png"


def test_stops_on_refusal_truncation_and_endless_loops(document: Document) -> None:
    chat = Chat(ScriptedModel(reply("No.", stop="refusal")))
    chat.ask("x")
    with pytest.raises(ChatError, match="declined"):
        _run(chat, document)

    chat = Chat(ScriptedModel(reply("", call("get_project", {}), stop="max_tokens")))
    chat.ask("x")
    with pytest.raises(ChatError, match="cut off"):
        _run(chat, document)

    endless = [reply("", call("get_project", {})) for _ in range(MAX_ROUNDS + 1)]
    chat = Chat(ScriptedModel(*endless))
    chat.ask("x")
    with pytest.raises(ChatError, match="too many"):
        _run(chat, document)


def test_pause_turn_continues(document: Document) -> None:
    chat = Chat(ScriptedModel(reply("…", stop="pause"), reply("ok")))
    chat.ask("x")
    _run(chat, document)
    assert [type(t).__name__ for t in chat.turns] == ["str", "Reply", "Reply"]


# --- local fake servers -----------------------------------------------------------


def test_an_openai_compatible_server_runs_the_tools(document: Document) -> None:
    """A local server as LM Studio or Ollama would answer: the tool call
    streamed in pieces, then text."""
    pytest.importorskip("openai")
    figure = document.figure
    arguments = json.dumps({"object_id": figure.id, "path": ["name"], "value": "B"})
    first = sse(
        chunk({"role": "assistant", "content": "Renaming. "}),
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_7",
                        "type": "function",
                        "function": {"name": "set_field", "arguments": arguments[:20]},
                    }
                ]
            }
        ),
        chunk(
            {"tool_calls": [{"index": 0, "function": {"arguments": arguments[20:]}}]}
        ),
        chunk({}, "tool_calls"),
    )
    second = sse(chunk({"content": "Done."}), chunk({}, "stop"))
    answers = [first, second]

    def answer(method, path, body):
        return answers.pop(0)

    with serve(answer) as (url, requests):
        provider = Provider("openai", "qwen-local", f"{url}/v1", vision=False)
        chat = Chat(OpenAIModel(provider))
        chat.ask("call it B")
        streamed = []
        while True:
            answer_ = chat.respond(streamed.append)
            if not chat.handle(answer_, lambda n, a: Toolbox(document).call(n, a)):
                break
    assert document.figure.name == "B"
    assert "".join(streamed) == "Renaming. Done."

    _, path, body = requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "qwen-local"
    assert body["stream"] is True and body["messages"][0]["role"] == "system"
    names = {t["function"]["name"] for t in body["tools"]}
    assert "render_preview" not in names  # this model cannot see
    messages = requests[1][2]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2]["tool_calls"][0]["function"]["arguments"] == arguments
    assert messages[3]["tool_call_id"] == "call_7"


def test_a_preview_goes_to_a_seeing_model_as_the_users_image() -> None:
    from figscribe.assistant.chat import _openai_messages

    turns = [
        "check it",
        reply("", call("render_preview", {}, "c1")),
        [ToolResult("c1", "", image=b"\x89PNG...")],
    ]
    messages = _openai_messages(turns, vision=True)
    assert messages[3]["role"] == "tool" and "image follows" in messages[3]["content"]
    image = messages[4]["content"][1]["image_url"]["url"]
    assert messages[4]["role"] == "user"
    assert image.startswith("data:image/png;base64,")


def test_openai_errors_are_explained() -> None:
    pytest.importorskip("openai")

    def refuse(method, path, body):
        if path.endswith("/models"):
            return json_reply(
                200, {"object": "list", "data": [{"id": "b"}, {"id": "a"}]}
            )
        return json_reply(404, {"error": {"message": "model not found", "type": "x"}})

    with serve(refuse) as (url, _):
        provider = Provider("openai", "nope", f"{url}/v1")
        assert list_models(provider) == ["a", "b"]
        with pytest.raises(ChatError, match="has no model 'nope'"):
            OpenAIModel(provider).respond(["hi"], lambda _: None)

    provider = Provider("openai", "m", "http://127.0.0.1:9/v1")
    model = OpenAIModel(provider)
    model.client = model.client.with_options(max_retries=0)
    with pytest.raises(ChatError, match="Cannot reach http://127.0.0.1:9/v1"):
        model.respond(["hi"], lambda _: None)
    with pytest.raises(ChatError, match="Choose a model"):
        OpenAIModel(Provider("openai", "", "http://x/v1")).respond(["hi"], print)


GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_gemini_takes_its_own_key_from_the_environment(monkeypatch) -> None:
    """An OpenAI key is never sent to Google."""
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gemini = Provider("openai", "gemini-2.5-flash", GEMINI)
    assert OpenAIModel(gemini).client.api_key != "sk-openai"
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    assert OpenAIModel(gemini).client.api_key == "gemini-key"
    assert OpenAIModel(gemini, "typed").client.api_key == "typed"
    local = Provider("openai", "m", "http://localhost:1234/v1")
    assert OpenAIModel(local).client.api_key == "sk-openai"


def test_geminis_thought_signature_goes_back_with_its_call(document: Document) -> None:
    """Gemini 3 refuses the next round without it: each call comes whole in
    its own chunk, without an index, the first one signed."""
    pytest.importorskip("openai")
    signed = {"google": {"thought_signature": "c2lnbmVk"}}

    def tool_call(uid: str, extra: dict | None = None) -> dict:
        part = {
            "id": uid,
            "type": "function",
            "function": {"name": "get_project", "arguments": "{}"},
        }
        return part | ({"extra_content": extra} if extra else {})

    first = sse(
        chunk({"role": "assistant", "tool_calls": [tool_call("a", signed)]}),
        chunk({"role": "assistant", "tool_calls": [tool_call("b")]}),
        chunk({"role": "assistant"}, "stop"),
    )
    answers = [first, sse(chunk({"content": "Done."}), chunk({}, "stop"))]

    with serve(lambda method, path, body: answers.pop(0)) as (url, requests):
        chat = Chat(OpenAIModel(Provider("openai", "gemini-3.5-flash", f"{url}/v1")))
        chat.ask("what is there?")
        while chat.handle(
            chat.respond(lambda _: None), lambda n, a: Toolbox(document).call(n, a)
        ):
            pass
    calls = requests[1][2]["messages"][2]["tool_calls"]
    assert [c["id"] for c in calls] == ["a", "b"]
    assert calls[0]["extra_content"] == signed
    assert "extra_content" not in calls[1]


@pytest.mark.parametrize(
    ("limit", "wait", "expected"),
    [
        (
            "requests per minute",
            "30.895273533s",
            ["in 31 s", "a few requests a minute"],
        ),
        ("requests per day", "21h21m28.693978504s", ["in 22 h", "daily limit"]),
        ("requests per day", "12m3.5s", ["in 13 min", "daily limit"]),
    ],
)
def test_a_free_tier_limit_says_how_long_to_wait(limit, wait, expected) -> None:
    """Gemini says it in its text, as it does on its free tier."""
    pytest.importorskip("openai")
    message = (
        "You exceeded your current quota. * Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        f"limit: 20, description: Generate content {limit} limit exceeded on "
        f"Free Tier.\nPlease retry in {wait}."
    )

    def refuse(method, path, body):
        return json_reply(429, [{"error": {"code": 429, "message": message}}])

    with serve(refuse) as (url, _):
        model = OpenAIModel(Provider("openai", "gemini-3.5-flash", f"{url}/v1"))
        model.client = model.client.with_options(max_retries=0)
        with pytest.raises(ChatError) as error:
            model.respond(["hi"], lambda _: None)
    for part in expected:
        assert part in str(error.value)


def test_a_refused_gemini_key_names_its_variable() -> None:
    pytest.importorskip("openai")

    def refuse(method, path, body):
        return json_reply(401, {"error": {"message": "API key not valid"}})

    with serve(refuse) as (url, _):
        model = OpenAIModel(Provider("openai", "gemini-2.5-flash", f"{url}/v1"))
        model.key_variable = "GEMINI_API_KEY"
        with pytest.raises(ChatError, match="Set GEMINI_API_KEY"):
            model.respond(["hi"], lambda _: None)


def test_model_names_drop_googles_prefix() -> None:
    pytest.importorskip("openai")

    def models(method, path, body):
        data = [{"id": "models/gemini-2.5-pro"}, {"id": "models/gemini-2.5-flash"}]
        return json_reply(200, {"object": "list", "data": data})

    with serve(models) as (url, _):
        provider = Provider("openai", "", f"{url}/v1beta/openai/")
        assert list_models(provider) == ["gemini-2.5-flash", "gemini-2.5-pro"]


def test_the_claude_client_reports_a_refused_key(monkeypatch) -> None:
    """The SDK path, against a local server that refuses every request."""
    pytest.importorskip("anthropic")

    def refuse(method, path, body):
        error = {"type": "authentication_error", "message": "invalid x-api-key"}
        return json_reply(401, {"type": "error", "error": error})

    with serve(refuse) as (url, requests):
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        with pytest.raises(ChatError, match="API key"):
            ClaudeModel(api_key="sk-wrong").respond(["hi"], lambda _: None)
        with pytest.raises(ChatError, match="API key"):
            ClaudeModel("sk-wrong", "claude-haiku-5-5").respond(["hi"], lambda _: None)
    opus, haiku = requests[0][2], requests[-1][2]
    assert opus["model"] == "claude-opus-5-5" and opus["stream"] is True
    assert opus["fallbacks"] == "default"
    assert opus["messages"] == [{"role": "user", "content": "hi"}]
    assert {t["name"] for t in opus["tools"]} == {spec.name for spec in TOOLS}
    assert haiku["model"] == "claude-haiku-5-5" and "fallbacks" not in haiku


def test_the_claude_client_asks_for_a_key_when_there_is_none(
    monkeypatch, tmp_path: Path
) -> None:
    """No key, no token, no `ant auth login` profile: the SDK fails before any
    request, with a TypeError of its own."""
    pytest.importorskip("anthropic")
    import os

    for name in list(os.environ):
        if name.startswith("ANTHROPIC_"):
            monkeypatch.delenv(name)
    for name in ("HOME", "USERPROFILE", "APPDATA"):  # where profiles are kept
        monkeypatch.setenv(name, str(tmp_path))
    with pytest.raises(ChatError, match="No valid API key"):
        ClaudeModel().list_models()
    with pytest.raises(ChatError, match="No valid API key"):
        ClaudeModel().respond(["hi"], lambda _: None)


# --- the panel --------------------------------------------------------------


@pytest.fixture
def panel(qtbot, document: Document) -> ChatPanel:
    widget = ChatPanel(document)
    qtbot.addWidget(widget)
    return widget


def test_the_panel_runs_a_request(panel: ChatPanel, document: Document) -> None:
    figure = document.figure
    model = ScriptedModel(
        reply(
            "",
            call(
                "set_field",
                {"object_id": figure.id, "path": ["width_mm"], "value": 175},
            ),
        ),
        reply("Now two columns wide."),
    )
    panel.make_model = lambda provider, key: model
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
    def no_key(provider, key):
        if key is None:
            raise ChatError("No valid API key. Set ANTHROPIC_API_KEY …")
        return ScriptedModel(reply("Hello."))

    panel.make_model = no_key
    panel.input.setText("hi")
    panel.send()
    assert "No valid API key" in panel.transcript.toPlainText()

    failing = ScriptedModel()
    failing.respond = lambda turns, on_text: (_ for _ in ()).throw(
        ChatError("No valid API key. Set ANTHROPIC_API_KEY …")
    )
    panel.make_model = lambda provider, key: failing
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
    panel.make_model = lambda provider, key: ScriptedModel(reply("Hi."))
    panel.input.setText("hello")
    panel.send()
    panel.wait()
    panel.set_document(Document())
    assert panel.chat is None and panel.transcript.toPlainText() == ""


def test_choosing_another_model(panel: ChatPanel) -> None:
    from figscribe.gui.assistantdialog import AssistantDialog

    chosen = []
    panel.provider_changed.connect(chosen.append)
    made = []
    panel.make_model = lambda provider, key: (
        made.append((provider, key)) or (ScriptedModel(reply("Hi.")))
    )

    def pick_lm_studio(dialog: AssistantDialog) -> bool:
        dialog.kind.setCurrentIndex(dialog.kind.findData("openai"))
        dialog.server.setCurrentText("LM Studio")
        dialog.list_models = lambda provider, key: ["qwen3-30b", "gpt-oss-20b"]
        dialog.load.click()
        dialog.model.setCurrentText("qwen3-30b")
        return True

    panel.run_dialog = pick_lm_studio
    panel.choose_model()
    provider = Provider("openai", "qwen3-30b", "http://localhost:1234/v1", False)
    assert chosen == [provider] and panel.provider == provider
    assert panel.model_button.text() == "qwen3-30b"
    assert "Now talking to qwen3-30b" in panel.transcript.toPlainText()
    panel.input.setText("hi")
    panel.send()
    panel.wait()
    assert made == [(provider, None)]


def test_the_dialog_reports_an_unreachable_server(qtbot) -> None:
    from figscribe.gui.assistantdialog import AssistantDialog

    dialog = AssistantDialog(Provider("openai", "", "http://localhost:11434/v1", False))
    qtbot.addWidget(dialog)
    assert dialog.server.currentText() == "Ollama"
    assert "not needed" in dialog.key.placeholderText()

    def unreachable(provider, key):
        raise ChatError(f"Cannot reach {provider.base_url}. Is the server running?")

    dialog.list_models = unreachable
    dialog.load.click()
    assert "Cannot reach http://localhost:11434/v1" in dialog.status.text()
    dialog.kind.setCurrentIndex(dialog.kind.findData("anthropic"))
    assert dialog.provider() == Provider()  # Claude, with the default model


def test_choosing_gemini_in_the_dialog(qtbot) -> None:
    from figscribe.gui.assistantdialog import AssistantDialog

    dialog = AssistantDialog(Provider("openai", "", "http://localhost:11434/v1", False))
    qtbot.addWidget(dialog)
    dialog.server.setCurrentText("Google Gemini")
    assert dialog.url.text() == GEMINI
    assert dialog.vision.isChecked()
    assert "GEMINI_API_KEY" in dialog.key.placeholderText()
    dialog.server.setCurrentText("ChatGPT (OpenAI)")
    assert "OPENAI_API_KEY" in dialog.key.placeholderText()


def test_the_window_remembers_the_model_but_never_the_key(qtbot, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from figscribe.gui import MainWindow

    path = tmp_path / "settings.ini"
    settings = QSettings(str(path), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    assert window.chat.provider == Provider()
    provider = Provider("openai", "gpt-oss-20b", "http://localhost:1234/v1", False)
    window.chat.key.setText("sk-secret")
    window.chat.set_provider(provider)
    settings.sync()
    assert "sk-secret" not in path.read_text()
    again = MainWindow(settings=QSettings(str(path), QSettings.Format.IniFormat))
    qtbot.addWidget(again)
    assert again.chat.provider == provider


def test_every_field_path_in_the_prompt_exists() -> None:
    """The cheat sheet for smaller models must not send them astray."""
    import re

    from figscribe.assistant.chat import SYSTEM
    from figscribe.model import Axes, ErrorbarPlot, Figure, LinePlot

    def exists(model, path: str) -> bool:
        for part in path.split("."):
            fields = getattr(model, "model_fields", {})
            if part not in fields:
                return False
            annotation = fields[part].annotation
            options = [
                a for a in getattr(annotation, "__args__", ()) if a is not type(None)
            ]
            model = options[0] if len(options) == 1 else annotation
        return True

    paths = re.findall(r"`([a-z_.]+)`", SYSTEM)
    assert len(paths) >= 15
    owners = (Figure, Axes, LinePlot, ErrorbarPlot)
    missing = [p for p in paths if not any(exists(m, p) for m in owners)]
    assert missing == []


def test_a_refusal_in_a_list_keeps_its_message() -> None:
    """Gemini sends its errors as a list; openai from 3.38 then says only
    "Error code: 400", and the reason is in the body."""
    pytest.importorskip("openai")

    def refuse(method, path, body):
        error = {"code": 400, "message": "Function call is missing a thought."}
        return json_reply(400, [{"error": error}])

    with serve(refuse) as (url, _):
        model = OpenAIModel(Provider("openai", "gemini-3.5-flash", f"{url}/v1"))
        model.client = model.client.with_options(max_retries=0)
        with pytest.raises(ChatError) as error:
            model.respond(["hi"], lambda _: None)
    assert "missing a thought" in str(error.value)
