"""The `figscribe` command: the GUI, or `figscribe mcp` for MCP clients."""

from __future__ import annotations

import sys


def main() -> int:
    if sys.argv[1:2] == ["mcp"]:
        try:
            from figscribe.assistant.mcpserver import main as serve
        except ImportError as exc:
            print(
                f"figscribe mcp needs the MCP package ({exc.name} is missing): "
                'pip install "figscribe[mcp]"',
                file=sys.stderr,
            )
            return 1
        return serve()

    from figscribe.gui.app import main as gui

    return gui()


if __name__ == "__main__":
    sys.exit(main())
