"""Undo stress (B7.2): random sequences of commands, undone and redone.

A state machine drives `History` on the project that has every kind of object
(`tests/gui/everything.py`): it adds, changes, moves, duplicates and removes
objects, fits, leaves points out and converts units, and undoes and redoes at
random. After every step the project must be sound and a refused step must
have changed nothing; each undo and redo must lead to the state recorded when
that step was made; at the end, undoing everything must give the start and
redoing everything the end.

The fields to change are found from the model, so a new field is in the test
without anyone adding it. Hypothesis shrinks a failing sequence to a few steps.
When it finds a bug, write the shrunk sequence as an ordinary test next to
the others in this folder, so that the bug stays covered whatever it draws.
"""

from __future__ import annotations

import os
import types
import typing
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")

from gui.everything import build  # noqa: E402
from hypothesis import HealthCheck, assume, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402
from hypothesis.stateful import (  # noqa: E402
    RuleBasedStateMachine,
    invariant,
    precondition,
    rule,
    run_state_machine_as_test,
)
from pydantic import BaseModel  # noqa: E402

from figscribe.commands import (  # noqa: E402
    CommandError,
    History,
    InsertItem,
    MoveItem,
    SetField,
    add_figure,
    add_panel,
    copy_style,
    duplicate_artists,
    duplicate_axes,
    duplicate_figure,
    paste_style,
    remove_artist,
    remove_artists,
    remove_axes,
    remove_figure,
    remove_source,
    same_range,
    to_front,
)
from figscribe.commands.core import _ids_in, walk  # noqa: E402
from figscribe.fit import FitError, add_fit, refit, set_left_out  # noqa: E402
from figscribe.io import load_data  # noqa: E402
from figscribe.io.errors import DataError  # noqa: E402
from figscribe.model import (  # noqa: E402
    Annotation,
    ColumnRef,
    Conversion,
    ErrorbarPlot,
    FitCurve,
    Histogram,
    LinePlot,
    PredefinedFit,
    Project,
    ReferenceLine,
    ScatterPlot,
    ShadedSpan,
    dumps,
    loads,
)
from figscribe.model.validate import FITTABLE, outside_the_grid  # noqa: E402
from figscribe.units import set_conversion, set_range  # noqa: E402

REFUSED = (CommandError, FitError, DataError)
"""What means "that cannot be done", as against a bug (`tools/operations.py`)."""

EXAMPLES = int(os.environ.get("FIGSCRIBE_STRESS_EXAMPLES", "40"))
"""Sequences tried; raise it before a release (B7: repeat before every release)."""

STEPS = 30
"""Rules applied in one sequence."""

# On CI the same sequences for one version of Hypothesis and of Python, so that
# a pull request is not stopped by a bug found at random that it did not bring
# (a new release draws other ones); random elsewhere, to find new ones.
SETTINGS = settings(
    max_examples=EXAMPLES,
    stateful_step_count=STEPS,
    deadline=None,
    derandomize="CI" in os.environ,
    suppress_health_check=list(HealthCheck),
    print_blob=True,
)

NEVER_SET = {"id", "kind", "format", "target", "parent", "source", "path", "sha256"}
"""Fields that name another object or a file: set to anything, they would only
leave the project pointing nowhere, which is not what is tested here."""

TEXTS = ["", "k", "C3", "red", "#00ff7f", "not-a-color", "-", "--", "o", "x", "$\\mu$"]

NUMBERS = st.floats(-1e4, 1e4) | st.sampled_from([0.0, 1.0, -1.0, 72.0, 1e-9, 1e9])
BAD_NUMBERS = st.sampled_from([float("nan"), float("inf"), -float("inf")])


def values_for(annotation) -> st.SearchStrategy | None:
    """Values for a field of this type, bad ones included; None for a type this
    test does not set (objects, dictionaries, long tuples)."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return values_for(args[0])
    if annotation is bool:
        return st.booleans()
    if annotation is int:
        return st.integers(-3, 12)
    if annotation is float:
        return NUMBERS | BAD_NUMBERS
    if annotation is str:
        return st.sampled_from(TEXTS) | st.text(max_size=6)
    if origin is typing.Literal:
        return st.sampled_from(args)
    if origin in (typing.Union, types.UnionType):
        parts = [st.none() if a is type(None) else values_for(a) for a in args]
        return None if None in parts else st.one_of(parts)
    if origin is tuple and args == (float, float):
        return st.tuples(NUMBERS, NUMBERS)
    if origin is list and args == (float,):
        return st.lists(NUMBERS, max_size=4)
    return None


def settable(obj: BaseModel) -> list[tuple[tuple[str, ...], st.SearchStrategy]]:
    """The fields of `obj`, and of the objects it holds, that can be set here."""
    found = []
    for name, info in type(obj).model_fields.items():
        if name in NEVER_SET:
            continue
        held = getattr(obj, name)
        if isinstance(held, BaseModel) and not isinstance(held, ColumnRef):
            found += [((name, *path), s) for path, s in settable(held)]
            continue
        strategy = values_for(info.annotation)
        if strategy is not None:
            found.append(((name,), strategy))
    return found


def below(items: list, index: int):
    """The item at `index` counted round, in project order: not a random id or
    a set's order, or the same sequence would not repeat. A step with nothing
    to act on is dropped."""
    assume(bool(items))
    return items[index % len(items)]


class ProjectMachine(RuleBasedStateMachine):
    def __init__(self, folder: Path) -> None:
        super().__init__()
        self.folder = folder
        self.project = loads((folder / "everything.figscribe").read_text("utf-8"))
        self.history = History(self.project)
        self.snapshots = [dumps(self.project)]
        self.at = 0
        """Which snapshot the project is at: the number of steps not undone."""
        self.saved: int | None = 0
        self.copied = None

    # --- looking ---------------------------------------------------------------

    def objects(self, field: str | None = None) -> list:
        return [o for o, _, f in walk(self.project) if field in (None, f)]

    def plots(self) -> list:
        return [a for a in self.objects("artists") if isinstance(a, FITTABLE)]

    def fits(self) -> list:
        return [a for a in self.objects("artists") if isinstance(a, FitCurve)]

    def data(self):
        return load_data(self.project, self.folder)

    def plenty(self) -> bool:
        """Whether there is enough left to remove from; or the sequences end up
        in a project with nothing in it, where nothing is tried."""
        return len(self.objects("artists")) > 6

    # --- doing -----------------------------------------------------------------

    def attempt(self, make) -> None:
        """Build a command with `make` and push it. A refusal must change nothing."""
        before = self.snapshots[self.at]
        try:
            command = make()
            if command is None:
                return
            self.history.push(command)
        except REFUSED:
            assert dumps(self.project) == before, "a refused step changed the project"
            return
        if self.saved is not None and self.saved > self.at:
            self.saved = None  # the saved state is on the redo stack no more
        self.snapshots = [*self.snapshots[: self.at + 1], dumps(self.project)]
        self.at += 1

    # --- the rules: single fields ----------------------------------------------

    @rule(
        picks=st.lists(
            st.tuples(st.integers(0, 1000), st.integers(0, 1000)),
            min_size=1,
            max_size=4,
        ),
        data=st.data(),
    )
    def set_some_fields(self, picks, data) -> None:
        """Fields are the most numerous, so several are set in one rule."""
        for which, field in picks:
            owners = [o for o in self.objects() if o not in self.objects("sources")]
            owner = below([o for o in owners if settable(o)], which)
            path, strategy = below(settable(owner), field)
            value = data.draw(strategy)
            self.attempt(lambda o=owner, p=path, v=value: SetField(o.id, p, v))

    @rule(
        axes=st.integers(0, 1000),
        kind=st.integers(0, 6),
        index=st.integers(0, 12),
    )
    def insert_a_plot(self, axes, kind, index) -> None:
        panel = below(self.objects("axes"), axes)
        scan = below(self.objects("sources"), 0).id

        def col(name):
            return ColumnRef(source=scan, column=name)

        new = [
            LinePlot(x=col("t"), y=col("U")),
            ScatterPlot(x=col("t"), y=col("U")),
            ErrorbarPlot(x=col("t"), y=col("U"), yerr=col("dU")),
            Histogram(values=col("U")),
            Annotation(text="note", position=(1.0, 1.0)),
            ReferenceLine(at=2.0),
            ShadedSpan(start=1.0, end=2.0),
        ][kind]
        self.attempt(
            lambda: InsertItem(
                panel.id, "artists", new, index % (len(panel.artists) + 1)
            )
        )

    @rule(which=st.integers(0, 1000), to=st.integers(0, 12))
    def move_a_plot(self, which, to) -> None:
        plot = below(self.objects("artists"), which)
        panel = next(a for a in self.objects("axes") if plot in a.artists)
        self.attempt(
            lambda: MoveItem(panel.id, "artists", plot.id, to % len(panel.artists))
        )

    @rule(which=st.integers(0, 1000), to=st.integers(0, 6))
    def move_a_panel_or_figure(self, which, to) -> None:
        item = below([*self.objects("axes"), *self.objects("figures")], which)
        if item in self.project.figures:
            parent, field, count = None, "figures", len(self.project.figures)
        else:
            figure = next(f for f in self.project.figures if item in f.axes)
            parent, field, count = figure.id, "axes", len(figure.axes)
        self.attempt(lambda: MoveItem(parent, field, item.id, to % count))

    # --- the rules: what the program offers -------------------------------------

    @precondition(lambda self: self.plenty())
    @rule(which=st.integers(0, 1000))
    def remove_a_plot(self, which) -> None:
        plot = below(self.objects("artists"), which)
        self.attempt(lambda: remove_artist(self.project, plot.id))

    @precondition(lambda self: self.plenty())
    @rule(which=st.lists(st.integers(0, 1000), min_size=1, max_size=3))
    def remove_plots(self, which) -> None:
        plots = self.objects("artists")
        ids = [below(plots, i).id for i in which]
        self.attempt(lambda: remove_artists(self.project, ids))

    @precondition(lambda self: self.plenty())
    @rule(which=st.integers(0, 1000))
    def remove_a_panel(self, which) -> None:
        panel = below(self.objects("axes"), which)
        self.attempt(lambda: remove_axes(self.project, panel.id))

    @precondition(lambda self: self.plenty())
    @rule(which=st.integers(0, 1000))
    def remove_a_data_file(self, which) -> None:
        assume(which % 10 == 0)  # it takes the plots of the file with it
        source = below(self.objects("sources"), which // 10)
        self.attempt(lambda: remove_source(self.project, source.id))

    @rule(which=st.integers(0, 1000))
    def remove_a_figure(self, which) -> None:
        figure = below(self.objects("figures"), which)
        self.attempt(lambda: remove_figure(self.project, figure.id))

    @rule(
        which=st.integers(0, 1000),
        side=st.sampled_from(["right", "left", "above", "below", "inset"]),
    )
    def add_a_panel(self, which, side) -> None:
        panel = below(self.objects("axes"), which)
        self.attempt(lambda: add_panel(self.project, panel.id, side)[0])

    @rule(which=st.integers(0, 1000))
    def add_a_figure(self, which) -> None:
        figure = below(self.objects("figures"), which)
        self.attempt(lambda: add_figure(self.project, figure.id)[0])

    @rule(which=st.integers(0, 1000))
    def duplicate_a_figure(self, which) -> None:
        figure = below(self.objects("figures"), which)
        self.attempt(lambda: duplicate_figure(self.project, figure.id)[0])

    @rule(which=st.integers(0, 1000))
    def duplicate_a_panel(self, which) -> None:
        panel = below(self.objects("axes"), which)
        self.attempt(lambda: duplicate_axes(self.project, panel.id)[0])

    @rule(which=st.lists(st.integers(0, 1000), min_size=1, max_size=3))
    def duplicate_plots(self, which) -> None:
        plots = self.objects("artists")
        ids = list(dict.fromkeys(below(plots, i).id for i in which))
        self.attempt(lambda: duplicate_artists(self.project, ids)[0])

    @rule(to=st.integers(0, 1000), like=st.integers(0, 1000))
    def style_like(self, to, like) -> None:
        plots = self.objects("artists")
        target, source = below(plots, to), below(plots, like)
        self.attempt(lambda: copy_style(self.project, target.id, source.id))

    @rule(source=st.integers(0, 1000))
    def copy_a_style(self, source) -> None:
        self.copied = below(self.objects("artists"), source).model_copy(deep=True)

    @precondition(lambda self: self.copied is not None)
    @rule(onto=st.lists(st.integers(0, 1000), min_size=1, max_size=3))
    def paste_the_style(self, onto) -> None:
        plots = self.objects("artists")
        ids = list(dict.fromkeys(below(plots, i).id for i in onto))
        self.attempt(lambda: paste_style(self.project, ids, self.copied))

    @rule(which=st.integers(0, 1000), front=st.booleans())
    def bring_to_front(self, which, front) -> None:
        plot = below(self.objects("artists"), which)
        self.attempt(lambda: to_front(self.project, plot.id, front))

    @rule(
        which=st.integers(0, 1000),
        field=st.sampled_from(["x", "y"]),
        low=NUMBERS,
        high=NUMBERS,
    )
    def same_range_everywhere(self, which, field, low, high) -> None:
        panel = below(self.objects("axes"), which)
        self.attempt(lambda: same_range(self.project, panel.id, field, (low, high))[0])

    # --- the rules: fits, rows, units --------------------------------------------

    @rule(
        which=st.integers(0, 1000),
        model=st.sampled_from(["linear", "gaussian", "exponential"]),
        residuals=st.booleans(),
    )
    def add_a_fit(self, which, model, residuals) -> None:
        plot = below(self.plots(), which)
        fit = FitCurve(target=plot.id, model=PredefinedFit(name=model))
        self.attempt(lambda: add_fit(self.project, fit, residuals))

    @rule(which=st.integers(0, 1000))
    def fit_again(self, which) -> None:
        fit = below(self.fits(), which)
        self.attempt(lambda: refit(self.project, fit.id, self.data()))

    @rule(which=st.integers(0, 1000), rows=st.lists(st.integers(0, 24), max_size=6))
    def leave_rows_out(self, which, rows) -> None:
        plot = below(self.plots(), which)
        self.attempt(lambda: set_left_out(self.project, plot.id, rows, self.data()))

    @rule(
        which=st.integers(0, 1000),
        axis=st.sampled_from(["x", "y"]),
        factor=st.sampled_from([0.001, 0.5, 1.0, 60.0, 1e6]),
        from_start=st.booleans(),
        none=st.booleans(),
    )
    def convert_units(self, which, axis, factor, from_start, none) -> None:
        plot = below(self.plots(), which)
        conversion = None if none else Conversion(factor=factor, from_start=from_start)
        self.attempt(
            lambda: set_conversion(self.project, plot.id, axis, conversion, self.data())
        )

    @rule(which=st.integers(0, 1000), low=NUMBERS, high=NUMBERS, none=st.booleans())
    def use_a_range(self, which, low, high, none) -> None:
        plot = below(self.plots(), which)
        ends = None if none else (low, high)
        self.attempt(lambda: set_range(self.project, plot.id, ends, self.data()))

    # --- the rules: undo, redo, save ---------------------------------------------

    @precondition(lambda self: self.history.can_undo)
    @rule()
    def undo(self) -> None:
        self.history.undo()
        self.at -= 1
        assert dumps(self.project) == self.snapshots[self.at], "undo missed its state"

    @precondition(lambda self: self.history.can_redo)
    @rule()
    def redo(self) -> None:
        self.history.redo()
        self.at += 1
        assert dumps(self.project) == self.snapshots[self.at], "redo missed its state"

    @rule()
    def save(self) -> None:
        self.history.mark_clean()
        self.saved = self.at

    # --- after every step --------------------------------------------------------

    @invariant()
    def the_project_is_sound(self) -> None:
        text = dumps(self.project)
        assert text == self.snapshots[self.at], "the project is not at its snapshot"
        assert dumps(loads(text)) == text, "the project does not survive saving"
        ids = list(_ids_in(self.project))
        assert len(ids) == len(set(ids)), "an id is used twice"
        assert not outside_the_grid(self.project), "a panel lies outside its grid"
        names = {a.id for a in self.objects("artists")}
        for fit in self.fits():
            assert fit.target in names, "a fit lost the plot it fits"
        for artist in self.objects("artists"):
            if artist.kind == "residuals":
                assert artist.target in names, "residuals lost their fit"

    @invariant()
    def the_history_knows_where_it_is(self) -> None:
        assert self.history.can_undo == (self.at > 0)
        assert self.history.can_redo == (self.at < len(self.snapshots) - 1)
        assert self.history.is_clean == (self.saved == self.at)

    def teardown(self) -> None:
        end = self.at
        while self.history.can_undo:
            self.history.undo()
        assert dumps(self.project) == self.snapshots[0], "undoing all missed the start"
        for _ in range(end):
            self.history.redo()
        assert dumps(self.project) == self.snapshots[end], "redoing all missed the end"


@pytest.fixture(scope="module")
def folder(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("everything")
    build(folder)
    return folder


def test_any_sequence_of_commands_can_be_undone_and_redone(folder: Path) -> None:
    run_state_machine_as_test(lambda: ProjectMachine(folder), settings=SETTINGS)


def test_a_project_is_the_same_after_saving_and_loading(folder: Path) -> None:
    project = loads((folder / "everything.figscribe").read_text("utf-8"))
    assert isinstance(project, Project)
    assert dumps(loads(dumps(project))) == dumps(project)
