"""Tools for assistants: read the project, change it through undoable commands.

Independent of Qt and of any LLM provider. The MCP server exposes them to any
MCP client; a built-in chat can use the same definitions.

`TOOLS` is cheap to import; the rest loads matplotlib and SciPy and is
imported on first use, so that `figscribe mcp` starts quickly.
"""

from typing import TYPE_CHECKING, Any

from figscribe.tools.spec import TOOLS, ToolSpec

if TYPE_CHECKING:
    from figscribe.tools.operations import Toolbox, ToolError
    from figscribe.tools.workspace import ProjectWorkspace, Workspace, column_choices

_LAZY = {
    "Toolbox": "figscribe.tools.operations",
    "ToolError": "figscribe.tools.operations",
    "ProjectWorkspace": "figscribe.tools.workspace",
    "Workspace": "figscribe.tools.workspace",
    "column_choices": "figscribe.tools.workspace",
}


def __getattr__(name: str) -> Any:
    if name in _LAZY:
        import importlib

        return getattr(importlib.import_module(_LAZY[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "TOOLS",
    "ProjectWorkspace",
    "ToolError",
    "ToolSpec",
    "Toolbox",
    "Workspace",
    "column_choices",
]
