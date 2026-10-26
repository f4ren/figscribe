"""The `figscribe` command: the GUI, or `figscribe mcp` for MCP clients."""

from __future__ import annotations

import sys

from figscribe import __version__

USAGE = """\
usage: figscribe [PROJECT.figscribe]   open the GUI, optionally with a project
       figscribe script PROJECT.figscribe [-o SCRIPT.py]
                                       write the Python script for its first figure
       figscribe mcp                   serve the open project to an MCP client
       figscribe bench [--help]        measure a model on typical assistant requests
       figscribe --version"""


def main() -> int:
    args = sys.argv[1:]
    if args[:1] in (["-h"], ["--help"]):
        print(USAGE)
        return 0
    if args[:1] == ["--version"]:
        print(f"figscribe {__version__}")
        return 0
    if args[:1] == ["script"]:
        return _script(args[1:])
    if args[:1] == ["bench"]:
        from figscribe.assistant.bench import main as bench

        return bench(args[1:])
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


def _script(args: list[str]) -> int:
    """`figscribe script`: the generated code, to a file or standard output."""
    from pathlib import Path

    from figscribe.codegen import generate, script_name
    from figscribe.io import DataError, load_data
    from figscribe.model import loads

    if len(args) not in (1, 3) or (len(args) == 3 and args[1] != "-o"):
        print(USAGE, file=sys.stderr)
        return 2
    project_path = Path(args[0])
    try:
        project = loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"figscribe: cannot read {project_path}: {exc}", file=sys.stderr)
        return 1
    if not project.figures:
        print(f"figscribe: {project_path} has no figure", file=sys.stderr)
        return 1
    figure = project.figures[0]
    target = Path(args[2]) if len(args) == 3 else None
    script_dir = target.parent if target is not None else project_path.parent
    output = f"{target.stem}.pdf" if target is not None else None
    options = {
        "base_dir": project_path.parent,
        "script_dir": script_dir,
        "output": output or f"{Path(script_name(figure)).stem}.pdf",
    }
    try:
        # With the data, the script leaves out what the preview leaves out.
        script = generate(
            project, figure, data=load_data(project, project_path.parent), **options
        )
    except DataError as exc:
        print(f"figscribe: {exc}; writing the script without it", file=sys.stderr)
        script = generate(project, figure, **options)
    if target is None:
        sys.stdout.write(script)
    else:
        target.write_text(script, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
