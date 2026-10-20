"""Reading NumPy sources: .npy and .npz files, as columns and as 2-D data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from figscribe.io import DataChangedError, DataError, load_data, numpy_source
from figscribe.model import ArrayRef, ColumnRef, Project


def _project(*sources) -> Project:
    return Project(sources=list(sources))


def test_an_npy_array_is_read_whole_and_by_column(tmp_path: Path) -> None:
    grid = np.arange(12.0).reshape(3, 4)
    np.save(tmp_path / "grid.npy", grid)
    source = numpy_source(tmp_path / "grid.npy", tmp_path)
    assert source.format == "npy" and source.array is None
    assert source.path == "grid.npy"
    data = load_data(_project(source), tmp_path)
    np.testing.assert_array_equal(data(ArrayRef(source=source.id)), grid)
    np.testing.assert_array_equal(
        data(ColumnRef(source=source.id, column=1)), grid[:, 1]
    )


def test_a_1d_array_is_one_column(tmp_path: Path) -> None:
    np.save(tmp_path / "t.npy", np.array([1, 2, 3]))  # integers become floats
    source = numpy_source(tmp_path / "t.npy", tmp_path)
    data = load_data(_project(source), tmp_path)
    values = data(ColumnRef(source=source.id, column=0))
    assert values.dtype == float
    np.testing.assert_array_equal(values, [1.0, 2.0, 3.0])


def test_an_npz_file_gives_its_first_or_the_named_array(tmp_path: Path) -> None:
    path = tmp_path / "scan.npz"
    np.savez(path, t=np.arange(3.0), image=np.eye(3))
    first = numpy_source(path, tmp_path)
    assert first.format == "npz" and first.array == "t"
    image = numpy_source(path, tmp_path, array="image")
    data = load_data(_project(first, image), tmp_path)
    np.testing.assert_array_equal(data(ArrayRef(source=image.id)), np.eye(3))
    np.testing.assert_array_equal(
        data(ArrayRef(source=first.id, key="image")), np.eye(3)
    )
    with pytest.raises(DataError, match="no array 'nope'"):
        numpy_source(path, tmp_path, array="nope")


def test_more_than_two_dimensions_is_refused(tmp_path: Path) -> None:
    np.save(tmp_path / "cube.npy", np.zeros((2, 2, 2)))
    with pytest.raises(DataError, match="3-D"):
        numpy_source(tmp_path / "cube.npy", tmp_path)


def test_pickled_objects_are_never_loaded(tmp_path: Path) -> None:
    np.save(tmp_path / "objects.npy", np.array([{"a": 1}], dtype=object))
    with pytest.raises(DataError, match="cannot read"):
        numpy_source(tmp_path / "objects.npy", tmp_path)


def test_a_changed_file_is_refused(tmp_path: Path) -> None:
    np.save(tmp_path / "a.npy", np.zeros(3))
    source = numpy_source(tmp_path / "a.npy", tmp_path)
    np.save(tmp_path / "a.npy", np.ones(3))
    with pytest.raises(DataChangedError):
        load_data(_project(source), tmp_path)(ArrayRef(source=source.id))
