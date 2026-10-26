"""The built-in chat: a language model changes the open project through
figscribe's tools.

The same tools as for MCP clients (`figscribe.tools`), so a change asked for
in the chat is a command like any other: shown at once, undoable. This module
holds the conversation and the tool loop and knows nothing of Qt; the GUI
calls `respond` in a worker thread and `handle` on its own thread, where the
tools may touch the document.

The conversation is kept in a provider-neutral form (user text, `Reply`,
lists of `ToolResult`); each `Model` translates it to its own API. Claude is
reached through the Anthropic SDK, everything else (ChatGPT, LM Studio,
Ollama, vLLM, …) through the OpenAI-compatible chat completions API.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from figscribe.tools import TOOLS

MODEL = "claude-opus-5-5"
CLAUDE_MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]
"""Offered in the settings before the server's own list is loaded."""
FALLBACK_MODELS = {
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
}
"""Claude models that take the server-side refusal fallback."""
MAX_TOKENS = 64000
MAX_ROUNDS = 25
"""Tool rounds per request, so a confused model cannot loop forever."""
VISION_TOOLS = {"render_preview"}
"""Tools whose answer is an image; offered only to models that can see."""

SYSTEM = """\
You work inside figscribe, a desktop application for scientific figures in \
Matplotlib. The user sees the figure and asks you to change it; you change \
the open project through the tools. Every change appears in the window at \
once and can be undone there.

Read the project with get_project before changing it, and again when you \
need fresh ids. Prefer apply_changes for several related changes, so they \
are one undo step. Data values are never shown to you, only file and column \
names; render_preview shows the figure if the user allowed it. Sizes are in \
millimetres and points, as a journal states them.

Answer briefly in the user's language: what you changed, or why you could \
not. Ask when the request is ambiguous instead of guessing.

Common set_field paths (get_schema has all of them):
- figure: `width_mm`, `height_mm`, `font_size`, `layout.share_x` ("none", \
"col", "all"), `layout.share_y` ("none", "row", "all"), `tick_direction` \
("in", "out", "inout"), `ticks_all_sides`, `frame_width`, `tick_width`, \
`tick_length`, `minor_tick_width`, `minor_tick_length` (all in pt), \
`panel_labels` (letters (a), (b) on the panels: {"style": "(a)", "bold": \
false}; null removes them)
- panel (axes): `title`, `grid`, `grid_color`, `grid_linewidth`, \
`grid_linestyle`, `x.label`, `x.unit`, \
`x.scale` ("linear", "log", "symlog"), `x.limits` ([min, max]), `x.major_step`, \
`x.minor_divisions` (4 minor ticks between majors = 5), `x.prefix` ("k" \
shows Hz values as kHz; limits and steps stay in Hz), the same for `y`, \
`legend.location` ("upper left", "lower right", …), `legend.frame`, \
`legend.visible`, `y_right` (an axis object such as {"label": "dU"}; null \
removes it)
- plot: `color`, `label` (legend entry), `marker`, `markersize`, \
`linestyle`, `linewidth`, `capsize`, `axis` ("left" or "right")
New plots: insert into a panel's "artists" with "kind" line, scatter, \
errorbar, histogram or annotation; columns are {"source": id, "column": \
name}. A line across the panel at a value: "kind" refline with "at" and \
"orientation" ("vertical" at an x value, "horizontal" at a y value); a \
shaded range: "kind" span with "start", "end" and "orientation". New \
panels: add_panel, then insert into the id it returns. A fit with its \
residual panel: fit with "residuals": true."""


class ChatError(Exception):
    """The request could not be answered; the message says why, for the user."""


# --- the conversation, independent of the provider ----------------------------


@dataclass
class ToolCall:
    id: str
    name: str
    input: Any
    """The parsed arguments; anything but a dict is refused as malformed."""
    raw: str = ""
    """The arguments as the model wrote them, echoed back unchanged."""
    extra: dict | None = None
    """What the server attached to the call and wants back unchanged, such
    as Gemini's thought signature."""


@dataclass
class Reply:
    """One model turn."""

    text: str
    calls: list[ToolCall] = field(default_factory=list)
    stop: Literal["end", "tool_use", "pause", "refusal", "max_tokens"] = "end"
    raw: Any = None
    """The provider's own record of the turn, for echoing it back."""


@dataclass
class ToolResult:
    id: str
    content: str
    image: bytes | None = None
    """A PNG instead of text, e.g. from render_preview."""
    is_error: bool = False


Turn = str | Reply | list[ToolResult]
"""User text, a model turn, or the results of that turn's tool calls."""


class Model(Protocol):
    name: str
    """Shown to the user, e.g. "claude-opus-5-5"."""

    def respond(self, turns: list[Turn], on_text: Callable[[str], None]) -> Reply:
        """One model turn: stream its text to `on_text`, return the reply."""
        ...


@dataclass(frozen=True)
class Provider:
    """Which model the chat talks to; kept in the user's settings, without
    any API key."""

    kind: Literal["anthropic", "openai"] = "anthropic"
    model: str = MODEL
    base_url: str | None = None
    """For "openai": the server, e.g. http://localhost:1234/v1 for LM Studio."""
    vision: bool = True
    """Whether the model reads images; without, render_preview is not offered."""

    @property
    def label(self) -> str:
        return self.model or "(no model chosen)"


SERVERS = {
    "ChatGPT (OpenAI)": "https://api.openai.com/v1",
    "Google Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "LM Studio": "http://localhost:1234/v1",
    "Ollama": "http://localhost:11434/v1",
}
"""OpenAI-compatible servers offered by name; any other URL works too."""

SEEING_SERVERS = {SERVERS["ChatGPT (OpenAI)"], SERVERS["Google Gemini"]}
"""Servers whose models read images; most local models do not."""

KEY_VARIABLES = {SERVERS["Google Gemini"]: "GEMINI_API_KEY"}
"""Where the key for a server comes from when none is entered; any other
server takes OPENAI_API_KEY."""


def key_variable(base_url: str | None) -> str:
    return KEY_VARIABLES.get(base_url or "", "OPENAI_API_KEY")


def make_model(provider: Provider, api_key: str | None = None) -> Model:
    if provider.kind == "anthropic":
        return ClaudeModel(api_key, provider.model)
    return OpenAIModel(provider, api_key)


def list_models(provider: Provider, api_key: str | None = None) -> list[str]:
    """The models the provider's server offers, by id."""
    return make_model(provider, api_key).list_models()


def tool_definitions(vision: bool = True) -> list[dict[str, Any]]:
    """The tools in Anthropic's format."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "eager_input_streaming": True,
        }
        for spec in TOOLS
        if vision or spec.name not in VISION_TOOLS
    ]


# --- Claude -------------------------------------------------------------------


NO_KEY = (
    "No valid API key. Set ANTHROPIC_API_KEY, sign in with `ant auth login`, "
    "or enter a key in the chat."
)


class ClaudeModel:
    """Claude through the Anthropic API.

    Credentials come from where the SDK looks for them (ANTHROPIC_API_KEY,
    or a profile from `ant auth login`) unless a key is given.
    """

    def __init__(self, api_key: str | None = None, model: str = MODEL):
        try:
            import anthropic
        except ImportError as exc:
            raise ChatError(
                'The chat needs the Anthropic SDK: pip install "figscribe[chat]"'
            ) from exc
        self._anthropic = anthropic
        self.client = (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )
        self.name = model
        self.tools = tool_definitions()

    def respond(self, turns: list[Turn], on_text: Callable[[str], None]) -> Reply:
        options: dict[str, Any] = {}
        if self.name in FALLBACK_MODELS:
            # On a safety decline the API answers with a fallback model, so the
            # user still gets an answer; the fallback blocks are echoed back.
            options = {
                "betas": ["server-side-fallback-2026-07-01"],
                "fallbacks": "default",
            }
        with self._errors():
            with self.client.beta.messages.stream(
                model=self.name,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                tools=self.tools,
                messages=_anthropic_messages(turns),
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                **options,
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        on_text(event.text)
                message = stream.get_final_message()
        return _anthropic_reply(message)

    def list_models(self) -> list[str]:
        with self._errors():
            return [m.id for m in self.client.models.list()]

    @contextmanager
    def _errors(self):
        anthropic = self._anthropic
        translate = _Translate(
            {
                anthropic.AuthenticationError: NO_KEY,
                anthropic.NotFoundError: f"The model {self.name!r} does not exist; "
                "choose another in the assistant settings.",
                anthropic.RateLimitError: "Too many requests just now; try again "
                "shortly.",
                anthropic.APIConnectionError: "Cannot reach the Anthropic API.",
                anthropic.APIStatusError: "The API refused the request: {message}",
            }
        )
        try:
            with translate:
                yield
        except TypeError as exc:
            # Without any credentials the SDK fails when it builds the first
            # request, before there is an API error to translate.
            if "authentication method" not in str(exc):
                raise
            raise ChatError(NO_KEY) from exc


_ANTHROPIC_STOPS = {
    "tool_use": "tool_use",
    "pause_turn": "pause",
    "refusal": "refusal",
    "max_tokens": "max_tokens",
}


def _anthropic_reply(message) -> Reply:
    calls = [
        ToolCall(b.id, b.name, b.input) for b in message.content if b.type == "tool_use"
    ]
    return Reply(
        text="".join(b.text for b in message.content if b.type == "text"),
        calls=calls,
        stop=_ANTHROPIC_STOPS.get(message.stop_reason, "end"),
        raw=message.content,
    )


def _anthropic_messages(turns: list[Turn]) -> list[dict]:
    messages = []
    for turn in turns:
        if isinstance(turn, str):
            messages.append({"role": "user", "content": turn})
        elif isinstance(turn, Reply):
            messages.append({"role": "assistant", "content": turn.raw})
        else:
            messages.append(
                {"role": "user", "content": [_anthropic_result(r) for r in turn]}
            )
    return messages


def _anthropic_result(result: ToolResult) -> dict:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": result.id}
    if result.image is not None:
        block["content"] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": _b64(result.image),
                },
            }
        ]
    else:
        block["content"] = result.content
    if result.is_error:
        block["is_error"] = True
    return block


# --- OpenAI-compatible servers --------------------------------------------------


class OpenAIModel:
    """Any server with the OpenAI chat completions API: ChatGPT, Gemini, or a
    local model in LM Studio, Ollama, vLLM, llama.cpp.

    The key is the given one, else the server's variable (GEMINI_API_KEY for
    Gemini, OPENAI_API_KEY for any other); local servers need none.
    """

    def __init__(self, provider: Provider, api_key: str | None = None):
        try:
            import openai
        except ImportError as exc:
            raise ChatError(
                'This server needs the OpenAI SDK: pip install "figscribe[chat]"'
            ) from exc
        self._openai = openai
        self.provider = provider
        self.name = provider.model
        self.key_variable = key_variable(provider.base_url)
        key = api_key or os.environ.get(self.key_variable) or "not-needed"
        self.client = openai.OpenAI(api_key=key, base_url=provider.base_url)
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": d["name"],
                    "description": d["description"],
                    "parameters": d["input_schema"],
                },
            }
            for d in tool_definitions(provider.vision)
        ]

    def respond(self, turns: list[Turn], on_text: Callable[[str], None]) -> Reply:
        if not self.name:
            raise ChatError("Choose a model in the assistant settings first.")
        text: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish = None
        with self._errors():
            stream = self.client.chat.completions.create(
                model=self.name,
                messages=_openai_messages(turns, self.provider.vision),
                tools=self.tools,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is not None and delta.content:
                    text.append(delta.content)
                    on_text(delta.content)
                for part in (delta.tool_calls if delta is not None else None) or []:
                    call = calls.setdefault(
                        part.index if part.index is not None else len(calls),
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if part.id:
                        call["id"] = part.id
                    if part.function is not None:
                        call["name"] += part.function.name or ""
                        call["arguments"] += part.function.arguments or ""
                    extra = (part.model_extra or {}).get("extra_content")
                    if extra:
                        call["extra"] = extra
                finish = choice.finish_reason or finish
        tool_calls = [
            ToolCall(
                c["id"] or f"call_{i}",
                c["name"],
                _parse(c["arguments"]),
                c["arguments"],
                c.get("extra"),
            )
            for i, c in sorted(calls.items())
        ]
        if tool_calls:
            stop = "max_tokens" if finish == "length" else "tool_use"
        else:
            stop = {"length": "max_tokens", "content_filter": "refusal"}.get(
                finish, "end"
            )
        return Reply("".join(text), tool_calls, stop)

    def list_models(self) -> list[str]:
        with self._errors():
            # Gemini lists "models/gemini-2.5-flash" and is asked for the bare name.
            return sorted(
                m.id.removeprefix("models/") for m in self.client.models.list()
            )

    def _errors(self):
        openai = self._openai
        where = self.provider.base_url or "the OpenAI API"
        return _Translate(
            {
                openai.AuthenticationError: f"No valid API key for {where}. Set "
                f"{self.key_variable} or enter a key in the chat.",
                openai.NotFoundError: f"{where} has no model {self.name!r}; choose "
                "one in the assistant settings (Load models).",
                openai.RateLimitError: _rate_limited,
                openai.APIConnectionError: f"Cannot reach {where}. Is the server "
                "running?",
                openai.APIStatusError: "The server refused the request: {message}",
            }
        )


def _openai_messages(turns: list[Turn], vision: bool) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": SYSTEM}]
    for turn in turns:
        if isinstance(turn, str):
            messages.append({"role": "user", "content": turn})
        elif isinstance(turn, Reply):
            message: dict[str, Any] = {
                "role": "assistant",
                "content": turn.text or None,
            }
            if turn.calls:
                message["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.name,
                            "arguments": c.raw or json.dumps(c.input),
                        },
                    }
                    | ({"extra_content": c.extra} if c.extra else {})
                    for c in turn.calls
                ]
            messages.append(message)
        else:
            images = []
            for result in turn:
                content = result.content
                if result.image is not None:
                    content = "The image follows in the next message."
                    images.append(result.image)
                messages.append(
                    {"role": "tool", "tool_call_id": result.id, "content": content}
                )
            if images and vision:
                # Tool messages carry text only; the picture comes as the user's.
                parts: list[dict] = [{"type": "text", "text": "The rendered preview:"}]
                parts += [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_b64(png)}"},
                    }
                    for png in images
                ]
                messages.append({"role": "user", "content": parts})
    return messages


def _parse(arguments: str) -> Any:
    """Tool arguments as JSON; an empty string is no arguments, anything
    unreadable comes back as the string itself and is refused."""
    if not arguments.strip():
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        return arguments


def _rate_limited(exc: Exception) -> str:
    """When to try again, if the server says, and why; Gemini says both in
    its text ("... per day limit exceeded on Free Tier ... retry in 21h3m4s")."""
    text = str(getattr(exc, "message", exc))
    wait = re.search(r"retry in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", text)
    seconds = 0.0
    if wait:
        hours, minutes, rest = (float(part or 0) for part in wait.groups())
        seconds = 3600 * hours + 60 * minutes + rest
    if seconds > 5400:
        when = f"in {math.ceil(seconds / 3600)} h"
    elif seconds > 90:
        when = f"in {math.ceil(seconds / 60)} min"
    elif seconds > 0:
        when = f"in {math.ceil(seconds)} s"
    else:
        when = "shortly"
    free = "free_tier" in text or "free tier" in text.lower()
    if free and "per day" in text:
        return (
            f"The free tier's daily limit for this model is used up; try again "
            f"{when}, or choose another model."
        )
    reason = " The free tier allows only a few requests a minute." if free else ""
    return f"Too many requests just now; try again {when}.{reason}"


class _Translate:
    """Turns the SDK's errors into ChatErrors with a message for the user;
    the first matching class wins, "{message}" is the API's own text. A
    function instead of a text makes the message from the error."""

    def __init__(
        self, messages: dict[type[Exception], str | Callable[[Exception], str]]
    ):
        self.messages = messages

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb) -> bool:
        if exc is None:
            return False
        for cls, text in self.messages.items():
            if isinstance(exc, cls):
                if callable(text):
                    raise ChatError(text(exc)) from exc
                detail = getattr(exc, "message", str(exc))
                raise ChatError(text.replace("{message}", str(detail))) from exc
        if isinstance(exc, ValueError):  # a streamed tool input the SDK choked on
            raise ChatError(
                f"The answer was garbled ({exc}); please ask again."
            ) from exc
        return False


# --- the loop -----------------------------------------------------------------

ToolRunner = Callable[[str, dict], dict]
"""Runs a figscribe tool by name; raises figscribe.tools.ToolError on refusal."""


class Chat:
    """One conversation: the turns, and the loop between model and tools."""

    def __init__(self, model: Model):
        self.model = model
        self.turns: list[Turn] = []
        self.rounds = 0

    def ask(self, text: str) -> None:
        """Start a request with the user's `text`."""
        self.turns.append(text)
        self.rounds = 0

    def respond(self, on_text: Callable[[str], None]) -> Reply:
        """The model's next turn; may run in a worker thread."""
        return self.model.respond(self.turns, on_text)

    def handle(
        self,
        reply: Reply,
        run_tool: ToolRunner,
        on_tool: Callable[[str, dict, str | None], None] = lambda *_: None,
    ) -> bool:
        """Take the model's turn: run the tools it asked for and say whether
        the model needs another turn. `on_tool` hears (name, input, error)."""
        self.turns.append(reply)
        if reply.stop == "pause":
            return True
        if reply.stop == "refusal":
            raise ChatError("The model declined this request.")
        if reply.stop == "max_tokens":
            raise ChatError("The answer was cut off; please ask in smaller steps.")
        if not reply.calls:
            return False
        self.rounds += 1
        if self.rounds > MAX_ROUNDS:
            raise ChatError("Stopped after too many steps; please ask again.")
        results = []
        for call in reply.calls:
            result = _run(run_tool, call)
            arguments = call.input if isinstance(call.input, dict) else {}
            on_tool(call.name, arguments, result.content if result.is_error else None)
            results.append(result)
        self.turns.append(results)
        return True


def _run(run_tool: ToolRunner, call: ToolCall) -> ToolResult:
    from figscribe.tools import ToolError

    if not isinstance(call.input, dict):
        return ToolResult(
            call.id, "the tool input is not a JSON object; send one", is_error=True
        )
    try:
        result = run_tool(call.name, call.input)
    except ToolError as exc:
        return ToolResult(call.id, str(exc), is_error=True)
    png = result.get("png") if isinstance(result, dict) else None
    if isinstance(png, bytes):
        return ToolResult(call.id, "", image=png)
    return ToolResult(call.id, json.dumps(result, default=str))


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")
