"""Test 4 from the project brief: every change is exactly reversible via undo."""

from __future__ import annotations

import pytest

from figscribe.commands import (
    Command,
    CommandError,
    History,
    InsertItem,
    Macro,
    MoveItem,
    RemoveItem,
    SetField,
)
from figscribe.model import (
    Annotation,
    Axes,
    AxisSpec,
    ColumnRef,
    Figure,
    LinePlot,
    Project,
    dumps,
)


def _ids(project: Project) -> tuple[str, str, str, str, str, str]:
    figure = project.figures[0]
    top, bottom = figure.axes
    data, fit = top.artists
    return figure.id, top.id, bottom.id, data.id, fit.id, bottom.artists[0].id


def _commands(project: Project) -> list[Command]:
    """One instance of every kind of command, all valid on the fixture."""
    figure, top, bottom, data, fit, _ = _ids(project)
    source = project.sources[0].id
    line = LinePlot(
        x=ColumnRef(source=source, column="t"), y=ColumnRef(source=source, column="U")
    )
    return [
        SetField(figure, ("width_mm",), 175.0),
        SetField(top, ("x", "label"), r"$\tau$"),
        SetField(top, ("x", "limits"), (0.0, 1.0)),
        SetField(top, ("legend", "position"), None),
        SetField(figure, ("layout", "height_ratios"), [2.0, 1.0]),
        SetField(fit, ("result",), None),
        SetField(top, ("x",), AxisSpec(label="t", scale="log")),
        SetField(None, ("figscribe_version",), "9.9.9"),
        InsertItem(top, "artists", line),
        InsertItem(top, "artists", line, index=0),
        InsertItem(figure, "axes", Axes(row=1, col=0)),
        InsertItem(None, "figures", Figure(name="second")),
        RemoveItem(top, "artists", data),
        RemoveItem(figure, "axes", bottom),
        RemoveItem(None, "sources", source),
        MoveItem(top, "artists", fit, 0),
        MoveItem(figure, "axes", top, 1),
        Macro(
            "Rename and resize",
            [
                SetField(figure, ("name",), "renamed"),
                SetField(figure, ("height_mm",), 80.0),
                InsertItem(bottom, "artists", Annotation(text="x", position=(0, 0))),
            ],
        ),
    ]


N_COMMANDS = 18


@pytest.fixture(params=range(N_COMMANDS))
def command(request: pytest.FixtureRequest, project: Project) -> Command:
    commands = _commands(project)
    assert len(commands) == N_COMMANDS
    return commands[request.param]


def test_apply_changes_the_project(project: Project, command: Command) -> None:
    before = dumps(project)
    command.apply(project)
    assert dumps(project) != before


def test_revert_restores_the_project_exactly(
    project: Project, command: Command
) -> None:
    before = dumps(project)
    command.apply(project)
    command.revert(project)
    assert dumps(project) == before


def test_redo_after_undo_restores_the_applied_state(
    project: Project, command: Command
) -> None:
    history = History(project)
    history.push(command)
    applied = dumps(project)
    history.undo()
    history.redo()
    assert dumps(project) == applied


def test_repeated_undo_redo_is_stable(project: Project, command: Command) -> None:
    history = History(project)
    before = dumps(project)
    history.push(command)
    applied = dumps(project)
    for _ in range(3):
        history.undo()
        assert dumps(project) == before
        history.redo()
        assert dumps(project) == applied


def test_a_whole_session_undoes_to_the_start(project: Project) -> None:
    history = History(project)
    before = dumps(project)
    figure, top, bottom, data, fit, _ = _ids(project)
    for command in [
        SetField(top, ("x", "label"), "a"),
        SetField(top, ("x", "label"), "b"),
        MoveItem(top, "artists", fit, 0),
        RemoveItem(top, "artists", data),
        InsertItem(figure, "axes", Axes(row=1, col=0)),
        SetField(figure, ("layout", "rows"), 3),
    ]:
        history.push(command)
    while history.can_undo:
        history.undo()
    assert dumps(project) == before


# --- the model is never left half-changed -----------------------------------


def test_invalid_value_is_refused_and_changes_nothing(project: Project) -> None:
    figure = project.figures[0].id
    history = History(project)
    before = dumps(project)
    with pytest.raises(CommandError, match="width_mm"):
        history.push(SetField(figure, ("width_mm",), -1.0))
    assert dumps(project) == before
    assert not history.can_undo


def test_strict_types_are_kept(project: Project) -> None:
    with pytest.raises(CommandError):
        SetField(project.figures[0].id, ("dpi",), "300").apply(project)


def test_failing_macro_rolls_back_its_earlier_steps(project: Project) -> None:
    figure, top, *_ = _ids(project)
    history = History(project)
    before = dumps(project)
    macro = Macro(
        "Half valid",
        [
            SetField(figure, ("name",), "renamed"),
            InsertItem(top, "artists", Annotation(text="x", position=(0, 0))),
            SetField(figure, ("dpi",), 0.0),
        ],
    )
    with pytest.raises(CommandError, match="dpi"):
        history.push(macro)
    assert dumps(project) == before
    assert not history.can_undo


@pytest.mark.parametrize(
    "make",
    [
        lambda ids: SetField("nope", ("name",), "x"),
        lambda ids: SetField(ids[0], ("no_such_field",), 1),
        lambda ids: SetField(ids[1], ("y_right", "label"), "x"),  # y_right is None
        lambda ids: SetField(ids[0], ("id",), "other"),
        lambda ids: SetField(ids[0], (), "x"),
        lambda ids: SetField(ids[1], ("artists",), []),  # an item list
        lambda ids: InsertItem(ids[0], "name", Axes()),  # not a list field
        lambda ids: RemoveItem(ids[1], "artists", "nope"),
        lambda ids: MoveItem(ids[1], "artists", ids[3], 5),
        lambda ids: MoveItem(ids[1], "artists", ids[3], -1),
    ],
    ids=[
        "unknown-object",
        "unknown-field",
        "through-none",
        "id-is-fixed",
        "empty-path",
        "set-item-list",
        "insert-into-non-list",
        "remove-unknown-item",
        "move-past-end",
        "move-negative",
    ],
)
def test_bad_addresses_are_refused(project: Project, make) -> None:
    before = dumps(project)
    with pytest.raises(CommandError):
        make(_ids(project)).apply(project)
    assert dumps(project) == before


def test_insert_refuses_an_id_already_in_the_project(project: Project) -> None:
    figure, top, *_ = _ids(project)
    clash = Axes(id=top)
    with pytest.raises(CommandError, match="already"):
        InsertItem(figure, "axes", clash).apply(project)


def test_insert_refuses_a_nested_id_already_in_the_project(project: Project) -> None:
    figure = project.figures[0]
    copy = figure.axes[0].model_copy(deep=True, update={"id": "fresh"})
    with pytest.raises(CommandError, match="already"):
        InsertItem(figure.id, "axes", copy).apply(project)


def test_insert_refuses_a_wrong_item_type(project: Project) -> None:
    figure = project.figures[0].id
    with pytest.raises(CommandError):
        InsertItem(figure, "axes", Figure()).apply(project)


# --- commands do not share objects with their callers ----------------------


def test_inserted_item_is_a_copy(project: Project) -> None:
    top = project.figures[0].axes[0]
    note = Annotation(text="before", position=(0, 0))
    InsertItem(top.id, "artists", note).apply(project)
    note.text = "changed by the caller"
    assert top.artists[-1].text == "before"
    assert top.artists[-1].id == note.id


def test_set_value_is_a_copy(project: Project) -> None:
    top = project.figures[0].axes[0]
    spec = AxisSpec(label="before")
    SetField(top.id, ("x",), spec).apply(project)
    spec.label = "changed by the caller"
    assert top.x.label == "before"


def test_lists_are_replaced_not_mutated(project: Project) -> None:
    top = project.figures[0].axes[0]
    old = top.artists
    snapshot = list(old)
    InsertItem(top.id, "artists", Annotation(text="x", position=(0, 0))).apply(project)
    assert top.artists is not old
    assert old == snapshot


def test_removed_item_keeps_its_id_after_undo(project: Project) -> None:
    figure, top, bottom, data, *_ = _ids(project)
    history = History(project)
    history.push(RemoveItem(top, "artists", data))
    history.undo()
    assert project.figures[0].axes[0].artists[0].id == data
    # and it is addressable again
    history.push(SetField(data, ("label",), "again"))
    assert project.figures[0].axes[0].artists[0].label == "again"


def test_commands_address_by_id_not_by_reference(project: Project) -> None:
    """A command recorded before a remove/undo still hits the restored object."""
    figure, top, *_ = _ids(project)
    history = History(project)
    rename = SetField(top, ("title",), "renamed")
    history.push(rename)
    history.push(RemoveItem(figure, "axes", top))
    history.undo()  # restores the axes
    history.undo()  # reverts the rename on the restored axes
    assert project.figures[0].axes[0].title is None


# --- History bookkeeping ----------------------------------------------------


def test_history_texts_and_flags(project: Project) -> None:
    figure, *_ = _ids(project)
    history = History(project)
    assert not history.can_undo and not history.can_redo
    assert history.undo_text is None and history.redo_text is None

    history.push(SetField(figure, ("name",), "x", description="Rename figure"))
    assert history.can_undo and history.undo_text == "Rename figure"

    history.undo()
    assert history.can_redo and history.redo_text == "Rename figure"
    assert not history.can_undo


def test_push_clears_redo(project: Project) -> None:
    figure, *_ = _ids(project)
    history = History(project)
    history.push(SetField(figure, ("name",), "a"))
    history.undo()
    history.push(SetField(figure, ("name",), "b"))
    assert not history.can_redo


def test_undo_and_redo_on_empty_stacks_are_refused(project: Project) -> None:
    history = History(project)
    with pytest.raises(CommandError):
        history.undo()
    with pytest.raises(CommandError):
        history.redo()


def test_clean_state_follows_undo_and_redo(project: Project) -> None:
    figure, *_ = _ids(project)
    history = History(project)
    assert history.is_clean

    history.push(SetField(figure, ("name",), "a"))
    assert not history.is_clean
    history.mark_clean()
    assert history.is_clean

    history.push(SetField(figure, ("name",), "b"))
    assert not history.is_clean
    history.undo()
    assert history.is_clean
    history.undo()
    assert not history.is_clean
    history.redo()
    assert history.is_clean


def test_clean_state_is_lost_when_its_branch_is_discarded(project: Project) -> None:
    figure, *_ = _ids(project)
    history = History(project)
    history.push(SetField(figure, ("name",), "a"))
    history.mark_clean()
    history.undo()
    history.push(SetField(figure, ("name",), "b"))
    assert not history.is_clean
    history.undo()
    assert not history.is_clean  # back at the start, which was never saved


def test_default_descriptions_are_readable(project: Project) -> None:
    figure, top, _, data, *_ = _ids(project)
    note = Annotation(text="x", position=(0, 0))
    assert SetField(top, ("x", "label"), "t").description == "Set x label"
    assert InsertItem(top, "artists", note).description == "Add annotation"
    assert InsertItem(figure, "axes", Axes()).description == "Add axes"

    remove = RemoveItem(top, "artists", data)
    remove.apply(project)
    assert remove.description == "Remove errorbar plot"

    move = MoveItem(figure, "axes", top, 1)
    move.apply(project)
    assert move.description == "Move axes"
