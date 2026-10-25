"""The assistant tools: strict input, undoable changes, no data leaving."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from figscribe.commands import find
from figscribe.model import ErrorbarPlot, LinePlot, dumps, loads
from figscribe.tools import TOOLS, ProjectWorkspace, Toolbox, ToolError


@pytest.fixture
def workspace(example: Path) -> ProjectWorkspace:
    project = loads(example.read_text(encoding="utf-8"))
    return ProjectWorkspace(project, example.parent)


@pytest.fixture
def tools(workspace: ProjectWorkspace) -> Toolbox:
    return Toolbox(workspace)


def _ids(workspace):
    figure = workspace.project.figures[0]
    axes = figure.axes[0]
    return figure.id, axes.id, axes.artists[0].id, workspace.project.sources[0].id


# --- the definitions -----------------------------------------------------------


def test_every_spec_has_a_tool_and_back() -> None:
    names = {spec.name for spec in TOOLS}
    methods = {m.removeprefix("tool_") for m in dir(Toolbox) if m.startswith("tool_")}
    assert names == methods


@pytest.mark.parametrize("spec", TOOLS, ids=lambda s: s.name)
def test_specs_are_well_formed(spec) -> None:
    schema = spec.input_schema
    assert schema["type"] == "object"
    assert set(schema.get("required", [])) <= set(schema["properties"])
    assert len(spec.description) > 40
    json.dumps(schema)  # serializable as sent to a client


# --- reading -------------------------------------------------------------------


def test_get_project_shows_structure_but_no_file_locations(tools, workspace) -> None:
    workspace.project.sources[0].path = "/home/someone/secret/scan.csv"
    result = tools.call("get_project", {})
    source = result["project"]["sources"][0]
    assert source["path"] == "scan.csv"
    assert "sha256" not in source
    assert source["columns"] == ["t", "U", "dU"]
    assert result["problems"] == ["scan.csv is missing; the user can locate it"]
    assert result["shown_figure"] == workspace.project.figures[0].id
    json.dumps(result)  # plain JSON all the way down


def test_get_project_contains_no_data_values(tools, workspace) -> None:
    text = json.dumps(tools.call("get_project", {}))
    csv = (workspace.base_dir / "scan.csv").read_text(encoding="utf-8")
    numbers = [line.split(",")[1] for line in csv.splitlines()[3:]]
    assert not any(n in text for n in numbers)


def test_get_schema_describes_the_format(tools) -> None:
    schema = tools.call("get_schema", {})
    assert "Figure" in schema["$defs"] and "LinePlot" in schema["$defs"]


def test_list_columns(tools, workspace) -> None:
    columns = tools.call("list_columns", {})["columns"]
    source = workspace.project.sources[0].id
    assert [c["label"] for c in columns] == [
        "scan.csv: t",
        "scan.csv: U",
        "scan.csv: dU",
    ]
    assert columns[0]["ref"] == {"source": source, "column": "t"}


def test_the_preview_needs_permission(tools, workspace) -> None:
    with pytest.raises(ToolError, match="allow"):
        tools.call("render_preview", {})
    workspace.allow_preview = True
    png = tools.call("render_preview", {})["png"]
    assert png.startswith(b"\x89PNG")
    width = int.from_bytes(png[16:20], "big")
    assert width == int(85 / 25.4 * 150)  # truncated to whole pixels, as Agg does


def test_the_python_script_draws_the_shown_figure(tools, workspace) -> None:
    script = tools.call("get_python_script", {})["script"]
    assert "np.loadtxt" in script and "fig.savefig" in script
    assert workspace.project.sources[0].sha256 in script
    compile(script, "figure.py", "exec")


def test_add_panel_grows_the_grid(tools, workspace) -> None:
    axes = workspace.project.figures[0].axes[0]
    new = tools.call("add_panel", {"axes_id": axes.id, "side": "below"})["id"]
    figure = workspace.project.figures[0]
    assert figure.layout.rows == 2 and figure.axes[-1].id == new
    with pytest.raises(ToolError, match="side"):
        tools.call("add_panel", {"axes_id": axes.id, "side": "diagonal"})


# --- set_field -----------------------------------------------------------------


def test_set_field_is_one_undo_step(tools, workspace) -> None:
    _, axes, _, _ = _ids(workspace)
    result = tools.call(
        "set_field", {"object_id": axes, "path": ["x", "limits"], "value": [0, 5]}
    )
    assert workspace.project.figures[0].axes[0].x.limits == (0.0, 5.0)
    assert result["undo_step"] == "Set x limits"
    workspace.undo()
    assert workspace.project.figures[0].axes[0].x.limits is None


def test_set_field_is_strict(tools, workspace) -> None:
    figure, *_ = _ids(workspace)
    with pytest.raises(ToolError, match="valid number"):
        tools.call("set_field", {"object_id": figure, "path": ["dpi"], "value": "300"})
    with pytest.raises(ToolError, match="greater than or equal to 72"):
        tools.call("set_field", {"object_id": figure, "path": ["dpi"], "value": -1})
    tools.call("set_field", {"object_id": figure, "path": ["dpi"], "value": 150})
    assert workspace.project.figures[0].dpi == 150.0


def test_a_tick_step_that_would_freeze_the_figure_is_refused(tools, workspace) -> None:
    _, axes, _, _ = _ids(workspace)
    before = dumps(workspace.project)
    # The data's t runs from 0 to 10, so every 0.001 means thousands of ticks.
    with pytest.raises(ToolError, match="at most 50"):
        tools.call(
            "set_field",
            {"object_id": axes, "path": ["x", "major_step"], "value": 0.001},
        )
    step = {"op": "set_field", "object_id": axes, "path": ["x", "major_step"]}
    wide = {"op": "set_field", "object_id": axes, "path": ["x", "limits"]}
    with pytest.raises(ToolError, match="at most 50"):
        tools.call(
            "apply_changes",
            {
                "description": "Ticks",
                "operations": [{**step, "value": 1}, {**wide, "value": [0, 10_000]}],
            },
        )
    assert dumps(workspace.project) == before
    tools.call(
        "set_field", {"object_id": axes, "path": ["x", "major_step"], "value": 2}
    )
    assert workspace.project.figures[0].axes[0].x.major_step == 2.0


def test_a_tick_problem_from_the_file_does_not_block_other_changes(
    tools, workspace
) -> None:
    from figscribe.model import AxisSpec

    axes = workspace.project.figures[0].axes[0]
    axes.x = AxisSpec(limits=(0.0, 10_000.0), major_step=1.0)  # as loaded
    result = tools.call(
        "set_field", {"object_id": axes.id, "path": ["y", "label"], "value": "U"}
    )
    assert any("major ticks" in problem for problem in result["problems"])


@pytest.mark.parametrize(
    ("object_id", "path", "message"),
    [
        ("nope", ["name"], "no object"),
        (None, [], "empty"),
        (None, ["no_field"], "no field"),
        (None, ["figures", "name"], "not an object"),
    ],
)
def test_set_field_refuses_bad_addresses(
    tools, workspace, object_id, path, message
) -> None:
    before = dumps(workspace.project)
    with pytest.raises(ToolError, match=message):
        tools.call("set_field", {"object_id": object_id, "path": path, "value": "x"})
    assert dumps(workspace.project) == before


def test_problems_are_reported_after_a_change(tools, workspace) -> None:
    figure, *_ = _ids(workspace)
    path = ["layout", "width_ratios"]  # two ratios for one column
    result = tools.call(
        "set_field", {"object_id": figure, "path": path, "value": [1.0, 2.0]}
    )
    assert result["problems"] and "grid" in result["problems"][0]


def test_a_panel_outside_the_grid_is_refused(tools, workspace) -> None:
    _, axes, _, _ = _ids(workspace)
    with pytest.raises(ToolError, match="outside the grid"):
        tools.call("set_field", {"object_id": axes, "path": ["row"], "value": 4})


# --- insert, remove, move ------------------------------------------------------


def test_a_style_string_matplotlib_refuses_is_refused(tools, workspace) -> None:
    _, _, artist, _ = _ids(workspace)
    with pytest.raises(ToolError, match="'blu' is not a color"):
        tools.call(
            "set_field", {"object_id": artist, "path": ["color"], "value": "blu"}
        )


def test_insert_a_plot(tools, workspace) -> None:
    _, axes, _, source = _ids(workspace)
    line = {
        "kind": "line",
        "x": {"source": source, "column": "t"},
        "y": {"source": source, "column": "U"},
        "color": "tab:red",
    }
    result = tools.call(
        "insert", {"parent_id": axes, "field": "artists", "object": line}
    )
    added = workspace.project.figures[0].axes[0].artists[-1]
    assert isinstance(added, LinePlot) and added.id == result["id"]
    assert result["undo_step"] == "Add line plot"


@pytest.mark.parametrize(
    ("field", "object", "message"),
    [
        ("artists", {"kind": "sparkle"}, "invalid artists"),
        (
            "artists",
            {"kind": "annotation", "text": "x", "position": [0, 0], "bogus": 1},
            "Extra",
        ),
        ("sources", {}, "imported by the user"),
        ("name", {}, "no list"),
    ],
)
def test_insert_refuses_bad_objects(tools, workspace, field, object, message) -> None:
    _, axes, _, _ = _ids(workspace)
    parent = None if field == "sources" else axes
    before = dumps(workspace.project)
    with pytest.raises(ToolError, match=message):
        tools.call("insert", {"parent_id": parent, "field": field, "object": object})
    assert dumps(workspace.project) == before


def test_insert_refuses_a_taken_id(tools, workspace) -> None:
    figure, axes, _, _ = _ids(workspace)
    with pytest.raises(ToolError, match="already"):
        tools.call(
            "insert", {"parent_id": figure, "field": "axes", "object": {"id": axes}}
        )


def test_remove_takes_dependents_along(tools, workspace) -> None:
    _, axes, data, _ = _ids(workspace)
    fit = tools.call(
        "fit", {"target_id": data, "model": {"kind": "predefined", "name": "gaussian"}}
    )
    result = tools.call("remove", {"object_id": data})
    assert set(result["removed"]) == {data, fit["id"]}
    assert workspace.project.figures[0].axes[0].artists == []


def test_sources_and_unknown_ids_are_not_removed(tools, workspace) -> None:
    *_, source = _ids(workspace)
    with pytest.raises(ToolError, match="cannot be removed"):
        tools.call("remove", {"object_id": source})
    with pytest.raises(ToolError, match="no object"):
        tools.call("remove", {"object_id": "nope"})


def test_move(tools, workspace) -> None:
    _, axes, data, _ = _ids(workspace)
    fit = tools.call(
        "fit", {"target_id": data, "model": {"kind": "predefined", "name": "gaussian"}}
    )
    tools.call("move", {"object_id": fit["id"], "index": 0})
    assert workspace.project.figures[0].axes[0].artists[0].id == fit["id"]


# --- fit -----------------------------------------------------------------------


def test_fit_adds_a_fitted_curve_as_one_step(tools, workspace) -> None:
    _, _, data, _ = _ids(workspace)
    before = dumps(workspace.project)
    result = tools.call(
        "fit",
        {
            "target_id": data,
            "model": {"kind": "predefined", "name": "gaussian"},
            "label": "Gauss",
        },
    )
    assert set(result["result"]["parameters"]) == {"a", "mu", "sigma", "c"}
    assert result["result"]["converged"]
    assert result["result"]["parameters"]["mu"] == pytest.approx(5.0, abs=0.3)
    assert result["undo_step"] == "Fit gaussian"
    workspace.undo()
    assert dumps(workspace.project) == before


def test_fit_with_an_expression(tools, workspace) -> None:
    _, _, data, _ = _ids(workspace)
    model = {
        "kind": "expression",
        "expression": "a * exp(-(x - m)**2 / (2 * s**2))",
        "parameters": ["a", "m", "s"],
    }
    result = tools.call(
        "fit",
        {"target_id": data, "model": model, "initial_values": {"a": 1, "m": 5, "s": 1}},
    )
    assert result["result"]["converged"]


def test_fit_refuses_a_bad_model_or_target(tools, workspace) -> None:
    figure, _, data, _ = _ids(workspace)
    with pytest.raises(ToolError, match="invalid model"):
        tools.call(
            "fit", {"target_id": data, "model": {"kind": "predefined", "name": "sine"}}
        )
    with pytest.raises(ToolError, match="no plot"):
        tools.call(
            "fit",
            {"target_id": figure, "model": {"kind": "predefined", "name": "linear"}},
        )
    with pytest.raises(ToolError, match="unknown function '__import__'"):
        tools.call(
            "fit",
            {
                "target_id": data,
                "model": {
                    "kind": "expression",
                    "expression": "__import__('os')",
                    "parameters": ["a"],
                },
            },
        )


# --- apply_changes -------------------------------------------------------------


def test_apply_changes_builds_a_second_panel_in_one_step(tools, workspace) -> None:
    figure, _, data, source = _ids(workspace)
    before = dumps(workspace.project)
    result = tools.call(
        "apply_changes",
        {
            "description": "Add a panel below",
            "operations": [
                {
                    "op": "set_field",
                    "object_id": figure,
                    "path": ["layout", "rows"],
                    "value": 2,
                },
                {
                    "op": "set_field",
                    "object_id": figure,
                    "path": ["height_mm"],
                    "value": 90,
                },
                {
                    "op": "insert",
                    "parent_id": figure,
                    "field": "axes",
                    "object": {"id": "lower", "row": 1},
                },
                {
                    "op": "insert",
                    "parent_id": "lower",
                    "field": "artists",
                    "object": {
                        "kind": "scatter",
                        "x": {"source": source, "column": "t"},
                        "y": {"source": source, "column": "dU"},
                    },
                },
                {
                    "op": "fit",
                    "target_id": data,
                    "model": {"kind": "predefined", "name": "gaussian"},
                },
            ],
        },
    )
    project = workspace.project
    assert project.figures[0].layout.rows == 2
    assert [a.id for a in project.figures[0].axes] == [
        project.figures[0].axes[0].id,
        "lower",
    ]
    assert len(project.figures[0].axes[0].artists) == 2  # data and fit
    assert result["ids"][2] == "lower" and result["ids"][4] is not None
    assert result["problems"] == []
    assert workspace.history.undo_text == "Add a panel below"

    workspace.undo()
    assert dumps(workspace.project) == before


def test_apply_changes_is_all_or_nothing(tools, workspace) -> None:
    figure, *_ = _ids(workspace)
    before = dumps(workspace.project)
    with pytest.raises(
        ToolError, match=r"operation 1 \('set_field'\).*nothing was changed"
    ):
        tools.call(
            "apply_changes",
            {
                "description": "Broken",
                "operations": [
                    {
                        "op": "set_field",
                        "object_id": figure,
                        "path": ["name"],
                        "value": "A",
                    },
                    {
                        "op": "set_field",
                        "object_id": figure,
                        "path": ["dpi"],
                        "value": 0,
                    },
                ],
            },
        )
    assert dumps(workspace.project) == before
    assert not workspace.history.can_undo


@pytest.mark.parametrize(
    ("operations", "message"),
    [
        ([], "no operations"),
        ([{"op": "explode"}], "unknown op"),
        ([{"op": "move"}], "operation 0"),
    ],
)
def test_apply_changes_refuses_bad_operations(tools, operations, message) -> None:
    with pytest.raises(ToolError, match=message):
        tools.call("apply_changes", {"description": "x", "operations": operations})


# --- the rest ------------------------------------------------------------------


def test_undo_takes_back_the_last_change(tools, workspace) -> None:
    figure, *_ = _ids(workspace)
    with pytest.raises(ToolError, match="nothing to undo"):
        tools.call("undo", {})
    tools.call("set_field", {"object_id": figure, "path": ["name"], "value": "A"})
    assert tools.call("undo", {})["undone"] == "Set name"
    assert workspace.project.figures[0].name == "Scan"


def test_unknown_tools_and_arguments_are_refused(tools) -> None:
    with pytest.raises(ToolError, match="unknown tool"):
        tools.call("format_disk", {})
    with pytest.raises(ToolError, match="bad arguments"):
        tools.call("set_field", {"nonsense": 1})


def test_error_bars_survive_a_roundtrip_through_json(tools, workspace) -> None:
    """What get_project returns can be inserted again, as an assistant would."""
    _, axes, data, _ = _ids(workspace)
    shown = tools.call("get_project", {})["project"]
    artist = shown["figures"][0]["axes"][0]["artists"][0]
    artist["id"] = "copy"
    tools.call("insert", {"parent_id": axes, "field": "artists", "object": artist})
    assert isinstance(workspace.project.figures[0].axes[0].artists[-1], ErrorbarPlot)


# --- found while hardening -----------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("set_field", {"object_id": None, "path": "name", "value": "x"}, "path"),
        ("move", {"object_id": "a", "index": "two"}, "index"),
        (
            "apply_changes",
            {"description": "x", "operations": {"op": "move"}},
            "operations",
        ),
        ("apply_changes", {"description": "x", "operations": ["move"]}, "operations.0"),
        ("insert", {"parent_id": None, "field": "figures", "object": "fig"}, "object"),
    ],
)
def test_arguments_of_the_wrong_type_are_refused(
    tools, workspace, tool, arguments, message
) -> None:
    before = dumps(workspace.project)
    with pytest.raises(ToolError, match=f"bad arguments for {tool}: {message}"):
        tools.call(tool, arguments)
    assert dumps(workspace.project) == before


def test_operations_are_checked_like_single_calls(tools, workspace) -> None:
    figure, *_ = _ids(workspace)
    with pytest.raises(
        ToolError, match=r"operation 0 \('set_field'\).*bad arguments.*path"
    ):
        tools.call(
            "apply_changes",
            {
                "description": "x",
                "operations": [
                    {"op": "set_field", "object_id": figure, "path": "name", "value": 1}
                ],
            },
        )
    with pytest.raises(ToolError, match="operation 0.*unexpected keyword"):
        tools.call(
            "apply_changes",
            {
                "description": "x",
                "operations": [
                    {"op": "move", "object_id": figure, "index": 0, "where": 1}
                ],
            },
        )


@pytest.mark.parametrize("field", ["path", "sha256", "columns"])
def test_a_source_cannot_be_pointed_elsewhere(tools, workspace, field) -> None:
    *_, source = _ids(workspace)
    value = (
        ["a"] if field == "columns" else "/etc/passwd" if field == "path" else "0" * 64
    )
    with pytest.raises(ToolError, match="importing the file"):
        tools.call("set_field", {"object_id": source, "path": [field], "value": value})


def test_how_a_source_is_read_may_change(tools, workspace) -> None:
    *_, source = _ids(workspace)
    tools.call("set_field", {"object_id": source, "path": ["comment"], "value": "%"})
    assert workspace.project.sources[0].comment == "%"


def test_a_missing_data_file_is_a_refusal_not_a_crash(tools, workspace) -> None:
    _, _, data, _ = _ids(workspace)
    (workspace.base_dir / "scan.csv").unlink()
    with pytest.raises(ToolError, match="scan.csv"):
        tools.call(
            "fit",
            {"target_id": data, "model": {"kind": "predefined", "name": "linear"}},
        )
    with pytest.raises(ToolError, match=r"operation 0 \('fit'\).*scan.csv"):
        tools.call(
            "apply_changes",
            {
                "description": "x",
                "operations": [
                    {
                        "op": "fit",
                        "target_id": data,
                        "model": {"kind": "predefined", "name": "linear"},
                    }
                ],
            },
        )


def test_reading_the_tool_list_stays_light() -> None:
    """`figscribe mcp` needs the tool list only; it must not load the heavy parts."""
    import subprocess
    import sys

    heavy = "('matplotlib', 'scipy', 'PySide6')"
    code = (
        "import sys, figscribe.tools as t; t.TOOLS; "
        f"print(sorted(m for m in {heavy} if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_a_changed_data_file_can_be_taken_as_it_is_now(
    tools, workspace, example: Path
) -> None:
    from figscribe.io import sha256_of

    csv = example.parent / "scan.csv"
    csv.write_text(csv.read_text(encoding="utf-8") + "10.25,0.01,0.04\n", "utf-8")
    problems = tools.call("get_project", {})["problems"]
    assert any("scan.csv has changed" in problem for problem in problems)

    source = workspace.project.sources[0].id
    result = tools.call("use_new_data_version", {"source_id": source})
    assert workspace.project.sources[0].sha256 == sha256_of(csv)
    assert workspace.project.sources[0].row_count == 42
    assert result["undo_step"] == "Use the new version of scan.csv"
    assert result["problems"] == []
    with pytest.raises(ToolError, match="has not changed"):
        tools.call("use_new_data_version", {"source_id": source})


def test_a_reading_option_reads_the_file_or_is_refused(tools, workspace) -> None:
    source = workspace.project.sources[0]
    with pytest.raises(ToolError, match="cannot read"):
        tools.call(
            "set_field", {"object_id": source.id, "path": ["delimiter"], "value": "2"}
        )
    assert workspace.project.sources[0] == source
    tools.call("set_field", {"object_id": source.id, "path": ["comment"], "value": "%"})
    assert workspace.project.sources[0].comment == "%"
    assert workspace.history.undo_text.startswith("Read ")


def test_apply_changes_reads_the_file_as_set_field_does(tools, workspace) -> None:
    source = workspace.project.sources[0]
    change = {"op": "set_field", "object_id": source.id, "path": ["delimiter"]}
    with pytest.raises(ToolError, match="cannot read"):
        tools.call(
            "apply_changes",
            {"description": "Separator", "operations": [{**change, "value": "2"}]},
        )
    assert workspace.project.sources[0] == source


def test_a_fit_can_hold_and_bound_parameters(tools, workspace) -> None:
    _, _, artist, _ = _ids(workspace)
    result = tools.call(
        "fit",
        {
            "target_id": artist,
            "model": {"kind": "predefined", "name": "gaussian"},
            "initial_values": {"c": 0.0},
            "fixed": ["c"],
            "bounds": {"sigma": [0.1, None]},
        },
    )
    assert result["result"]["parameters"]["c"] == 0.0
    fit = find(workspace.project, result["id"])
    assert fit.fixed == ["c"] and fit.parameter_bounds == {"sigma": (0.1, None)}


def test_a_fit_can_use_part_of_the_data(tools, workspace) -> None:
    _, _, artist, _ = _ids(workspace)
    result = tools.call(
        "fit",
        {
            "target_id": artist,
            "model": {"kind": "predefined", "name": "gaussian"},
            "fit_range": [2.0, 8.0],
        },
    )
    assert find(workspace.project, result["id"]).fit_range == (2.0, 8.0)


def test_leaving_points_out_fits_the_plot_again(tools, workspace) -> None:
    _, _, artist, _ = _ids(workspace)
    fitted = tools.call(
        "fit",
        {"target_id": artist, "model": {"kind": "predefined", "name": "gaussian"}},
    )
    before = find(workspace.project, fitted["id"]).result
    tools.call(
        "set_field", {"object_id": artist, "path": ["left_out"], "value": [0, 1, 2]}
    )
    assert find(workspace.project, artist).left_out == [0, 1, 2]
    assert find(workspace.project, fitted["id"]).result != before
