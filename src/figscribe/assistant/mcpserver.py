"""`figscribe mcp`: an MCP server on stdio that forwards to the running figscribe.

An MCP client (Claude Desktop, Claude Code, an IDE, a local model's front end)
starts this command. It lists figscribe's tools and passes each call to the
application, which runs it on the open project. No Qt here, and no project
state: every call goes to whatever the user has open at that moment.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from figscribe import __version__
from figscribe.assistant import endpoint
from figscribe.tools import TOOLS

INSTRUCTIONS = """\
figscribe is a desktop application for scientific plots; these tools act on the
project the user has open in it, live. Changes appear in the user's window at
once and can be undone there.

Start with get_project to see the figures, axes, plots and their ids; call it
again when you need fresh ids, since the user may change the project too. The
"selected" id is what the user has selected; "this plot" usually means it.
Use list_columns for the data columns a plot or fit can use, and get_schema
when unsure about a field. For a request that needs more than one change, use
apply_changes, so the user can undo the whole request in one step. When a call
is refused, read the message: it names the field and the reason. If the user
allowed it, render_preview shows the figure to check your result.
"""

NOT_RUNNING = (
    "figscribe is not reachable. Ask the user to start figscribe and enable "
    "'Assistant > Allow MCP access'."
)


async def forward(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Send one tool call to the running application and return its answer."""
    target = endpoint.read()
    if target is None:
        return {"ok": False, "error": NOT_RUNNING}
    try:
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", target.port, limit=endpoint.MAX_LINE
        )
    except OSError:
        return {"ok": False, "error": NOT_RUNNING}
    try:
        writer.write(
            endpoint.encode(
                {"token": target.token, "tool": tool, "arguments": arguments}
            )
        )
        await writer.drain()
        line = await reader.readline()
        if not line:
            return {"ok": False, "error": "figscribe closed the connection"}
        return endpoint.decode(line)
    finally:
        writer.close()


def to_result(response: dict[str, Any]) -> types.CallToolResult:
    """An MCP tool result: the answer as JSON text, a preview as an image."""
    if not response.get("ok"):
        message = response.get("error", "unknown error")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)], is_error=True
        )
    result = dict(response.get("result") or {})
    content: list[Any] = []
    png = result.pop("png_base64", None)
    if png is not None:
        content.append(
            types.ImageContent(type="image", data=png, mime_type="image/png")
        )
    if result or not content:
        content.append(types.TextContent(type="text", text=json.dumps(result)))
    return types.CallToolResult(content=content)


async def _list_tools(ctx, params) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in TOOLS
        ]
    )


async def _call_tool(ctx, params) -> types.CallToolResult:
    return to_result(await forward(params.name, dict(params.arguments or {})))


def create_server() -> Server:
    return Server(
        "figscribe",
        version=__version__,
        instructions=INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


async def serve() -> None:
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def main() -> int:
    asyncio.run(serve())
    return 0
