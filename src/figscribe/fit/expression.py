"""The expression language for fit models: a safe subset of Python arithmetic.

An expression such as ``a * exp(-x / tau) + c`` is parsed with `ast` and checked
against an allow-list: the operators + - * / **, numbers, the variable x, the
model's parameters, the constant pi and a fixed set of NumPy functions. Nothing
is ever passed to `eval`; the checked tree is turned into nested closures.

The same text is the single description of a model: the fit evaluates it, and
`numpy_source` turns it into the NumPy code the code generator writes.
"""

from __future__ import annotations

import ast
import functools
import keyword
import re
from collections.abc import Callable, Sequence

import numpy as np

MAX_LENGTH = 1000
"""Longer expressions are refused; Python's parser recurses on nesting."""

FUNCTIONS: dict[str, np.ufunc] = {
    name: getattr(np, name)
    for name in (
        "exp",
        "log",
        "log10",
        "sqrt",
        "sin",
        "cos",
        "tan",
        "arcsin",
        "arccos",
        "arctan",
        "sinh",
        "cosh",
        "tanh",
        "abs",
    )
}
"""Named as in NumPy, so that `numpy_source` only has to prefix them."""

CONSTANTS: dict[str, float] = {"pi": np.pi}

VARIABLE = "x"

_OPERATORS: dict[type[ast.operator], Callable] = {
    ast.Add: np.add,
    ast.Sub: np.subtract,
    ast.Mult: np.multiply,
    ast.Div: np.divide,
    ast.Pow: np.power,
}
_UNARY: dict[type[ast.unaryop], Callable] = {
    ast.USub: np.negative,
    ast.UAdd: np.positive,
}

Model = Callable[..., np.ndarray]
"""f(x, *parameters) -> y, the signature curve_fit expects."""


class FitError(ValueError):
    """A fit that cannot be set up or run."""


class ExpressionError(FitError):
    """An expression outside the allowed language."""

    def __init__(self, message: str, position: int | None = None) -> None:
        super().__init__(message)
        self.position = position
        """0-based character offset into the expression, where known."""


def compile_expression(source: str, parameters: Sequence[str]) -> Model:
    """Check `source` and return it as f(x, *parameters).

    Raises ExpressionError for anything outside the language, for names that
    are neither x, a parameter nor a constant, and for a parameter that does
    not appear (its uncertainty could not be determined).
    """
    return _compile(source, tuple(parameters))


@functools.lru_cache(maxsize=256)
def _compile(source: str, parameters: tuple[str, ...]) -> Model:
    tree = _parse(source)
    _check_parameters(parameters)
    used: set[str] = set()
    index = {name: i for i, name in enumerate(parameters)}
    body = _build(tree.body, index, used)
    for name in parameters:
        if name not in used:
            raise ExpressionError(
                f"parameter {name!r} does not appear in the expression"
            )

    def model(x, *values):
        with np.errstate(all="ignore"):
            x = np.asarray(x, dtype=float)
            return body(x, values) + np.zeros_like(x)

    return model


def numpy_source(source: str) -> str:
    """The expression as NumPy code: ``exp(x)`` becomes ``np.exp(x)``."""
    tree = _parse(source)

    class Prefix(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.AST:
            if node.id in FUNCTIONS or node.id in CONSTANTS:
                return ast.Attribute(ast.Name("np", ast.Load()), node.id, ast.Load())
            return node

    return ast.unparse(Prefix().visit(tree))


def free_names(source: str) -> list[str]:
    """The names in `source` that are neither x, a function nor a constant:
    the parameters a user means, in the order they first appear."""
    names: list[str] = []
    for node in ast.walk(_parse(source)):
        if isinstance(node, ast.Name) and node.id not in names:
            if node.id != VARIABLE and node.id not in FUNCTIONS | CONSTANTS:
                names.append(node.id)
    return sorted(names, key=lambda n: _first_position(source, n))


def _first_position(source: str, name: str) -> int:
    match = re.search(rf"\b{re.escape(name)}\b", source)
    return match.start() if match else len(source)


def _parse(source: str) -> ast.Expression:
    if not source.strip():
        raise ExpressionError("the expression is empty")
    if len(source) > MAX_LENGTH:
        raise ExpressionError(
            f"the expression is too long (over {MAX_LENGTH} characters)"
        )
    try:
        return ast.parse(source.strip(), mode="eval")
    except SyntaxError as exc:
        position = exc.offset - 1 if exc.offset else None
        raise ExpressionError(f"syntax error: {exc.msg}", position) from None


def _check_parameters(parameters: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for name in parameters:
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ExpressionError(f"{name!r} is not a valid name")
        if name == VARIABLE or name in FUNCTIONS or name in CONSTANTS:
            raise ExpressionError(f"{name!r} is reserved and cannot be a parameter")
        if name in seen:
            raise ExpressionError(f"parameter {name!r} is listed more than once")
        seen.add(name)


Node = Callable[[np.ndarray, tuple], np.ndarray]


def _build(node: ast.AST, index: dict[str, int], used: set[str]) -> Node:
    """Turn a checked node into a closure over (x, parameter values)."""
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        op = _OPERATORS[type(node.op)]
        left, right = _build(node.left, index, used), _build(node.right, index, used)
        return lambda x, p: op(left(x, p), right(x, p))

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        op = _UNARY[type(node.op)]
        operand = _build(node.operand, index, used)
        return lambda x, p: op(operand(x, p))

    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        # Float, so that 9**9**9 overflows to inf instead of computing a huge int.
        value = np.float64(node.value)
        return lambda x, p: value

    if isinstance(node, ast.Name):
        name = node.id
        if name == VARIABLE:
            return lambda x, p: x
        if name in index:
            used.add(name)
            i = index[name]
            return lambda x, p: p[i]
        if name in CONSTANTS:
            value = np.float64(CONSTANTS[name])
            return lambda x, p: value
        if name in FUNCTIONS:
            raise ExpressionError(
                f"{name!r} is a function; call it as {name}(...)", node.col_offset
            )
        raise ExpressionError(f"unknown name {name!r}", node.col_offset)

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        name = node.func.id
        if name not in FUNCTIONS:
            raise ExpressionError(f"unknown function {name!r}", node.col_offset)
        if (
            len(node.args) != 1
            or node.keywords
            or isinstance(node.args[0], ast.Starred)
        ):
            raise ExpressionError(
                f"{name}() takes exactly one argument", node.col_offset
            )
        func = FUNCTIONS[name]
        argument = _build(node.args[0], index, used)
        return lambda x, p: func(argument(x, p))

    position = getattr(node, "col_offset", None)
    raise ExpressionError(
        f"{_describe(node)} is not allowed in a fit expression", position
    )


def _describe(node: ast.AST) -> str:
    if isinstance(node, ast.Constant):
        return f"the constant {node.value!r}"
    if isinstance(node, ast.BinOp | ast.UnaryOp):
        return f"the operator {type(node.op).__name__}"
    return f"a {type(node).__name__} expression"
