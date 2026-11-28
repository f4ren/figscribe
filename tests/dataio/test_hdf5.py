"""HDF5 files as data (decision 0081)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from figscribe.io import DataChangedError, DataError, load_data
from figscribe.io.hdf5file import entries, hdf5_source, units
from figscribe.model import (
    ArrayRef,
    ColumnRef,
    Hdf5Source,
    Project,
    dumps,
    loads,
)
from tests.hdf5files import write_h5, write_scan


@pytest.fixture
def scan(tmp_path: Path) -> Path:
    return write_scan(tmp_path / "scan.h5")


def _data(tmp_path: Path, source: Hdf5Source):
    return load_data(Project(sources=[source]), tmp_path)


def _column(tmp_path: Path, source: Hdf5Source, column: str | int) -> np.ndarray:
    return _data(tmp_path, source)(ColumnRef(source=source.id, column=column))


def test_a_group_is_a_table_of_its_one_dimensional_numbers(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/run1")
    assert (source.format, source.path, source.dataset) == ("hdf5", "scan.h5", "/run1")
    assert source.columns == ["U", "counts", "t"]
    assert source.row_count == 9
    values = _column(scan.parent, source, "U")
    assert values.dtype == np.float64
    np.testing.assert_allclose(values, 3 * np.linspace(0, 4, 9) + 1)
    np.testing.assert_array_equal(_column(scan.parent, source, "counts"), range(9))
    table = _data(scan.parent, source)(ArrayRef(source=source.id))
    assert table.shape == (9, 3)


def test_a_table_of_records_has_its_numbers_as_columns(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/table")
    assert source.columns == ["f", "n"]
    assert source.row_count == 4
    np.testing.assert_array_equal(_column(scan.parent, source, "n"), [4, 3, 2, 1])
    table = _data(scan.parent, source)(ArrayRef(source=source.id))
    np.testing.assert_array_equal(table[:, 0], [10, 20, 30, 40])


def test_one_dataset_is_one_column_named_after_it(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/run1/U")
    assert source.columns == ["U"]
    assert source.row_count == 9
    assert _column(scan.parent, source, "U").shape == (9,)
    assert _data(scan.parent, source)(ArrayRef(source=source.id)).shape == (9,)


def test_a_two_dimensional_dataset_is_read_by_number(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/image")
    assert source.columns == []
    assert source.row_count == 3
    data = _data(scan.parent, source)
    assert data(ArrayRef(source=source.id)).shape == (3, 4)
    np.testing.assert_array_equal(
        data(ColumnRef(source=source.id, column=1)), [1, 5, 9]
    )
    with pytest.raises(DataError, match="out of range"):
        data(ColumnRef(source=source.id, column=4))


def test_datasets_of_different_lengths_are_columns_but_no_table(
    tmp_path: Path,
) -> None:
    path = write_h5(tmp_path / "m.h5", {"f": np.arange(5.0), "t": np.arange(8.0)})
    source = hdf5_source(path, tmp_path)
    assert (source.dataset, source.columns, source.row_count) == ("/", ["f", "t"], 8)
    assert len(_column(tmp_path, source, "f")) == 5
    assert len(_column(tmp_path, source, "t")) == 8
    with pytest.raises(DataError, match="different lengths"):
        _data(tmp_path, source)(ArrayRef(source=source.id))


@pytest.mark.parametrize(
    ("datasets", "chosen"),
    [
        # The first group that holds a pair of equal columns.
        ({"a/x": [1.0], "b/x": [1.0, 2], "b/y": [3.0, 4]}, "/b"),
        # No pair anywhere: a table of records, then an image, then a column.
        ({"note": "x", "m": np.zeros((2, 2)), "v": [1.0, 2]}, "/m"),
        ({"note": "x", "deep/v": [1.0, 2]}, "/deep/v"),
    ],
)
def test_what_is_chosen_without_being_asked(
    tmp_path: Path, datasets: dict, chosen: str
) -> None:
    path = write_h5(tmp_path / "m.h5", datasets)
    assert hdf5_source(path, tmp_path).dataset == chosen


def test_a_file_with_nothing_to_plot(tmp_path: Path) -> None:
    path = write_h5(tmp_path / "m.h5", {"note": "warm", "gain": 2.0})
    with pytest.raises(DataError, match="no numbers that can be plotted"):
        hdf5_source(path, tmp_path)


def test_the_tree_says_what_each_entry_gives_or_why_not(scan: Path) -> None:
    found = {e.path: e for e in entries(scan.read_bytes(), scan.name)}
    assert list(found)[:2] == ["/", "/image"]
    assert found["/run1"].columns == ["U", "counts", "t"]
    assert found["/run1"].left_out == {
        "comment": "it holds one value only",
        "gain": "it holds one value only",
    }
    assert found["/run1/U"].columns == ["U"]
    assert found["/run1/gain"].problem == "it holds one value only"
    assert found["/image"].columns == [] and found["/image"].problem == ""
    assert found["/table"].columns == ["f", "n"]
    assert found["/table"].left_out == {"name": "it holds text"}
    assert "no one-dimensional numbers" in found["/"].problem


@pytest.mark.parametrize(
    ("value", "why"),
    [
        (np.array(["a", "b"], dtype=h5py.string_dtype()), "it holds text"),
        (np.array([b"a", b"b"]), "it holds text"),
        (np.array([True, False]), "it holds true or false"),
        (np.array([1j, 2]), "it holds complex numbers"),
        (
            np.array([0, 1], dtype=h5py.enum_dtype({"A": 0, "B": 1}, basetype="i1")),
            "it holds named values",
        ),
        (np.zeros((2, 2, 2)), "it has 3 dimensions"),
        (np.zeros(0), "it is empty"),
        (h5py.Empty("f8"), "it is empty"),
    ],
)
def test_what_is_no_column(tmp_path: Path, value, why: str) -> None:
    path = write_h5(tmp_path / "m.h5", {"good": [1.0, 2], "odd": value})
    with pytest.raises(DataError, match=why):
        hdf5_source(path, tmp_path, dataset="/odd")
    assert hdf5_source(path, tmp_path, dataset="/").columns == ["good"]


def _tricks(tmp_path: Path) -> Path:
    """Datasets whose values are not in the file. The same paths exist here as
    in the other file: followed from the bytes in memory, an external link
    leads back into this file."""
    write_h5(tmp_path / "other.h5", {"t": [9.0, 9], "far/t": [9.0, 9]})
    np.array([7.0, 7]).tofile(tmp_path / "raw.bin")
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        file["t"] = [1.0, 2]
        file["far/t"] = [1.0, 2]
        file["link"] = h5py.ExternalLink("other.h5", "/t")
        file["via"] = h5py.SoftLink("/link")
        file["linked group"] = h5py.ExternalLink("other.h5", "/far")
        layout = h5py.VirtualLayout(shape=(2,), dtype="f8")
        layout[:] = h5py.VirtualSource("other.h5", "t", shape=(2,))
        file.create_virtual_dataset("virtual", layout)
        file.create_dataset(
            "outside", shape=(2,), dtype="f8", external=[("raw.bin", 0, 16)]
        )
        file["nowhere"] = h5py.SoftLink("/gone")
        file["loop"] = h5py.SoftLink("/loop")
        file["alias"] = h5py.SoftLink("/t")
    return path


ELSEWHERE = {
    "/link": "in another file",
    "/via": "in another file",
    "/linked group": "in another file",
    "/linked group/t": "in another file",
    "/virtual": "virtual",
    "/outside": "outside the file",
    "/nowhere": "leads nowhere",
    "/loop": "leads nowhere",
}


@pytest.mark.parametrize(("dataset", "why"), ELSEWHERE.items())
def test_values_that_are_not_in_the_file_are_refused(
    tmp_path: Path, dataset: str, why: str
) -> None:
    path = _tricks(tmp_path)
    with pytest.raises(DataError, match=why):
        hdf5_source(path, tmp_path, dataset=dataset)
    # Nor from a project file that names one.
    source = hdf5_source(path, tmp_path, dataset="/t").model_copy(
        update={"dataset": dataset}
    )
    with pytest.raises(DataError, match=why):
        _column(tmp_path, source, 0)


def test_a_group_leaves_out_values_that_are_elsewhere(tmp_path: Path) -> None:
    path = _tricks(tmp_path)
    source = hdf5_source(path, tmp_path, dataset="/")
    assert source.columns == ["alias", "t"]  # a link within the file is fine
    np.testing.assert_array_equal(_column(tmp_path, source, "alias"), [1, 2])
    root = entries(path.read_bytes(), path.name)[0]
    assert set(root.left_out) >= {"link", "via", "virtual", "outside", "nowhere"}
    # A column named by hand in the project file is checked too.
    wrong = source.model_copy(update={"columns": ["link"]})
    with pytest.raises(DataError, match="in another file"):
        _column(tmp_path, wrong, "link")


def test_a_group_that_holds_itself(tmp_path: Path) -> None:
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        group = file.create_group("a")
        group["again"] = group
        group["x"] = [1.0, 2]
    paths = [e.path for e in entries(path.read_bytes(), path.name)]
    assert paths == ["/", "/a", "/a/again", "/a/x"]


def test_a_filter_that_is_not_there(tmp_path: Path) -> None:
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        plist = h5py.h5p.create(h5py.h5p.DATASET_CREATE)
        plist.set_chunk((2,))
        # Zstandard, a plugin h5py does not carry. Optional, so that HDF5 makes
        # the dataset without it; the chunk below says it went through it.
        plist.set_filter(32015, h5py.h5z.FLAG_OPTIONAL)
        space = h5py.h5s.create_simple((2,))
        made = h5py.h5d.create(file.id, b"z", h5py.h5t.NATIVE_DOUBLE, space, dcpl=plist)
        made.write_direct_chunk((0,), bytes(16))
    with pytest.raises(DataError, match="compression"):
        hdf5_source(path, tmp_path, dataset="/z")


@pytest.mark.parametrize("compression", ["gzip", "lzf"])
def test_the_compression_h5py_carries(tmp_path: Path, compression: str) -> None:
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        file.create_dataset("x", data=np.arange(100.0), compression=compression)
    source = hdf5_source(path, tmp_path)
    np.testing.assert_array_equal(_column(tmp_path, source, "x"), range(100))


def test_units_from_the_attributes(tmp_path: Path) -> None:
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        for name, value in {
            "text": "mV",
            "utf8": np.bytes_("µV".encode()),
            "latin": np.bytes_("µA".encode("latin-1")),
            "array": np.array([b"s"]),
            "number": 3,
            "blank": "  ",
        }.items():
            file[name] = [1.0, 2]
            file[name].attrs["units"] = value
        file["other"] = [1.0, 2]
        file["other"].attrs["unit"] = "K"
        file["none"] = [1.0, 2]
    source = hdf5_source(path, tmp_path)
    found = dict(zip(source.columns, units(source, path.read_bytes()), strict=True))
    assert found == {
        "array": "s",
        "blank": "",
        "latin": "µA",
        "none": "",
        "number": "",
        "other": "K",
        "text": "mV",
        "utf8": "µV",
    }


def test_a_changed_file_is_refused(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/run1")
    write_h5(scan, {"run1/t": [1.0, 2]})
    with pytest.raises(DataChangedError):
        _column(scan.parent, source, "t")


@pytest.mark.parametrize("content", [b"", b"x,y\n1,2\n", b"\x89HDF\r\n\x1a\n"])
def test_a_file_that_is_no_hdf5(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "bad.h5"
    path.write_bytes(content)
    with pytest.raises(DataError, match="cannot read bad.h5"):
        hdf5_source(path, tmp_path)


def test_a_dataset_that_is_not_there_names_those_that_are(scan: Path) -> None:
    with pytest.raises(DataError, match="/run2.*/run1"):
        hdf5_source(scan, scan.parent, dataset="/run2")


def test_the_project_keeps_the_source(scan: Path) -> None:
    source = hdf5_source(scan, scan.parent, dataset="/run1")
    project = Project(sources=[source])
    assert loads(dumps(project)).sources == [source]
