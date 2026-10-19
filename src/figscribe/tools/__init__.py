"""Tools for assistants: read the project, change it through undoable commands.

Independent of Qt and of any LLM provider. The MCP server exposes them to any
MCP client; a built-in chat can use the same definitions.
"""

from figscribe.tools.operations import Toolbox, ToolError
from figscribe.tools.spec import TOOLS, ToolSpec
from figscribe.tools.workspace import ProjectWorkspace, Workspace, column_choices

__all__ = [
    "TOOLS",
    "ProjectWorkspace",
    "ToolError",
    "ToolSpec",
    "Toolbox",
    "Workspace",
    "column_choices",
]
