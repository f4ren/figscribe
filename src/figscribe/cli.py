"""The `figscribe` command: the GUI, or `figscribe mcp` for MCP clients."""

from __future__ import annotations

import sys

from figscribe import __version__

USAGE = """\
usage: figscribe [PROJECT.figscribe]   open the GUI, optionally with a project
       figscribe mcp                   serve the open project to an MCP client
       figscribe --version"""


def main() -> int:
    args = sys.argv[1:]
    if args[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if args[:1] == ["--version"]:
        print(f"figscribe {__version__}")
        return 0
    if args[:1] == ["mcp"]:
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
