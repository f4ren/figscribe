"""A benchmark for the assistant: typical requests, checked automatically.

Each case starts from the example project (a Gaussian scan, errorbar plot of
U against t with error dU), asks the model one thing through the chat's tool
loop and checks the resulting project. It answers which model is good enough
for which kind of request, e.g. a local one in LM Studio against Claude:

    figscribe bench --base-url http://localhost:1234/v1 --model qwen3-30b

Every case has a reference solution, a list of tool calls that fulfils it;
the tests run them so that a check can be trusted to pass when it should.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal

from figscribe.assistant.chat import Chat, ChatError, Model
from figscribe.model import (
    Annotation,
    Axes,
    ErrorbarPlot,
    FitCurve,
    Histogram,
    LinePlot,
    PredefinedFit,
    Project,
    ResidualPlot,
    ScatterPlot,
)

Level = Literal["easy", "medium", "hard"]
Call = Callable[[str, dict], dict]
"""Runs a tool by name, returns its result."""
Solution = Callable[[Call, Project], None]


@dataclass(frozen=True)
class Case:
    name: str
    level: Level
    request: str
    check: Callable[[Project], str | None]
    """None when the project does what was asked, else what is wrong."""
    solution: Solution
    """Tool calls that fulfil the request, for testing the check."""


@dataclass
class Outcome:
    case: str
    level: Level
    passed: bool
    reason: str | None
    """Why it failed: the check's answer, or the chat's error."""
    seconds: float
    rounds: int
    tool_errors: int


# --- the example project's parts ------------------------------------------------


def _figure(p: Project):
    return p.figures[0]


def _panel(p: Project) -> Axes:
    """The example's own panel (the first)."""
    return _figure(p).axes[0]


def _data(p: Project) -> ErrorbarPlot:
    return next(a for a in _panel(p).artists if isinstance(a, ErrorbarPlot))


def _source(p: Project) -> str:
    return p.sources[0].id


def _column(p: Project, name: str) -> dict:
    return {"source": _source(p), "column": name}


def _all_artists(p: Project):
    return [a for axes in _figure(p).axes for a in axes.artists]


def _uses(artist, field: str, column: str) -> bool:
    ref = getattr(artist, field, None)
    return ref is not None and getattr(ref, "column", None) == column


def _close(value, expected, tolerance=1e-6) -> bool:
    return value is not None and abs(value - expected) <= tolerance


def _expect(condition: bool, otherwise: str) -> str | None:
    return None if condition else otherwise


def _all(*reasons: str | None) -> str | None:
    return next((r for r in reasons if r is not None), None)


def _red(color: str | None) -> bool:
    from matplotlib.colors import to_rgb

    if color is None:
        return False
    try:
        r, g, b = to_rgb(color)
    except ValueError:
        return False
    return r > 0.6 and g < 0.45 and b < 0.45


# --- the cases ------------------------------------------------------------------


def _check_legend_top_left(p: Project) -> str | None:
    legend = _panel(p).legend
    if legend.position is not None:
        x, y = legend.position
        return _expect(x < 0.35 and y > 0.65, f"legend placed at {legend.position}")
    return _expect(legend.location == "upper left", f"legend at {legend.location!r}")


def _check_scatter(p: Project) -> str | None:
    found = [
        a
        for a in _panel(p).artists
        if isinstance(a, ScatterPlot) and _uses(a, "x", "t") and _uses(a, "y", "dU")
    ]
    return _expect(bool(found), "no scatter plot of dU against t in the panel")


def _gaussian(fit: FitCurve) -> bool:
    model = fit.model
    if isinstance(model, PredefinedFit):
        return model.name == "gaussian"
    return "exp" in model.expression


def _check_fit(p: Project) -> str | None:
    target = _data(p).id
    fits = [
        a for a in _all_artists(p) if isinstance(a, FitCurve) and a.target == target
    ]
    if not fits:
        return "no fit of the measurement"
    fit = fits[-1]
    return _all(
        _expect(_gaussian(fit), "the fit is not a Gaussian"),
        _expect(
            fit.result is not None and fit.result.converged, "the fit did not converge"
        ),
    )


def _check_panel_below(p: Project) -> str | None:
    figure = _figure(p)
    top = _panel(p)
    below = [
        axes
        for axes in figure.axes
        if axes.row > top.row
        and any(
            isinstance(a, LinePlot) and _uses(a, "y", "dU") and _uses(a, "x", "t")
            for a in axes.artists
        )
    ]
    return _all(
        _expect(bool(below), "no panel below with a line of dU against t"),
        _expect(figure.layout.share_x != "none", "the x axis is not shared"),
    )


def _check_note(p: Project) -> str | None:
    notes = [
        a
        for a in _all_artists(p)
        if isinstance(a, Annotation) and "peak" in a.text.lower()
    ]
    if not notes:
        return "no note saying 'peak'"
    note = notes[-1]
    tip = note.arrow_to
    return _all(
        _expect(note.coords == "data", "the note is not placed in data coordinates"),
        _expect(
            tip is not None and abs(tip[0] - 5) <= 0.5 and abs(tip[1] - 1) <= 0.2,
            f"the arrow points at {tip}, not at (5, 1)",
        ),
    )


def _check_right_axis(p: Project) -> str | None:
    panel = _panel(p)
    plots = [a for a in panel.artists if a.axis == "right" and _uses(a, "y", "dU")]
    return _all(
        _expect(panel.y_right is not None, "the panel has no right y axis"),
        _expect(bool(plots), "dU is not drawn against the right axis"),
        _expect(
            panel.y_right is not None and "du" in (panel.y_right.label or "").lower(),
            "the right axis is not labelled dU",
        ),
    )


def _check_axis_names(p: Project) -> str | None:
    x, y = _panel(p).x, _panel(p).y
    return _all(
        _expect("time" in (x.label or "").lower(), f"x label is {x.label!r}"),
        _expect("voltage" in (y.label or "").lower(), f"y label is {y.label!r}"),
        _expect(x.unit == "s" and y.unit == "V", "the units were lost"),
    )


def _check_histogram(p: Project) -> str | None:
    figure = _figure(p)
    top = _panel(p)
    right = [
        axes
        for axes in figure.axes
        if axes.col > top.col
        and axes.inset is None
        and any(
            isinstance(a, Histogram) and _uses(a, "values", "U") for a in axes.artists
        )
    ]
    return _expect(bool(right), "no panel on the right with a histogram of U")


def _check_publication(p: Project) -> str | None:
    figure = _figure(p)
    return _all(
        _expect(_close(figure.width_mm, 85, 0.5), f"width is {figure.width_mm} mm"),
        _expect(_close(figure.height_mm, 55, 0.5), f"height is {figure.height_mm} mm"),
        _expect(_close(figure.font_size, 8), f"font size is {figure.font_size}"),
        _expect(not _panel(p).legend.frame, "the legend still has a frame"),
    )


def _check_inset(p: Project) -> str | None:
    top = _panel(p)
    insets = [
        a for a in _figure(p).axes if a.inset is not None and a.inset.parent == top.id
    ]
    if not insets:
        return "no inset in the panel"
    inset = insets[-1]
    left, bottom, width, height = inset.inset.bounds
    limits = inset.x.limits
    return _all(
        _expect(any(_uses(a, "y", "U") for a in inset.artists), "the inset shows no U"),
        _expect(
            limits is not None
            and _close(limits[0], 4, 0.25)
            and _close(limits[1], 6, 0.25),
            f"the inset's x range is {limits}",
        ),
        _expect(
            left + width / 2 > 0.5 and bottom + height / 2 > 0.5,
            "the inset is not in the upper right",
        ),
    )


def _check_residuals(p: Project) -> str | None:
    fits = [a for a in _all_artists(p) if isinstance(a, FitCurve)]
    if not fits:
        return "no fit"
    top = _panel(p)
    residuals = [
        axes
        for axes in _figure(p).axes
        if axes.row > top.row
        and any(
            isinstance(a, ResidualPlot) and a.target == fits[-1].id
            for a in axes.artists
        )
    ]
    return _all(
        _check_fit(p),
        _expect(bool(residuals), "no residuals of the fit in a panel below"),
    )


def _set(call: Call, object_id: str | None, path: list[str], value) -> dict:
    return call("set_field", {"object_id": object_id, "path": path, "value": value})


def _setting(object_id: str | None, path: list[str], value) -> dict:
    """A set_field operation for apply_changes."""
    return {"op": "set_field", "object_id": object_id, "path": path, "value": value}


def _changes(call: Call, *operations: dict) -> dict:
    return call(
        "apply_changes", {"description": "Benchmark", "operations": list(operations)}
    )


def _insert(call: Call, parent_id: str, obj: dict) -> dict:
    return call("insert", {"parent_id": parent_id, "field": "artists", "object": obj})


def _fit(call: Call, p: Project, residuals: bool = False) -> None:
    arguments = {
        "target_id": _data(p).id,
        "model": {"kind": "predefined", "name": "gaussian"},
    }
    if residuals:
        arguments["residuals"] = True
    call("fit", arguments)


def _setter(target: Callable[[Project], object], path: list[str], value) -> Solution:
    """A one-call solution: set `path` of the object `target` finds."""

    def solve(call: Call, p: Project) -> None:
        _set(call, target(p).id, path, value)

    return solve


def _new_panel(call: Call, p: Project, side: str, obj: dict) -> str:
    """A panel at `side` of the example's, with `obj` drawn in it."""
    panel = call("add_panel", {"axes_id": _panel(p).id, "side": side})["id"]
    _insert(call, panel, obj)
    return panel


def _solve_legend_and_caps(call: Call, p: Project) -> None:
    _changes(
        call,
        _setting(_panel(p).id, ["legend", "frame"], False),
        _setting(_data(p).id, ["capsize"], 4),
    )


def _solve_axis_names(call: Call, p: Project) -> None:
    _set(call, _panel(p).id, ["x", "label"], "time")
    _set(call, _panel(p).id, ["y", "label"], "voltage")


def _solve_scatter(call: Call, p: Project) -> None:
    scatter = {"kind": "scatter", "x": _column(p, "t"), "y": _column(p, "dU")}
    _insert(call, _panel(p).id, scatter)


def _solve_note(call: Call, p: Project) -> None:
    note = {"kind": "annotation", "text": "peak", "position": [7, 1.1]}
    _insert(call, _panel(p).id, {**note, "arrow_to": [5, 1]})


def _solve_right_axis(call: Call, p: Project) -> None:
    line = {"kind": "line", "x": _column(p, "t"), "y": _column(p, "dU")}
    _changes(
        call,
        _setting(_panel(p).id, ["y_right"], {"label": "dU", "unit": "V"}),
        {
            "op": "insert",
            "parent_id": _panel(p).id,
            "field": "artists",
            "object": {**line, "axis": "right"},
        },
    )


def _solve_histogram(call: Call, p: Project) -> None:
    _new_panel(call, p, "right", {"kind": "histogram", "values": _column(p, "U")})


def _solve_panel_below(call: Call, p: Project) -> None:
    line = {"kind": "line", "x": _column(p, "t"), "y": _column(p, "dU")}
    _new_panel(call, p, "below", line)
    _set(call, _figure(p).id, ["layout", "share_x"], "col")


def _solve_publication(call: Call, p: Project) -> None:
    figure = _figure(p).id
    _changes(
        call,
        _setting(figure, ["width_mm"], 85),
        _setting(figure, ["height_mm"], 55),
        _setting(figure, ["font_size"], 8),
        _setting(_panel(p).id, ["legend", "frame"], False),
    )


def _solve_inset(call: Call, p: Project) -> None:
    data = {"kind": "errorbar", "x": _column(p, "t"), "y": _column(p, "U")}
    inset = _new_panel(call, p, "inset", data)
    _set(call, inset, ["x", "limits"], [4, 6])


CASES: list[Case] = [
    Case(
        "x-label",
        "easy",
        "Label the x axis 'Time'.",
        lambda p: _expect(
            "time" in (_panel(p).x.label or "").lower(),
            f"x label is {_panel(p).x.label!r}",
        ),
        _setter(_panel, ["x", "label"], "Time"),
    ),
    Case(
        "width",
        "easy",
        "Make the figure 170 mm wide, for two journal columns.",
        lambda p: _expect(
            _close(_figure(p).width_mm, 170, 0.5), f"width is {_figure(p).width_mm}"
        ),
        _setter(_figure, ["width_mm"], 170),
    ),
    Case(
        "x-range",
        "easy",
        "Show only t from 2 s to 8 s.",
        lambda p: _expect(
            _panel(p).x.limits is not None
            and _close(_panel(p).x.limits[0], 2, 0.01)
            and _close(_panel(p).x.limits[1], 8, 0.01),
            f"x range is {_panel(p).x.limits}",
        ),
        _setter(_panel, ["x", "limits"], [2, 8]),
    ),
    Case(
        "log-y",
        "easy",
        "Use a logarithmic y axis.",
        lambda p: _expect(
            _panel(p).y.scale == "log", f"y scale is {_panel(p).y.scale}"
        ),
        _setter(_panel, ["y", "scale"], "log"),
    ),
    Case(
        "legend-corner",
        "easy",
        "Put the legend in the upper left corner.",
        _check_legend_top_left,
        _setter(_panel, ["legend", "location"], "upper left"),
    ),
    Case(
        "color",
        "easy",
        "Draw the measurement in red.",
        lambda p: _expect(_red(_data(p).color), f"color is {_data(p).color!r}"),
        _setter(_data, ["color"], "tab:red"),
    ),
    Case(
        "title-german",
        "easy",
        "Gib dem Diagramm den Titel „Kalibrierung“.",
        lambda p: _expect(
            "kalibrierung" in (_panel(p).title or "").lower(),
            f"title is {_panel(p).title!r}",
        ),
        _setter(_panel, ["title"], "Kalibrierung"),
    ),
    Case(
        "grid",
        "easy",
        "Turn on the grid.",
        lambda p: _expect(_panel(p).grid, "the grid is off"),
        _setter(_panel, ["grid"], True),
    ),
    Case(
        "font-size",
        "easy",
        "Set the figure's font size to 8 pt.",
        lambda p: _expect(
            _close(_figure(p).font_size, 8), f"font size is {_figure(p).font_size}"
        ),
        _setter(_figure, ["font_size"], 8),
    ),
    Case(
        "markers",
        "easy",
        "Use square markers for the measurement.",
        lambda p: _expect(_data(p).marker == "s", f"marker is {_data(p).marker!r}"),
        _setter(_data, ["marker"], "s"),
    ),
    Case(
        "legend-and-caps",
        "medium",
        "Remove the legend's frame and make the error bar caps 4 pt wide.",
        lambda p: _all(
            _expect(not _panel(p).legend.frame, "the legend still has a frame"),
            _expect(_close(_data(p).capsize, 4), f"capsize is {_data(p).capsize}"),
        ),
        _solve_legend_and_caps,
    ),
    Case(
        "axis-names",
        "medium",
        "Rename the axes to 'time' and 'voltage', keeping their units.",
        _check_axis_names,
        _solve_axis_names,
    ),
    Case(
        "scatter",
        "medium",
        "Also plot dU against t as a scatter plot in the same panel.",
        _check_scatter,
        _solve_scatter,
    ),
    Case(
        "gaussian-fit",
        "medium",
        "Fit a Gaussian to the measurement.",
        _check_fit,
        lambda call, p: _fit(call, p),
    ),
    Case(
        "note",
        "medium",
        "Add a note 'peak' with an arrow pointing at t = 5 s, U = 1 V.",
        _check_note,
        _solve_note,
    ),
    Case(
        "right-axis",
        "medium",
        "Plot dU as a line against a second y axis on the right of the same "
        "panel, and label that axis 'dU'.",
        _check_right_axis,
        _solve_right_axis,
    ),
    Case(
        "histogram-right",
        "medium",
        "Add a panel to the right of the plot with a histogram of U.",
        _check_histogram,
        _solve_histogram,
    ),
    Case(
        "panel-below",
        "hard",
        "Add a second panel below that shows dU against t as a line, sharing "
        "the x axis.",
        _check_panel_below,
        _solve_panel_below,
    ),
    Case(
        "publication",
        "hard",
        "Prepare it for a single-column journal figure: 85 mm wide, 55 mm high, "
        "8 pt text and a legend without frame.",
        _check_publication,
        _solve_publication,
    ),
    Case(
        "inset",
        "hard",
        "Add an inset in the upper right of the panel showing the same "
        "measurement zoomed in to t between 4 s and 6 s.",
        _check_inset,
        _solve_inset,
    ),
    Case(
        "fit-residuals",
        "hard",
        "Fit a Gaussian to the measurement and show its residuals in a panel below.",
        _check_residuals,
        lambda call, p: _fit(call, p, residuals=True),
    ),
]


def case(name: str) -> Case:
    return next(c for c in CASES if c.name == name)


# --- running ----------------------------------------------------------------------


def run_case(case: Case, model: Model) -> Outcome:
    """Ask `model` for the case on a fresh copy of the example project."""
    from figscribe.tools import Toolbox

    workspace = example_workspace()
    toolbox = Toolbox(workspace)
    chat = Chat(model)
    chat.ask(case.request)
    errors = 0

    def heard(name, arguments, error) -> None:
        nonlocal errors
        errors += error is not None

    reason = None
    start = time.perf_counter()
    try:
        while chat.handle(chat.respond(lambda _: None), toolbox.call, heard):
            pass
    except ChatError as exc:
        reason = f"chat stopped: {exc}"
    seconds = time.perf_counter() - start
    if reason is None:
        reason = case.check(workspace.project)
    return Outcome(
        case.name, case.level, reason is None, reason, seconds, chat.rounds, errors
    )


def example_workspace():
    """A workspace on the example project, which is only read, never written."""
    from figscribe.examples import bundled_example
    from figscribe.model import loads
    from figscribe.tools import ProjectWorkspace

    folder = bundled_example()
    project = loads((folder / "scan.figscribe").read_text(encoding="utf-8"))
    workspace = ProjectWorkspace(project, folder)
    workspace.allow_preview = True
    return workspace


def apply_solution(case: Case, workspace) -> None:
    """Run the case's reference solution against `workspace`."""
    from figscribe.tools import Toolbox

    case.solution(Toolbox(workspace).call, workspace.project)


def report(outcomes: list[Outcome]) -> str:
    """A plain-text table, and the score per level."""
    lines = [
        f"{'case':<18}{'level':<8}{'ok':<4}{'s':>6}{'rounds':>8}{'errors':>8}  why"
    ]
    for o in outcomes:
        mark = "✓" if o.passed else "✗"
        lines.append(
            f"{o.case:<18}{o.level:<8}{mark:<4}{o.seconds:>6.1f}{o.rounds:>8}"
            f"{o.tool_errors:>8}  {o.reason or ''}"
        )
    lines.append("")
    for level in ("easy", "medium", "hard"):
        mine = [o for o in outcomes if o.level == level]
        if mine:
            passed = sum(o.passed for o in mine)
            lines.append(f"{level:<8}{passed}/{len(mine)}")
    total = sum(o.passed for o in outcomes)
    seconds = sum(o.seconds for o in outcomes)
    lines.append(f"{'total':<8}{total}/{len(outcomes)} in {seconds:.0f} s")
    return "\n".join(lines)


def to_json(outcomes: list[Outcome], model: str) -> str:
    return json.dumps(
        {"model": model, "outcomes": [asdict(o) for o in outcomes]}, indent=2
    )


# --- the command ------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """`figscribe bench`: run the cases against a model, print the table."""
    import argparse
    import sys

    from figscribe.assistant.chat import MODEL, Provider, make_model

    parser = argparse.ArgumentParser(
        prog="figscribe bench",
        description="Measure how well a model handles typical requests. Without "
        "--base-url it uses Claude (ANTHROPIC_API_KEY); with it, any server with "
        "the OpenAI chat completions API (OPENAI_API_KEY if it needs one; "
        "GEMINI_API_KEY for Gemini).",
    )
    parser.add_argument("--model", help=f"model id (Claude default: {MODEL})")
    parser.add_argument(
        "--base-url", help="OpenAI-compatible server, e.g. http://localhost:1234/v1"
    )
    parser.add_argument(
        "--no-vision",
        action="store_true",
        help="the model cannot read images; render_preview is not offered",
    )
    parser.add_argument(
        "--case", action="append", default=[], help="run only this case (repeatable)"
    )
    parser.add_argument("--level", choices=["easy", "medium", "hard"])
    parser.add_argument("--repeat", type=int, default=1, help="runs per case")
    parser.add_argument("--json", metavar="FILE", help="also write the results here")
    parser.add_argument("--list", action="store_true", help="list the cases and exit")
    args = parser.parse_args(argv)

    cases = [
        c
        for c in CASES
        if (not args.case or c.name in args.case)
        and (args.level is None or c.level == args.level)
    ]
    if args.list:
        for c in cases:
            print(f"{c.name:<18}{c.level:<8}{c.request}")
        return 0
    unknown = set(args.case) - {c.name for c in CASES}
    if unknown or not cases:
        print(f"figscribe bench: no case {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    if args.base_url:
        provider = Provider(
            "openai", args.model or "", args.base_url, not args.no_vision
        )
        if not provider.model:
            parser.error("--model is required with --base-url")
    else:
        provider = Provider("anthropic", args.model or MODEL)
    try:
        model = make_model(provider)
    except ChatError as exc:
        print(f"figscribe bench: {exc}", file=sys.stderr)
        return 1

    outcomes = []
    for c in cases:
        for _ in range(args.repeat):
            outcome = run_case(c, model)
            mark = "✓" if outcome.passed else "✗"
            print(f"{mark} {c.name} ({outcome.seconds:.1f} s)", file=sys.stderr)
            outcomes.append(outcome)
    print(
        f"Model: {provider.label}"
        + (f" at {provider.base_url}" if provider.base_url else "")
    )
    print(report(outcomes))
    if args.json:
        from pathlib import Path

        Path(args.json).write_text(to_json(outcomes, provider.label), encoding="utf-8")
    return 0
