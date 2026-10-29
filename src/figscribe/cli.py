"""The `figscribe` command: the GUI, or `figscribe mcp` for MCP clients."""

from __future__ import annotations

import sys

from figscribe import __version__

USAGE = """\
usage: figscribe [PROJECT.figscribe]   open the GUI, optionally with a project
       figscribe script PROJECT.figscribe [--figure NAME] [-o SCRIPT.py]
                                       write the Python script for a figure,
                                       by default the first
       figscribe script PROJECT.figscribe --all [-o FOLDER]
                                       write a script for every figure
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
    import argparse
    from pathlib import Path

    from figscribe.codegen import file_stems
    from figscribe.model import loads

    parser = argparse.ArgumentParser(prog="figscribe script", add_help=False)
    parser.add_argument("project", type=Path)
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--figure", metavar="NAME")
    which.add_argument("--all", action="store_true")
    parser.add_argument("-o", dest="target", type=Path)
    try:
        options = parser.parse_args(args)
    except SystemExit:
        print(USAGE, file=sys.stderr)
        return 2
    project_path: Path = options.project
    try:
        project = loads(project_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"figscribe: cannot read {project_path}: {exc}", file=sys.stderr)
        return 1
    if not project.figures:
        print(f"figscribe: {project_path} has no figure", file=sys.stderr)
        return 1
    if options.all:
        folder = options.target or project_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        for figure, stem in zip(
            project.figures, file_stems(project.figures), strict=True
        ):
            target = folder / f"{stem}.py"
            _write_script(project, figure, project_path, target)
            print(target)
        return 0
    figure = project.figures[0]
    if options.figure is not None:
        figure = next((f for f in project.figures if f.name == options.figure), None)
        if figure is None:
            names = ", ".join(f.name for f in project.figures)
            print(
                f"figscribe: no figure {options.figure!r} in {project_path}; "
                f"it has {names}",
                file=sys.stderr,
            )
            return 1
    target = options.target
    script = _write_script(project, figure, project_path, target)
    if target is None:
        sys.stdout.write(script)
    return 0


def _write_script(project, figure, project_path, target) -> str:
    """The script for `figure`, written to `target` unless it is None; the
    figure it saves is named after `target`, or after the figure."""
    from pathlib import Path

    from figscribe.codegen import generate, script_name
    from figscribe.io import DataError, load_data

    script_dir = target.parent if target is not None else project_path.parent
    stem = target.stem if target is not None else Path(script_name(figure)).stem
    options = {
        "base_dir": project_path.parent,
        "script_dir": script_dir,
        "output": f"{stem}.pdf",
    }
    try:
        # With the data, the script leaves out what the preview leaves out.
        data = load_data(project, project_path.parent)
        script = generate(project, figure, data=data, **options)
    except DataError as exc:
        print(f"figscribe: {exc}; writing the script without it", file=sys.stderr)
        script = generate(project, figure, **options)
    if target is not None:
        target.write_text(script, encoding="utf-8")
    return script


if __name__ == "__main__":
    sys.exit(main())
