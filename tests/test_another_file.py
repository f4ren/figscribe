"""Use another file: a data file's place taken by a different one."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from figscribe.commands import History
from figscribe.datafile import columns_to_choose, use_another_file
from figscribe.fit import add_fit, refit
from figscribe.io import DataError, csv_source, load_data, sha256_of
from figscribe.io.numpyfile import numpy_source
from figscribe.model import (
    ArrayRef,
    Axes,
    ColumnRef,
    ErrorbarPlot,
    ExpressionFit,
    Figure,
    FitCurve,
    ImagePlot,
    LinePlot,
    PredefinedFit,
    Project,
    dumps,
)
from figscribe.model.validate import missing_columns

T = np.linspace(0.0, 10.0, 11)


def _write(path: Path, slope: float, header: str = "t,U,dU", rows: int = 11) -> Path:
    lines = [f"{t:g},{slope * t + 1:g},0.1" for t in T[:rows]]
    path.write_text(header + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _project(tmp_path: Path, model=None, **plot) -> Project:
    """A plot of old.csv, U = 2 t + 1, with a fit."""
    source = csv_source(_write(tmp_path / "old.csv", 2.0), tmp_path)

    def col(name):
        return ColumnRef(source=source.id, column=name)

    line = ErrorbarPlot(x=col("t"), y=col("U"), yerr=col("dU"), label="data", **plot)
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[line])])])
    fit = FitCurve(
        target=line.id, model=model or PredefinedFit(name="linear"), label="fit"
    )
    add_fit(project, fit).apply(project)
    refit(project, fit.id, load_data(project, tmp_path)).apply(project)
    return project


def _parts(project: Project):
    return project.figures[0].axes[0].artists[:2]


def _use(project: Project, folder: Path, path: Path):
    return use_another_file(project, project.sources[0].id, folder, path)


def test_the_plots_and_their_fits_follow_the_other_file(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = dumps(project)
    other = _write(tmp_path / "new.csv", 5.0, rows=9)
    swap = _use(project, tmp_path, other)
    assert dumps(project) == before  # nothing until the command runs
    history = History(project)
    history.push(swap.command)

    source = project.sources[0]
    assert (source.path, source.row_count) == ("new.csv", 9)
    assert source.sha256 == sha256_of(other)
    _, fit = _parts(project)
    assert fit.result.parameters["a"] == pytest.approx(5.0)
    assert swap.notes == []
    assert history.undo_text == "Use another file for old.csv"
    history.undo()
    assert dumps(project) == before


def test_left_out_rows_meant_the_old_file(tmp_path: Path) -> None:
    project = _project(tmp_path, left_out=[3, 4], left_out_note="glitch")
    swap = _use(project, tmp_path, _write(tmp_path / "new.csv", 5.0))
    History(project).push(swap.command)
    line, _ = _parts(project)
    assert (line.left_out, line.left_out_note) == ([], None)
    (note,) = swap.notes
    assert "data" in note and "left-out rows" in note


def test_a_column_the_other_file_lacks_is_listed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    swap = _use(project, tmp_path, _write(tmp_path / "new.csv", 5.0, header="t,V,dU"))
    History(project).push(swap.command)
    assert [column.column for _, _, column in missing_columns(project)] == ["U"]
    _, fit = _parts(project)
    assert fit.result is None  # never the old curve over other data
    text = " ".join(swap.notes)
    assert "no column U" in text and "fit" in text and "not fitted" in text


def test_a_fit_that_fails_draws_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    swap = _use(project, tmp_path, _write(tmp_path / "new.csv", 5.0, rows=1))
    History(project).push(swap.command)
    assert _parts(project)[1].result is None
    assert any(note.startswith("fit is not fitted") for note in swap.notes)
    assert _name_of_unlabelled(tmp_path).startswith("The fit is not fitted")


def _name_of_unlabelled(tmp_path: Path) -> str:
    """The note about a fit without a label: it begins the sentence."""
    folder = tmp_path / "unlabelled"
    folder.mkdir()
    project = _project(folder)
    _parts(project)[1].label = None
    swap = _use(project, folder, _write(folder / "new.csv", 5.0, rows=1))
    return next(note for note in swap.notes if "not fitted" in note)


def test_an_own_formula_starts_from_the_values_it_had(tmp_path: Path) -> None:
    """Nothing can be guessed for it, and the user may have typed them."""
    model = ExpressionFit(expression="a * x + b", parameters=["a", "b"])
    project = _project(tmp_path, model=model)
    start = _parts(project)[1].initial_values
    start = {"a": 1.9, "b": 0.9}
    _parts(project)[1].initial_values = start
    History(project).push(
        _use(project, tmp_path, _write(tmp_path / "new.csv", 5.0)).command
    )
    assert _parts(project)[1].initial_values == start


def test_a_guessed_model_is_guessed_again(tmp_path: Path) -> None:
    project = _project(tmp_path)
    History(project).push(
        _use(project, tmp_path, _write(tmp_path / "new.csv", 5.0)).command
    )
    assert _parts(project)[1].initial_values["a"] == pytest.approx(5.0, rel=0.05)


def test_a_file_that_is_read_otherwise_changes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    other = tmp_path / "semicolons.csv"
    other.write_text("t;U;dU\n0;1,5;0,1\n1;2,5;0,1\n", encoding="utf-8")
    said = "separator ',', decimal mark '.', header line 1"
    with pytest.raises(DataError, match=said.replace(".", r"\.")):
        _use(project, tmp_path, other)


def test_the_same_file_again_is_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(DataError, match="already"):
        _use(project, tmp_path, tmp_path / "old.csv")


def _arrays(tmp_path: Path) -> Project:
    np.savez(tmp_path / "map.npz", counts=np.ones((3, 4)), x=np.arange(4.0))
    counts = numpy_source(tmp_path / "map.npz", tmp_path, array="counts")
    x = numpy_source(tmp_path / "map.npz", tmp_path, array="x")
    image = ImagePlot(data=ArrayRef(source=counts.id))
    line = LinePlot(
        x=ColumnRef(source=x.id, column=0), y=ColumnRef(source=x.id, column=0)
    )
    return Project(
        sources=[counts, x],
        figures=[Figure(axes=[Axes(artists=[image]), Axes(col=0, artists=[line])])],
    )


def test_every_array_of_an_archive_goes_over_together(tmp_path: Path) -> None:
    project = _arrays(tmp_path)
    np.savez(tmp_path / "run2.npz", counts=np.zeros((5, 4)), x=np.arange(4.0))
    History(project).push(_use(project, tmp_path, tmp_path / "run2.npz").command)
    assert [s.path for s in project.sources] == ["run2.npz", "run2.npz"]
    assert [s.array for s in project.sources] == ["counts", "x"]


@pytest.mark.parametrize(
    ("name", "said"), [("other.npz", "no array"), ("plain.npy", ".npz")]
)
def test_an_archive_needs_the_same_arrays(tmp_path: Path, name, said) -> None:
    project = _arrays(tmp_path)
    np.savez(tmp_path / "other.npz", counts=np.zeros((3, 4)))
    np.save(tmp_path / "plain.npy", np.zeros((3, 4)))
    before = dumps(project)
    with pytest.raises(DataError, match=said):
        _use(project, tmp_path, tmp_path / name)
    assert dumps(project) == before


# --- columns under other names ------------------------------------------------


def _renamed(tmp_path: Path, header: str = "time,signal,error") -> Path:
    return _write(tmp_path / "new.csv", 5.0, header=header)


def _two_figures(tmp_path: Path) -> Project:
    """The plot with its fit, and a second figure that draws U again."""
    project = _project(tmp_path)
    source = project.sources[0]
    line = LinePlot(
        x=ColumnRef(source=source.id, column="t"),
        y=ColumnRef(source=source.id, column="U"),
        label="again",
    )
    project.figures.append(Figure(name="Second", axes=[Axes(artists=[line])]))
    return project


def test_the_columns_to_choose_are_those_used_and_missing(tmp_path: Path) -> None:
    project = _two_figures(tmp_path)
    missing, columns = columns_to_choose(
        project, project.sources[0].id, tmp_path, _renamed(tmp_path, "t,signal,error")
    )
    assert columns == ["t", "signal", "error"]
    assert [(m.name, m.plots, m.default) for m in missing] == [
        ("U", ["data", "again"], "signal"),
        ("dU", ["data"], "error"),
    ]


def test_a_column_without_a_place_has_no_default(tmp_path: Path) -> None:
    project = _project(tmp_path)
    path = tmp_path / "new.csv"
    path.write_text("time,signal\n0,1\n1,2\n2,3\n", encoding="utf-8")
    missing, _ = columns_to_choose(project, project.sources[0].id, tmp_path, path)
    assert [(m.name, m.default) for m in missing] == [
        ("t", "time"),
        ("U", "signal"),
        ("dU", None),
    ]


def test_nothing_is_chosen_where_the_names_are_the_same(tmp_path: Path) -> None:
    project = _project(tmp_path)
    other = _write(tmp_path / "new.csv", 5.0)
    missing, _ = columns_to_choose(project, project.sources[0].id, tmp_path, other)
    assert missing == []


def test_the_chosen_columns_take_the_places_of_the_old(tmp_path: Path) -> None:
    project = _two_figures(tmp_path)
    before = dumps(project)
    columns = {"t": "time", "U": "signal", "dU": "error"}
    swap = use_another_file(
        project, project.sources[0].id, tmp_path, _renamed(tmp_path), columns
    )
    assert dumps(project) == before
    history = History(project)
    history.push(swap.command)

    line, fit = _parts(project)
    assert (line.x.column, line.y.column, line.yerr.column) == (
        "time",
        "signal",
        "error",
    )
    again = project.figures[1].axes[0].artists[0]
    assert (again.x.column, again.y.column) == ("time", "signal")
    assert swap.notes == [] and missing_columns(project) == []
    assert fit.result.parameters["a"] == pytest.approx(5.0)
    history.undo()
    assert dumps(project) == before


def test_a_column_left_out_of_the_choice_is_still_listed(tmp_path: Path) -> None:
    project = _project(tmp_path)
    swap = use_another_file(
        project,
        project.sources[0].id,
        tmp_path,
        _renamed(tmp_path),
        {"t": "time", "U": "signal", "dU": None},
    )
    History(project).push(swap.command)
    assert [column.column for _, _, column in missing_columns(project)] == ["dU"]
    assert swap.notes[0] == "The new file has no column dU, which data uses."
    assert swap.notes[1] == (
        "fit is not fitted on the new data: no column 'dU' in new.csv; known are "
        "'time', 'signal', 'error'."
    )
