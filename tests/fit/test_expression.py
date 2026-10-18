"""The fit expression language: a safe subset of Python arithmetic."""

from __future__ import annotations

import time

import numpy as np
import pytest

from figscribe.fit import ExpressionError, compile_expression, numpy_source


def test_evaluates_like_numpy() -> None:
    f = compile_expression(
        "a * exp(-(x - mu)**2 / (2 * sigma**2)) + c", ["a", "mu", "sigma", "c"]
    )
    x = np.linspace(-3, 3, 7)
    expected = 2.0 * np.exp(-((x - 0.5) ** 2) / (2 * 1.5**2)) + 0.1
    np.testing.assert_allclose(f(x, 2.0, 0.5, 1.5, 0.1), expected)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("sqrt(x) + log(x) + log10(x)", lambda x: np.sqrt(x) + np.log(x) + np.log10(x)),
        ("sin(x) * cos(x) / tan(x)", lambda x: np.sin(x) * np.cos(x) / np.tan(x)),
        (
            "arcsin(x / 4) + arccos(x / 4) + arctan(x)",
            lambda x: np.arcsin(x / 4) + np.arccos(x / 4) + np.arctan(x),
        ),
        ("sinh(x) - cosh(x) + tanh(x)", lambda x: np.sinh(x) - np.cosh(x) + np.tanh(x)),
        ("abs(-x) + +x - pi", lambda x: np.abs(-x) + x - np.pi),
    ],
)
def test_every_function_matches_numpy(source: str, expected) -> None:
    x = np.array([0.5, 1.0, 2.0])
    np.testing.assert_allclose(compile_expression(source, [])(x), expected(x))


def test_a_constant_model_broadcasts_to_x() -> None:
    f = compile_expression("c", ["c"])
    assert f(np.zeros(4), 3.0).shape == (4,)


def test_huge_powers_overflow_instead_of_hanging() -> None:
    f = compile_expression("9**9**9 + x", [])
    start = time.monotonic()
    with np.errstate(over="ignore"):
        assert np.isinf(f(np.zeros(1)))[0]
    assert time.monotonic() - start < 1.0


@pytest.mark.parametrize(
    ("source", "parameters", "message"),
    [
        ("__import__('os').system('x')", [], "not allowed"),
        ("x.real", [], "not allowed"),
        ("(lambda: 1)()", [], "not allowed"),
        ("[x for x in y]", [], "not allowed"),
        ("x if a else 1", ["a"], "not allowed"),
        ("x < 1", [], "not allowed"),
        ("x // 2", [], "not allowed"),
        ("x % 2", [], "not allowed"),
        ("'text'", [], "not allowed"),
        ("True + x", [], "not allowed"),
        ("1j * x", [], "not allowed"),
        ("exp(x, 2)", [], "exactly one argument"),
        ("exp(x=1)", [], "exactly one argument"),
        ("exp(*x)", [], "exactly one argument"),
        ("np.exp(x)", [], "not allowed"),
        ("open(x)", [], "unknown function"),
        ("a * x + b", ["a"], "unknown name 'b'"),
        ("a * x", ["a", "b"], "parameter 'b' does not appear"),
        ("x +", [], "syntax"),
        ("a = 1", [], "syntax"),
        ("a * x", ["a", "a"], "more than once"),
        ("x * x", ["x"], "reserved"),
        ("exp * x", ["exp"], "reserved"),
        ("pi * x", ["pi"], "reserved"),
        ("a1 * x", ["1a"], "not a valid name"),
        ("", [], "empty"),
        ("x" + " + x" * 1000, [], "too long"),
    ],
)
def test_bad_expressions_are_refused(
    source: str, parameters: list[str], message: str
) -> None:
    with pytest.raises(ExpressionError, match=message):
        compile_expression(source, parameters)


def test_errors_carry_the_position() -> None:
    with pytest.raises(ExpressionError) as info:
        compile_expression("a * x + foo(x)", ["a"])
    assert info.value.position == 8


def test_numpy_source_runs_as_plain_numpy() -> None:
    source = numpy_source("a * exp(-x / tau) + c * sqrt(abs(x)) + pi")
    assert source == "a * np.exp(-x / tau) + c * np.sqrt(np.abs(x)) + np.pi"
    x = np.linspace(0, 2, 5)
    namespace = {"np": np, "x": x, "a": 2.0, "tau": 0.7, "c": 0.3}
    reference = compile_expression(
        "a * exp(-x / tau) + c * sqrt(abs(x)) + pi", ["a", "tau", "c"]
    )
    np.testing.assert_allclose(eval(source, namespace), reference(x, 2.0, 0.7, 0.3))
