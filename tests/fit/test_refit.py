"""Running a fit as one undoable command."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.commands import History
from figscribe.fit import FitError, evaluate, refit
from figscribe.model import (
    Annotation,
    ColumnRef,
    FitCurve,
    PredefinedFit,
    Project,
    dumps,
)

TRUE = {"a": 3.0, "mu": 0.5, "sigma": 0.8, "c": 0.2}


@pytest.fixture
def data(project: Project):
    """Gaussian data with errors for the fixture's t, U and dU columns."""
    t = np.linspace(-4, 4, 81)
    rng = np.random.default_rng(1)
    columns = {
        "t": t,
        "U": evaluate(PredefinedFit(name="gaussian"), TRUE, t)
        + rng.normal(0, 0.05, t.size),
        "dU": np.full(t.size, 0.05),
    }

    def provide(ref: ColumnRef) -> np.ndarray:
        return columns[ref.column]

    return provide


def _fit(project: Project) -> FitCurve:
    return project.figures[0].axes[0].artists[1]


def test_refit_stores_start_values_and_result_in_one_step(
    project: Project, data
) -> None:
    fit = _fit(project)
    history = History(project)
    before = dumps(project)

    history.push(refit(project, fit.id, data))

    fit = _fit(project)
    assert set(fit.initial_values) == set(TRUE)
    assert fit.result.converged
    for name, value in TRUE.items():
        assert (
            abs(fit.result.parameters[name] - value)
            < 5 * fit.result.uncertainties[name]
        )
    assert fit.result.reduced_chi_square is not None
    assert history.undo_text == "Fit gaussian"

    history.undo()
    assert dumps(project) == before


def test_stored_start_values_win_over_the_guess(project: Project, data) -> None:
    fit = _fit(project)
    # The fixture stores a, mu and sigma; c is missing and gets guessed.
    macro = refit(project, fit.id, data)
    macro.apply(project)
    fit = _fit(project)
    assert fit.initial_values["a"] == 1.0
    assert fit.initial_values["mu"] == 0.0
    assert fit.initial_values["sigma"] == 1.0
    assert "c" in fit.initial_values


def test_start_values_of_another_model_are_dropped(project: Project, data) -> None:
    fit = _fit(project)
    fit.model = PredefinedFit(name="linear")
    refit(project, fit.id, data).apply(project)
    assert set(_fit(project).initial_values) == {"a", "b"}


def test_refit_refuses_what_is_not_a_fit(project: Project, data) -> None:
    data_artist = project.figures[0].axes[0].artists[0]
    with pytest.raises(FitError, match="not a fit"):
        refit(project, data_artist.id, data)


def test_refit_refuses_a_target_without_data(project: Project, data) -> None:
    top = project.figures[0].axes[0]
    note = Annotation(text="x", position=(0.0, 0.0))
    top.artists = [*top.artists, note]
    _fit(project).target = note.id
    with pytest.raises(FitError, match="annotation"):
        refit(project, _fit(project).id, data)


def test_refit_holds_fixed_parameters_and_keeps_bounds(project: Project, data) -> None:
    fit = _fit(project)
    fit.initial_values = {"sigma": 0.7}
    fit.fixed = ["sigma"]
    fit.parameter_bounds = {"a": (None, 2.0)}
    History(project).push(refit(project, fit.id, data))
    result = _fit(project).result
    assert result.parameters["sigma"] == 0.7
    assert result.parameters["a"] <= 2.0


def test_a_fit_is_changed_in_one_step(project: Project, data) -> None:
    from figscribe.fit import update_fit

    fit = _fit(project)
    history = History(project)
    history.push(refit(project, fit.id, data))
    before = dumps(project)
    changed = _fit(project).model_copy(
        update={"fixed": ["c"], "parameter_bounds": {"a": (0.0, None)}, "label": "new"}
    )
    history.push(update_fit(project, fit.id, changed))
    assert _fit(project).fixed == ["c"] and _fit(project).label == "new"
    assert history.undo_text == "Change the fit"
    history.undo()
    assert dumps(project) == before
