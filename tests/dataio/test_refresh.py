"""A data file that changed or moved after it was imported."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from figscribe.io.refresh import describe_change, source_state, use_new_version

from figscribe.commands import History
from figscribe.io import DataError, csv_source, sha256_of
from figscribe.io.numpyfile import numpy_source
from figscribe.model import ColumnRef, LinePlot, Project, loads

SCAN = "# a scan\nt;U;dU\ns;V;V\n0;1,5;0,1\n1;2,5;0,1\n"


def _project(tmp_path: Path, text: str = SCAN) -> Project:
    path = tmp_path / "scan.csv"
    path.write_bytes(text.encode())
    source = csv_source(
        path, tmp_path, delimiter=";", decimal=",", header_row=1, skip_rows=1
    )
    return Project(sources=[source])


def test_the_number_of_rows_is_recorded_on_import(tmp_path: Path) -> None:
    assert _project(tmp_path).sources[0].rows == 2
    np.save(tmp_path / "a.npy", np.zeros((7, 3)))
    assert numpy_source(tmp_path / "a.npy", tmp_path).rows == 7


def test_a_changed_file_is_told_from_a_missing_one(tmp_path: Path) -> None:
    source = _project(tmp_path).sources[0]
    assert source_state(source, tmp_path) == "ok"
    (tmp_path / "scan.csv").write_bytes((SCAN + "2;3,5;0,1\n").encode())
    assert source_state(source, tmp_path) == "changed"
    (tmp_path / "scan.csv").unlink()
    assert source_state(source, tmp_path) == "missing"


def test_the_new_version_is_one_step_and_keeps_how_the_file_is_read(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    old = project.sources[0].model_copy()
    (tmp_path / "scan.csv").write_bytes(
        b"# a scan\nt;U;dU;T\ns;V;V;K\n0;1,5;0,1;3\n1;2,5;0,1;3\n2;3;0,1;3\n"
    )
    history = History(project)
    history.push(use_new_version(project, old.id, tmp_path))

    new = project.sources[0]
    assert new.sha256 == sha256_of(tmp_path / "scan.csv")
    assert (new.rows, new.columns) == (3, ["t", "U", "dU", "T"])
    assert (new.delimiter, new.decimal, new.header_row) == (";", ",", 1)
    assert history.undo_text == "Use the new version of scan.csv"
    history.undo()
    assert project.sources[0] == old


def test_a_located_file_keeps_a_relative_path(tmp_path: Path) -> None:
    project = _project(tmp_path)
    moved = tmp_path / "raw" / "scan.csv"
    moved.parent.mkdir()
    (tmp_path / "scan.csv").rename(moved)
    assert source_state(project.sources[0], tmp_path) == "missing"

    history = History(project)
    history.push(use_new_version(project, project.sources[0].id, tmp_path, moved))
    assert project.sources[0].path == "raw/scan.csv"
    assert source_state(project.sources[0], tmp_path) == "ok"
    assert history.undo_text == "Locate scan.csv"


def test_a_new_version_that_cannot_be_read_changes_nothing(tmp_path: Path) -> None:
    project = _project(tmp_path)
    before = project.model_copy(deep=True)
    (tmp_path / "scan.csv").write_bytes(b"# a scan\nt;U;dU\ns;V;V\n0;high;0,1\n")
    with pytest.raises(DataError, match="scan.csv"):
        use_new_version(project, project.sources[0].id, tmp_path)
    assert project == before


def test_what_changed_is_said_in_rows_and_columns(tmp_path: Path) -> None:
    old = _project(tmp_path).sources[0]
    new = old.model_copy(update={"rows": 5, "columns": ["t", "U", "T"]})
    text = describe_change(old, new)
    assert "2 → 5 rows" in text
    assert "dU" in text and "T" in text

    unknown = old.model_copy(update={"rows": None})
    assert "unknown → 5 rows" in describe_change(unknown, new)


def test_a_plot_of_a_column_the_file_lost_is_reported(tmp_path: Path) -> None:
    from figscribe.model import Axes, Figure, validate_references
    from figscribe.model.validate import missing_columns

    project = _project(tmp_path)
    source = project.sources[0]
    plot = LinePlot(
        x=ColumnRef(source=source.id, column="t"),
        y=ColumnRef(source=source.id, column="dU"),
        label="noise",
    )
    project.figures = [Figure(axes=[Axes(artists=[plot])])]
    assert missing_columns(project) == []
    source.columns = ["t", "U"]

    assert missing_columns(project) == [(plot, "y", plot.y)]
    issues = validate_references(project)
    assert [i.location for i in issues] == ["figures[0].axes[0].artists[0].y"]
    assert "'dU'" in issues[0].message


def test_an_older_project_without_rows_still_loads(example: Path) -> None:
    project = loads(example.read_text(encoding="utf-8"))
    assert project.sources[0].rows is None
