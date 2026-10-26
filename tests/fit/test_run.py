"""Running fits: predefined models, weights, failure modes."""

from __future__ import annotations

import math

import numpy as np
import pytest

from figscribe.fit import (
    FitError,
    evaluate,
    initial_guess,
    numpy_source,
    parameter_names,
    run_fit,
)
from figscribe.model import ExpressionFit, FitResult, PredefinedFit

RNG_SEED = 20261018


def _noisy(model, true: dict[str, float], x: np.ndarray, noise: float):
    rng = np.random.default_rng(RNG_SEED)
    y = evaluate(model, true, x) + rng.normal(0.0, noise, x.size)
    return y, np.full(x.size, noise)


CASES = [
    (PredefinedFit(name="linear"), {"a": 2.5, "b": -1.0}, np.linspace(0, 10, 50)),
    (
        PredefinedFit(name="polynomial", degree=3),
        {"c0": 1.0, "c1": -2.0, "c2": 0.5, "c3": 0.1},
        np.linspace(-4, 4, 60),
    ),
    (
        PredefinedFit(name="gaussian"),
        {"a": 3.0, "mu": 1.2, "sigma": 0.6, "c": 0.4},
        np.linspace(-3, 5, 120),
    ),
    (
        PredefinedFit(name="gaussian"),
        {"a": -2.0, "mu": 0.0, "sigma": 1.0, "c": 5.0},  # a dip, not a peak
        np.linspace(-5, 5, 120),
    ),
    (
        PredefinedFit(name="lorentzian"),
        {"a": 4.0, "x0": -0.5, "gamma": 0.3, "c": 1.0},
        np.linspace(-4, 3, 150),
    ),
    (
        PredefinedFit(name="exponential"),
        {"a": 5.0, "tau": 2.0, "c": 0.5},
        np.linspace(0, 10, 80),
    ),
    (
        PredefinedFit(name="exponential"),
        {"a": 0.2, "tau": -3.0, "c": 1.0},  # growth: negative tau
        np.linspace(0, 6, 80),
    ),
    (
        ExpressionFit(expression="a * sin(w * x) + b", parameters=["a", "w", "b"]),
        {"a": 1.5, "w": 1.0, "b": 0.2},
        np.linspace(0, 12, 100),
    ),
]


@pytest.mark.parametrize(("model", "true", "x"), CASES)
def test_recovers_known_parameters(model, true, x) -> None:
    y, yerr = _noisy(model, true, x, noise=0.05)
    p0 = initial_guess(model, x, y)
    result = run_fit(model, p0, x, y, yerr)

    assert result.converged
    assert set(result.parameters) == set(true)
    for name, value in true.items():
        assert abs(result.parameters[name] - value) < 5 * result.uncertainties[name], (
            name
        )
    assert 0.5 < result.reduced_chi_square < 1.6


@pytest.mark.parametrize(
    ("model", "names"),
    [
        (PredefinedFit(name="linear"), ["a", "b"]),
        (PredefinedFit(name="polynomial", degree=2), ["c0", "c1", "c2"]),
        (PredefinedFit(name="gaussian"), ["a", "mu", "sigma", "c"]),
        (PredefinedFit(name="lorentzian"), ["a", "x0", "gamma", "c"]),
        (PredefinedFit(name="exponential"), ["a", "tau", "c"]),
        (ExpressionFit(expression="k * x", parameters=["k"]), ["k"]),
    ],
)
def test_parameter_names(model, names) -> None:
    assert parameter_names(model) == names


def test_polynomial_needs_a_degree() -> None:
    with pytest.raises(FitError, match="degree"):
        parameter_names(PredefinedFit(name="polynomial"))


def test_predefined_models_have_plain_numpy_source() -> None:
    assert numpy_source(PredefinedFit(name="gaussian")) == (
        "a * np.exp(-(x - mu) ** 2 / (2 * sigma ** 2)) + c"
    )
    assert numpy_source(PredefinedFit(name="polynomial", degree=2)) == (
        "c0 + c1 * x + c2 * x ** 2"
    )


def test_without_errors_there_is_no_chi_square() -> None:
    model = PredefinedFit(name="linear")
    x = np.linspace(0, 1, 20)
    y, _ = _noisy(model, {"a": 1.0, "b": 0.0}, x, noise=0.01)
    result = run_fit(model, {"a": 1.0, "b": 0.0}, x, y)
    assert result.reduced_chi_square is None
    assert all(0 < u < 0.1 for u in result.uncertainties.values())


def test_errors_weight_the_points() -> None:
    model = ExpressionFit(expression="c", parameters=["c"])
    x = np.arange(3.0)
    y = np.array([0.0, 0.0, 10.0])
    precise_last = run_fit(model, {"c": 1.0}, x, y, np.array([1.0, 1.0, 0.01]))
    assert precise_last.parameters["c"] == pytest.approx(10.0, abs=0.01)


def test_non_finite_points_are_dropped() -> None:
    model = PredefinedFit(name="linear")
    x = np.array([0.0, 1.0, np.nan, 3.0, 4.0])
    y = np.array([0.0, 2.0, 4.0, np.inf, 8.0])
    yerr = np.array([0.1, 0.1, 0.1, 0.1, 0.1])
    result = run_fit(model, {"a": 1.0, "b": 0.0}, x, y, yerr)
    assert result.parameters["a"] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("p0", "message"),
    [
        ({"a": 1.0}, "missing start value for 'b'"),
        ({"a": 1.0, "b": 0.0, "z": 3.0}, "unknown parameter 'z'"),
        ({"a": math.nan, "b": 0.0}, "not finite"),
    ],
)
def test_start_values_must_match_the_model(p0, message) -> None:
    x = np.arange(5.0)
    with pytest.raises(FitError, match=message):
        run_fit(PredefinedFit(name="linear"), p0, x, 2 * x)


def test_too_few_points_are_refused() -> None:
    x = np.array([0.0, 1.0])
    with pytest.raises(FitError, match="needs more than 2 valid points"):
        run_fit(PredefinedFit(name="linear"), {"a": 1.0, "b": 0.0}, x, x)


def test_non_positive_errors_are_refused() -> None:
    x = np.arange(5.0)
    with pytest.raises(FitError, match="positive"):
        run_fit(PredefinedFit(name="linear"), {"a": 1.0, "b": 0.0}, x, x, np.zeros(5))


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(FitError, match="same length"):
        run_fit(
            PredefinedFit(name="linear"),
            {"a": 1.0, "b": 0.0},
            np.arange(5.0),
            np.arange(4.0),
        )


def test_a_model_undefined_at_the_start_is_refused() -> None:
    model = ExpressionFit(expression="log(k * x)", parameters=["k"])
    x = np.arange(1.0, 6.0)
    with pytest.raises(FitError, match="not finite"):
        run_fit(model, {"k": -1.0}, x, x)


def test_non_convergence_is_recorded_not_raised() -> None:
    model = ExpressionFit(
        expression="a * exp(-(x - mu)**2 / (2 * s**2))", parameters=["a", "mu", "s"]
    )
    x = np.linspace(-5, 5, 40)
    start = {"a": 1.0, "mu": 3.0, "s": 0.5}
    result = run_fit(model, start, x, np.exp(-(x**2)), max_evaluations=3)
    assert not result.converged
    assert result.parameters == start
    assert all(math.isinf(u) for u in result.uncertainties.values())


def test_an_inestimable_covariance_gives_infinite_uncertainties() -> None:
    # a and b only ever appear as their sum: the covariance is singular.
    model = ExpressionFit(expression="(a + b) * x", parameters=["a", "b"])
    x = np.arange(1.0, 6.0)
    result = run_fit(model, {"a": 1.0, "b": 1.0}, x, 3 * x, np.full(5, 0.1))
    assert result.converged
    assert result.parameters["a"] + result.parameters["b"] == pytest.approx(3.0)
    assert all(math.isinf(u) for u in result.uncertainties.values())


def test_a_numerically_singular_covariance_counts_as_inestimable() -> None:
    # Almost the sum again: the covariance comes back finite but meaningless
    # (about 1e27), as macOS returns it for the exact sum above.
    model = ExpressionFit(expression="(a + b * 1.000000001) * x", parameters=["a", "b"])
    x = np.arange(1.0, 6.0)
    result = run_fit(model, {"a": 1.0, "b": 1.0}, x, 3 * x, np.full(5, 0.1))
    assert all(math.isinf(u) for u in result.uncertainties.values())


def test_strongly_correlated_parameters_keep_finite_uncertainties() -> None:
    # Far from the origin, slope and intercept correlate almost perfectly,
    # but the covariance is still well determined.
    model = PredefinedFit(name="linear")
    x = np.linspace(1000.0, 1001.0, 20)
    y, yerr = _noisy(model, {"a": 2.0, "b": 1.0}, x, noise=0.05)
    result = run_fit(model, initial_guess(model, x, y), x, y, yerr)
    assert all(math.isfinite(u) and u > 0 for u in result.uncertainties.values())
    assert abs(result.parameters["a"] - 2.0) < 5 * result.uncertainties["a"]


def test_results_are_plain_floats_and_roundtrip() -> None:
    model = PredefinedFit(name="linear")
    x = np.arange(6.0)
    result = run_fit(model, {"a": 1.0, "b": 0.0}, x, 2 * x + 1, np.full(6, 0.1))
    assert all(type(v) is float for v in result.parameters.values())
    assert FitResult.model_validate_json(result.model_dump_json()) == result


def test_guess_works_on_flat_or_tiny_data() -> None:
    for model in (
        PredefinedFit(name="gaussian"),
        PredefinedFit(name="lorentzian"),
        PredefinedFit(name="exponential"),
    ):
        for x, y in ((np.arange(5.0), np.ones(5)), (np.array([1.0]), np.array([2.0]))):
            guess = initial_guess(model, x, y)
            assert set(guess) == set(parameter_names(model))
            assert all(math.isfinite(v) for v in guess.values())


# --- fixed parameters and bounds ----------------------------------------------


def _gaussian_data():
    model = PredefinedFit(name="gaussian")
    true = {"a": 3.0, "mu": 1.2, "sigma": 0.6, "c": 0.4}
    x = np.linspace(-3, 5, 120)
    y, yerr = _noisy(model, true, x, 0.05)
    return model, true, x, y, yerr


def test_a_fixed_parameter_keeps_its_start_value() -> None:
    model, true, x, y, yerr = _gaussian_data()
    start = {**initial_guess(model, x, y), "sigma": 0.55}
    result = run_fit(model, start, x, y, yerr, fixed=["sigma"])
    assert result.parameters["sigma"] == 0.55
    assert result.uncertainties["sigma"] == 0.0
    assert result.parameters["mu"] == pytest.approx(true["mu"], abs=0.05)
    residuals = (y - evaluate(model, result.parameters, x)) / yerr
    free = 3  # the degrees of freedom count only what was fitted
    assert result.reduced_chi_square == pytest.approx(
        np.sum(residuals**2) / (x.size - free)
    )


def test_bounds_keep_a_parameter_in_its_range() -> None:
    model, true, x, y, yerr = _gaussian_data()
    start = {**initial_guess(model, x, y), "a": 2.0}
    result = run_fit(model, start, x, y, yerr, bounds={"a": (None, 2.5)})
    assert result.converged
    assert result.parameters["a"] <= 2.5
    assert result.parameters["a"] == pytest.approx(2.5, abs=1e-3)  # it wants 3


def test_an_open_bound_is_no_bound() -> None:
    model, true, x, y, yerr = _gaussian_data()
    start = initial_guess(model, x, y)
    free = run_fit(model, start, x, y, yerr)
    bounded = run_fit(model, start, x, y, yerr, bounds={"sigma": (0.0, None)})
    assert bounded.parameters["sigma"] == pytest.approx(
        free.parameters["sigma"], rel=1e-4
    )


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"bounds": {"a": (5.0, None)}}, "start value of a, 3, lies outside"),
        ({"bounds": {"a": (2.0, 1.0)}}, "lower bound of a is not below"),
        ({"fixed": ["a", "mu", "sigma", "c"]}, "every parameter is fixed"),
        ({"fixed": ["k"]}, "unknown parameter 'k'"),
        ({"bounds": {"k": (0.0, 1.0)}}, "unknown parameter 'k'"),
    ],
)
def test_fixed_and_bounds_are_checked(options, message) -> None:
    model, true, x, y, yerr = _gaussian_data()
    with pytest.raises(FitError, match=message):
        run_fit(model, true, x, y, yerr, **options)


# --- outliers -------------------------------------------------------------------


def _with_glitches(yerr: bool):
    model = PredefinedFit(name="linear")
    x = np.linspace(0, 10, 41)
    rng = np.random.default_rng(RNG_SEED)
    y = 2.0 * x + 1.0 + rng.normal(0, 0.05, x.size)  # well inside the errors
    y[[7, 30]] += [3.0, -4.0]
    return model, x, y, (np.full(x.size, 0.1) if yerr else None)


@pytest.mark.parametrize("errors", [True, False])
def test_outliers_are_found_by_their_residuals(errors: bool) -> None:
    from figscribe.fit import outliers

    model, x, y, yerr = _with_glitches(errors)
    start = initial_guess(model, x, y)
    found = outliers(model, start, x, y, yerr, k=3.0)
    assert list(np.flatnonzero(found)) == [7, 30]


def test_without_outliers_none_are_found() -> None:
    from figscribe.fit import outliers

    model, x, _, yerr = _with_glitches(True)
    y = 2.0 * x + 1.0
    found = outliers(model, {"a": 1.0, "b": 0.0}, x, y + 0.01 * np.sin(x), yerr)
    assert not found.any()
