"""Cross-object checks that per-object validation cannot express."""

from __future__ import annotations

from figscribe.model import (
    Annotation,
    ArrayRef,
    Axes,
    AxisSpec,
    ColorMesh,
    ColumnRef,
    Figure,
    GridLayout,
    Histogram,
    ImagePlot,
    LinePlot,
    Project,
    ResidualPlot,
    validate_references,
)


def test_sound_project_has_no_issues(project: Project) -> None:
    assert validate_references(project) == []


def test_unknown_data_source_is_reported(project: Project) -> None:
    artist = project.figures[0].axes[0].artists[0]
    artist.x = ColumnRef(source="nope", column="t")

    issues = validate_references(project)
    assert len(issues) == 1
    assert issues[0].location == "figures[0].axes[0].artists[0].x"
    assert issues[0].object_id == artist.id
    assert "unknown data source" in issues[0].message


def test_fit_target_outside_its_axes_is_reported(project: Project) -> None:
    fit = project.figures[0].axes[0].artists[1]
    fit.target = "elsewhere"

    issues = validate_references(project)
    assert [i.location for i in issues] == ["figures[0].axes[0].artists[1].target"]


def test_residual_target_must_be_a_fit(project: Project) -> None:
    residuals = project.figures[0].axes[1].artists[0]
    assert isinstance(residuals, ResidualPlot)
    residuals.target = project.figures[0].axes[0].artists[0].id  # the data, not the fit

    issues = validate_references(project)
    assert "not a fit" in issues[0].message


def test_decimal_separator_equal_to_delimiter_is_reported(project: Project) -> None:
    project.sources[0].decimal = ","

    issues = validate_references(project)
    assert [i.location for i in issues] == ["sources[0].decimal"]
    assert issues[0].object_id == project.sources[0].id


def test_right_axis_without_y_right_is_reported(project: Project) -> None:
    project.figures[0].axes[0].artists[0].axis = "right"

    issues = validate_references(project)
    assert "no y_right" in issues[0].message


def test_right_axis_is_fine_once_declared(project: Project) -> None:
    axes = project.figures[0].axes[0]
    axes.y_right = AxisSpec(label="count")
    axes.artists[0].axis = "right"

    assert validate_references(project) == []


def test_axes_outside_the_grid_is_reported(project: Project) -> None:
    project.figures[0].axes[1].row = 5

    issues = validate_references(project)
    assert any("but the grid has 2" in i.message for i in issues)


def test_ratio_length_must_match_the_grid(project: Project) -> None:
    project.figures[0].layout.height_ratios = [1.0, 1.0, 1.0]

    issues = validate_references(project)
    assert issues[0].location == "figures[0].layout.height_ratios"


def test_duplicate_ids_are_reported(project: Project) -> None:
    axes = project.figures[0].axes[0]
    axes.artists[1].id = axes.artists[0].id

    issues = validate_references(project)
    assert any("duplicate id" in i.message for i in issues)


def test_tick_labels_need_matching_positions(project: Project) -> None:
    project.figures[0].axes[0].x = AxisSpec(ticks=[0.0, 1.0], tick_labels=["a"])

    issues = validate_references(project)
    assert "1 labels for 2 ticks" in issues[0].message


def test_tick_labels_without_positions_are_reported(project: Project) -> None:
    project.figures[0].axes[0].x = AxisSpec(tick_labels=["a"])

    issues = validate_references(project)
    assert "without tick positions" in issues[0].message


def test_bin_edges_must_increase(project: Project) -> None:
    source = project.sources[0]
    project.figures[0].axes[0].artists = [
        Histogram(values=ColumnRef(source=source.id, column="U"), bins=[0.0, 2.0, 1.0])
    ]

    issues = validate_references(project)
    assert "increase strictly" in issues[0].message


def test_issue_renders_readably(project: Project) -> None:
    project.figures[0].axes[0].artists[0].x = ColumnRef(source="nope", column="t")

    issue = validate_references(project)[0]
    assert str(issue).startswith("figures[0].axes[0].artists[0].x: ")


def test_several_issues_are_all_reported() -> None:
    bad = Project(
        figures=[
            Figure(
                layout=GridLayout(rows=1, cols=1),
                axes=[
                    Axes(
                        row=3,
                        artists=[
                            LinePlot(
                                x=ColumnRef(source="a", column=0),
                                y=ColumnRef(source="b", column=1),
                            )
                        ],
                    )
                ],
            )
        ]
    )
    assert len(validate_references(bad)) == 3


def test_fit_target_must_be_a_data_artist(project: Project) -> None:
    axes = project.figures[0].axes[0]
    note = Annotation(text="peak", position=(0.0, 1.0))
    axes.artists.append(note)
    axes.artists[1].target = note.id

    issues = validate_references(project)
    assert [i.location for i in issues] == ["figures[0].axes[0].artists[1].target"]
    assert "not a data artist" in issues[0].message


def test_data_refs_are_found_on_every_artist_type(project: Project) -> None:
    # Guards against a new artist type whose references the check forgets.
    missing = ColumnRef(source="nope", column=0)
    project.figures[0].axes[0].artists = [
        Histogram(values=missing),
        ImagePlot(data=ArrayRef(source="nope")),
        ColorMesh(c=ArrayRef(source="nope"), x=missing, y=missing),
    ]

    prefix = "figures[0].axes[0].artists"
    locations = [
        i.location
        for i in validate_references(project)
        if i.location.startswith(prefix)
    ]
    assert locations == [
        f"{prefix}[0].values",
        f"{prefix}[1].data",
        f"{prefix}[2].c",
        f"{prefix}[2].x",
        f"{prefix}[2].y",
    ]
