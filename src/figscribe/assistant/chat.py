"""The built-in chat: Claude changes the open project through figscribe's tools.

The same tools as for MCP clients (`figscribe.tools`), so a change asked for
in the chat is a command like any other: shown at once, undoable. This module
holds the conversation and the tool loop and knows nothing of Qt; the GUI
calls `respond` in a worker thread and `handle` on its own thread, where the
tools may touch the document.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any, Protocol

from figscribe.tools import TOOLS

MODEL = "claude-opus-5-5"
MAX_TOKENS = 64000
MAX_ROUNDS = 25
"""Tool rounds per request, so a confused model cannot loop forever."""

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
not. Ask when the request is ambiguous instead of guessing."""


class ChatError(Exception):
    """The request could not be answered; the message says why, for the user."""


class Model(Protocol):
    def respond(self, messages: list[dict], on_text: Callable[[str], None]) -> Any:
        """One model turn: stream its text to `on_text`, return the message."""
        ...


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": spec.input_schema,
            "eager_input_streaming": True,
        }
        for spec in TOOLS
    ]


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
        self.model = model
        self.tools = tool_definitions()

    def respond(self, messages: list[dict], on_text: Callable[[str], None]) -> Any:
        anthropic = self._anthropic
        try:
            # On a safety decline the API answers with a fallback model, so the
            # user still gets an answer; the fallback blocks are echoed back.
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                tools=self.tools,
                messages=messages,
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        on_text(event.text)
                return stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise ChatError(
                "No valid API key. Set ANTHROPIC_API_KEY, sign in with "
                "`ant auth login`, or enter a key in the chat."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise ChatError("Too many requests just now; try again shortly.") from exc
        except anthropic.APIConnectionError as exc:
            raise ChatError("Cannot reach the Anthropic API.") from exc
        except anthropic.APIStatusError as exc:
            raise ChatError(f"The API refused the request: {exc.message}") from exc
        except ValueError as exc:  # a tool input the SDK could not parse
            raise ChatError(
                f"The answer was garbled ({exc}); please ask again."
            ) from exc


ToolRunner = Callable[[str, dict], dict]
"""Runs a figscribe tool by name; raises figscribe.tools.ToolError on refusal."""


class Chat:
    """One conversation: the messages, and the loop between model and tools."""

    def __init__(self, model: Model):
        self.model = model
        self.messages: list[dict] = []
        self.rounds = 0

    def ask(self, text: str) -> None:
        """Start a request with the user's `text`."""
        self.messages.append({"role": "user", "content": text})
        self.rounds = 0

    def respond(self, on_text: Callable[[str], None]) -> Any:
        """The model's next turn; may run in a worker thread."""
        return self.model.respond(self.messages, on_text)

    def handle(
        self,
        response: Any,
        run_tool: ToolRunner,
        on_tool: Callable[[str, dict, str | None], None] = lambda *_: None,
    ) -> bool:
        """Take the model's turn: run the tools it asked for and say whether
        the model needs another turn. `on_tool` hears (name, input, error)."""
        self.messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "pause_turn":
            return True
        uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "refusal":
            raise ChatError("The model declined this request.")
        if not uses:
            return False
        if response.stop_reason == "max_tokens":
            raise ChatError("The answer was cut off; please ask in smaller steps.")
        self.rounds += 1
        if self.rounds > MAX_ROUNDS:
            raise ChatError("Stopped after too many steps; please ask again.")
        results = []
        for use in uses:
            result, error = _run(run_tool, use)
            on_tool(use.name, use.input if isinstance(use.input, dict) else {}, error)
            results.append(result)
        self.messages.append({"role": "user", "content": results})
        return True


def _run(run_tool: ToolRunner, use) -> tuple[dict, str | None]:
    """A tool_result block for one tool_use, and the error text if it failed."""
    from figscribe.tools import ToolError

    arguments = use.input
    if not isinstance(arguments, dict):
        message = "the tool input is not a JSON object"
        return _error(use.id, message), message
    try:
        result = run_tool(use.name, arguments)
    except ToolError as exc:
        return _error(use.id, str(exc)), str(exc)
    png = result.get("png") if isinstance(result, dict) else None
    if isinstance(png, bytes):
        data = base64.standard_b64encode(png).decode("ascii")
        content: Any = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": data},
            }
        ]
    else:
        content = json.dumps(result, default=str)
    return {"type": "tool_result", "tool_use_id": use.id, "content": content}, None


def _error(tool_use_id: str, message: str) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": message,
        "is_error": True,
    }
