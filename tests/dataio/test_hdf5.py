"""HDF5 files as data (decision 0081)."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from figscribe.datafile import columns_to_choose, parts_to_choose, use_another_file
from figscribe.io import DataChangedError, DataError, load_data
from figscribe.io.hdf5file import entries, hdf5_source, units
from figscribe.io.refresh import (
    describe_change,
    read_differently,
    reading_options,
    reread,
    use_new_version,
)
from figscribe.model import (
    AllanDeviationPlot,
    ArrayRef,
    Axes,
    ColumnRef,
    Figure,
    Hdf5Source,
    ImagePlot,
    LinePlot,
    Project,
    dumps,
    loads,
    validate_references,
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


def _plotted(tmp_path: Path, runs=("run1",), x="t", y="U") -> Project:
    """A figure of one line per run, each run a group with t and U."""
    path = tmp_path / "scan.h5"
    _write_runs(path, {run: [1.0, 2, 3] for run in runs})
    sources = [hdf5_source(path, tmp_path, dataset=f"/{run}") for run in runs]
    lines = [
        LinePlot(
            x=ColumnRef(source=source.id, column=x),
            y=ColumnRef(source=source.id, column=y),
            label=source.dataset,
        )
        for source in sources
    ]
    figure = Figure(name="scan", axes=[Axes(artists=lines)])
    return Project(sources=sources, figures=[figure])


def _write_runs(path: Path, runs: dict[str, list[float]], names=("t", "U")) -> Path:
    first, second = names
    datasets = {}
    for run, values in runs.items():
        datasets[f"{run}/{first}"] = np.array(values)
        datasets[f"{run}/{second}"] = np.array(values) * 2
    return write_h5(path, datasets)


def _y(project: Project, tmp_path: Path, line: int = 0) -> np.ndarray:
    return load_data(project, tmp_path)(project.figures[0].axes[0].artists[line].y)


def test_how_a_file_is_read_is_the_dataset(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    assert reading_options(project.sources[0]) == ("dataset",)


def test_another_dataset_of_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "scan.h5"
    _write_runs(path, {"run1": [1.0, 2, 3], "run2": [5.0, 6]})
    source = hdf5_source(path, tmp_path, dataset="/run1")
    project = Project(sources=[source])
    command = read_differently(project, source.id, "dataset", "run2", tmp_path)
    assert command.description == "Read scan.h5 with another dataset"
    command.apply(project)
    assert (project.sources[0].dataset, project.sources[0].row_count) == ("/run2", 2)


def test_a_dataset_that_is_no_data_changes_nothing(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    with pytest.raises(DataError, match="no '/nope'"):
        read_differently(project, project.sources[0].id, "dataset", "/nope", tmp_path)


def test_the_new_version_of_a_changed_file(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    _write_runs(tmp_path / "scan.h5", {"run1": [1.0, 2, 3, 4]})
    old = project.sources[0]
    use_new_version(project, old.id, tmp_path).apply(project)
    assert project.sources[0].row_count == 4
    np.testing.assert_array_equal(_y(project, tmp_path), [2, 4, 6, 8])


def test_the_only_group_with_the_columns_takes_the_place_of_a_renamed_one(
    tmp_path: Path,
) -> None:
    project = _plotted(tmp_path)
    _write_runs(tmp_path / "scan.h5", {"2026-11-28": [7.0, 8]})
    old = project.sources[0].model_copy()  # the command changes it in place
    use_new_version(project, old.id, tmp_path).apply(project)
    new = project.sources[0]
    assert new.dataset == "/2026-11-28"
    assert "The dataset is now '/2026-11-28'" in describe_change(old, new)


def test_a_dataset_that_is_gone_is_not_guessed_among_several(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    _write_runs(tmp_path / "scan.h5", {"a": [1.0], "b": [2.0]})
    with pytest.raises(DataError, match="no '/run1'; it has .*/a.*/b"):
        use_new_version(project, project.sources[0].id, tmp_path)


def test_another_file_asks_which_dataset(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    path = _write_runs(tmp_path / "next.h5", {"a": [1.0, 2], "b": [3.0, 4]})
    oid = project.sources[0].id
    asked = parts_to_choose(project, oid, tmp_path, path)
    assert list(asked) == ["/run1"]
    assert asked["/run1"][:2] == ["/a", "/b"]  # those with the columns first
    swap = use_another_file(project, oid, tmp_path, path, parts={"/run1": "/b"})
    swap.command.apply(project)
    assert (project.sources[0].path, project.sources[0].dataset) == ("next.h5", "/b")
    np.testing.assert_array_equal(_y(project, tmp_path), [6, 8])


def test_another_file_with_the_same_datasets_asks_nothing(tmp_path: Path) -> None:
    project = _plotted(tmp_path, runs=("run1", "run2"))
    path = _write_runs(tmp_path / "next.h5", {"run1": [9.0], "run2": [4.0, 5]})
    oid = project.sources[0].id
    assert parts_to_choose(project, oid, tmp_path, path) == {}
    use_another_file(project, oid, tmp_path, path).command.apply(project)
    assert [s.dataset for s in project.sources] == ["/run1", "/run2"]
    np.testing.assert_array_equal(_y(project, tmp_path, 1), [8, 10])


def test_another_file_with_other_names_asks_for_the_columns(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    path = _write_runs(tmp_path / "next.h5", {"run1": [1.0, 2]}, ("time", "volt"))
    oid = project.sources[0].id
    missing = columns_to_choose(project, oid, tmp_path, path)
    assert [(m.name, m.choices) for m in missing] == [
        ("U", ["time", "volt"]),
        ("t", ["time", "volt"]),
    ]


def test_another_file_must_be_hdf5(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    (tmp_path / "next.csv").write_text("t,U\n1,2\n")
    with pytest.raises(DataError, match="not an HDF5 file"):
        use_another_file(
            project, project.sources[0].id, tmp_path, tmp_path / "next.csv"
        )


def test_a_column_gone_from_the_new_version_is_a_problem(tmp_path: Path) -> None:
    project = _plotted(tmp_path)
    write_h5(tmp_path / "scan.h5", {"run1/t": [1.0, 2], "run1/other": [3.0, 4]})
    use_new_version(project, project.sources[0].id, tmp_path).apply(project)
    assert any("U" in str(problem) for problem in validate_references(project))


def test_reread_reads_the_whole_of_nothing_it_does_not_plot(tmp_path: Path) -> None:
    path = write_h5(tmp_path / "m.h5", {"f": np.arange(5.0), "t": np.arange(8.0)})
    source = hdf5_source(path, tmp_path)
    assert reread(source, tmp_path).columns == ["f", "t"]


def _odd(tmp_path: Path) -> Path:
    """A group with two good datasets and two that NumPy or Python stumble on:
    a name in Latin-1, and HDF5's time type."""
    path = tmp_path / "odd.h5"
    with h5py.File(path, "w") as file:
        file["g/t"] = [1.0, 2]
        file["g/u"] = [3.0, 4]
        file["g"].create_dataset(b"temp_\xb0C", data=[5.0, 6])
        space = h5py.h5s.create_simple((2,))
        h5py.h5d.create(file["g"].id, b"when", h5py.h5t.UNIX_D32LE, space)
        file.create_group(b"run_\xb5")
    return path


def test_one_odd_member_does_not_spoil_the_file(tmp_path: Path) -> None:
    path = _odd(tmp_path)
    source = hdf5_source(path, tmp_path)
    assert (source.dataset, source.columns) == ("/g", ["t", "u"])
    np.testing.assert_array_equal(_column(tmp_path, source, "u"), [3, 4])
    found = {e.path: e for e in entries(path.read_bytes(), path.name)}
    assert found["/g"].left_out["temp_\\xb0C"] == "its name is not UTF-8 text"
    assert "cannot be read" in found["/g"].left_out["when"]
    assert "cannot be read" in found["/g/when"].problem


def test_columns_plotted_from_what_has_become_an_image_are_a_problem(
    tmp_path: Path,
) -> None:
    project = _plotted(tmp_path)
    with h5py.File(tmp_path / "scan.h5", "a") as file:
        file["img"] = np.zeros((3, 4))
    source = hdf5_source(tmp_path / "scan.h5", tmp_path, dataset="/run1")
    oid = project.sources[0].id
    project.sources = [source.model_copy(update={"id": oid})]  # the file as it is
    read_differently(project, oid, "dataset", "/img", tmp_path).apply(project)
    problems = [str(p) for p in validate_references(project)]
    assert any("'t'" in p for p in problems) and any("'U'" in p for p in problems)


def test_an_image_of_a_group_of_different_lengths_is_a_problem(tmp_path: Path) -> None:
    path = write_h5(tmp_path / "m.h5", {"g/f": np.arange(5.0), "g/t": np.arange(8.0)})
    source = hdf5_source(path, tmp_path, dataset="/g")
    image = ImagePlot(data=ArrayRef(source=source.id))
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[image])])])
    problems = validate_references(project, load_data(project, tmp_path))
    assert any("different lengths" in str(p) for p in problems)


def test_nothing_that_could_take_the_place_is_said(tmp_path: Path) -> None:
    path = write_h5(tmp_path / "i.h5", {"img": np.zeros((2, 2))})
    source = hdf5_source(path, tmp_path)
    line = write_h5(tmp_path / "next.h5", {"t": [1.0, 2]})
    with pytest.raises(DataError, match="next.h5 holds nothing .* '/img'"):
        parts_to_choose(Project(sources=[source]), source.id, tmp_path, line)


@pytest.mark.parametrize("dataset", ["/run1", "/run1/U"])
def test_a_renamed_run_is_found_for_one_column_too(
    tmp_path: Path, dataset: str
) -> None:
    path = write_h5(tmp_path / "r.h5", {"run1/U": [1.0, 2]})
    source = hdf5_source(path, tmp_path, dataset=dataset)
    write_h5(path, {"run2/U": [3.0, 4]})
    project = Project(sources=[source])
    use_new_version(project, source.id, tmp_path).apply(project)
    assert project.sources[0].dataset == dataset.replace("run1", "run2")


def test_the_list_of_a_file_is_read_once_until_the_file_changes(
    tmp_path: Path, monkeypatch
) -> None:
    from figscribe.io import hdf5file

    path = write_h5(tmp_path / "m.h5", {"a/t": [1.0, 2]})
    opened = []
    real = h5py.File

    def counting(*args, **kwargs):
        opened.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(hdf5file.h5py, "File", counting)
    assert hdf5file.listed(path) == ["/a", "/a/t"]
    assert hdf5file.listed(path) == ["/a", "/a/t"]
    assert opened == [path]  # by its path: not the whole file into memory
    monkeypatch.undo()
    write_h5(path, {"b/long name of the run": [1.0, 2]})
    assert hdf5file.listed(path) == ["/b", "/b/long name of the run"]


def test_listing_a_file_reads_no_values(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "m.h5"
    with h5py.File(path, "w") as file:
        for name in ("a", "b"):
            file.create_dataset(f"g/{name}", data=np.arange(100.0), compression="gzip")
        file.create_dataset("m", data=np.eye(3), compression="lzf", shuffle=True)

    def read(*args, **kwargs):
        raise AssertionError("values were read")

    monkeypatch.setattr(h5py.Dataset, "__getitem__", read)
    found = {e.path: e.problem for e in entries(path.read_bytes(), path.name)}
    assert found == {"/": found["/"], "/g": "", "/g/a": "", "/g/b": "", "/m": ""}


def test_an_allan_deviation_with_times_of_another_length_is_a_problem(
    tmp_path: Path,
) -> None:
    path = write_h5(tmp_path / "m.h5", {"y": np.arange(16.0), "t": np.arange(12.0)})
    source = hdf5_source(path, tmp_path)
    plot = AllanDeviationPlot(
        values=ColumnRef(source=source.id, column="y"),
        time=ColumnRef(source=source.id, column="t"),
    )
    project = Project(sources=[source], figures=[Figure(axes=[Axes(artists=[plot])])])
    problems = validate_references(project, load_data(project, tmp_path))
    assert any("time (t) has 12 values, values (y) has 16" in str(p) for p in problems)
