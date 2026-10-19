"""The Document: the GUI's single path to the model."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.commands import CommandError, SetField, remove_artist
from figscribe.gui import Document
from figscribe.model import loads


def test_a_new_document_has_one_empty_figure(qtbot) -> None:
    document = Document()
    assert len(document.project.figures) == 1
    assert document.figure is document.project.figures[0]
    assert document.title == "Untitled — figscribe"


def test_open_reads_the_project_and_its_data(qtbot, example: Path) -> None:
    document = Document.open(example)
    assert document.title == "scan.figscribe — figscribe"
    assert document.base_dir == example.parent
    artist = document.project.figures[0].axes[0].artists[0]
    assert len(document.data(artist.x)) > 0


def test_push_emits_and_marks_unsaved(qtbot, example: Path) -> None:
    document = Document.open(example)
    figure = document.figure
    with qtbot.waitSignals([document.changed, document.state_changed]):
        document.push(SetField(figure.id, ("name",), "Renamed"))
    assert document.figure.name == "Renamed"
    assert document.title.endswith("* — figscribe")

    with qtbot.waitSignal(document.changed):
        document.undo()
    assert document.figure.name == "Scan"
    assert not document.title.endswith("* — figscribe")

    with qtbot.waitSignal(document.changed):
        document.redo()
    assert document.figure.name == "Renamed"


def test_a_refused_command_changes_nothing(qtbot, example: Path) -> None:
    document = Document.open(example)
    with qtbot.assertNotEmitted(document.changed):
        with pytest.raises(CommandError):
            document.push(SetField(document.figure.id, ("dpi",), -1.0))
    assert not document.history.can_undo


def test_save_writes_and_marks_clean(qtbot, example: Path, tmp_path: Path) -> None:
    document = Document.open(example)
    document.push(SetField(document.figure.id, ("name",), "Renamed"))
    target = tmp_path / "copy.figscribe"
    with qtbot.waitSignal(document.state_changed):
        document.save(target)
    assert document.path == target
    assert document.history.is_clean
    assert loads(target.read_text(encoding="utf-8")).figures[0].name == "Renamed"


def test_saving_an_untitled_document_needs_a_path(qtbot) -> None:
    with pytest.raises(ValueError, match="path"):
        Document().save()


def test_selection_follows_the_model(qtbot, example: Path) -> None:
    document = Document.open(example)
    artist = document.project.figures[0].axes[0].artists[0]

    with qtbot.waitSignal(document.selection_changed) as signal:
        document.select(artist.id)
    assert signal.args == [artist.id]
    assert document.selected == artist.id

    document.select("no-such-id")
    assert document.selected is None

    document.select(artist.id)
    with qtbot.waitSignal(document.selection_changed) as signal:
        document.push(remove_artist(document.project, artist.id))
    assert signal.args == [None]


def test_selecting_an_object_shows_its_figure(qtbot, example: Path) -> None:
    document = Document.open(example)
    second = document.figure.model_copy(deep=True, update={"id": "second"})
    second.axes = []
    document.project.figures = [*document.project.figures, second]
    document.select("second")
    assert document.figure.id == "second"


def test_data_is_reread_when_the_sources_change(qtbot, example: Path) -> None:
    document = Document.open(example)
    first = document.data
    assert document.data is first
    source = document.project.sources[0]
    document.push(SetField(source.id, ("comment",), "%"))
    assert document.data is not first


def test_the_document_is_a_workspace_for_the_tools(qtbot, example: Path) -> None:
    from figscribe.tools import Toolbox

    document = Document.open(example)
    tools = Toolbox(document)
    artist = document.project.figures[0].axes[0].artists[0]
    document.select(artist.id)
    assert tools.call("get_project", {})["selected"] == artist.id

    with qtbot.waitSignal(document.changed):
        tools.call(
            "set_field",
            {"object_id": artist.id, "path": ["color"], "value": "tab:green"},
        )
    assert document.history.undo_text == "Set color"
    assert document.title.endswith("* — figscribe")
