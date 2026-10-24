"""Test 1 from the project brief: model -> JSON -> model yields equality."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from figscribe.model import (
    SCHEMA_VERSION,
    Axes,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    Histogram,
    LinePlot,
    Project,
    ResidualPlot,
    SchemaVersionError,
    dumps,
    loads,
)


def test_roundtrip_is_lossless(project: Project) -> None:
    assert loads(dumps(project)) == project


def test_roundtrip_is_idempotent(project: Project) -> None:
    once = dumps(project)
    assert dumps(loads(once)) == once


def test_roundtrip_keeps_the_encoding_of_a_source(project: Project) -> None:
    project.sources[0].encoding = "cp1252"
    assert loads(dumps(project)).sources[0].encoding == "cp1252"


def test_roundtrip_restores_concrete_artist_types(project: Project) -> None:
    axes = loads(dumps(project)).figures[0].axes
    assert [type(a) for a in axes[0].artists] == [ErrorbarPlot, FitCurve]
    assert [type(a) for a in axes[1].artists] == [ResidualPlot]


def test_roundtrip_keeps_nested_unions(project: Project) -> None:
    fit = loads(dumps(project)).figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve)
    assert fit.model.name == "gaussian"


def test_roundtrip_keeps_tuples_as_tuples(project: Project) -> None:
    legend = loads(dumps(project)).figures[0].axes[0].legend
    assert legend.position == (0.6, 0.9)
    assert isinstance(legend.position, tuple)


def test_empty_project_roundtrips() -> None:
    assert loads(dumps(Project())) == Project()


@pytest.mark.parametrize(
    ("kwargs", "error_type"),
    [
        ({"alpha": 1.5}, "less_than_equal"),
        ({"alpha": -0.1}, "greater_than_equal"),
        ({"linewidth": 0.0}, "greater_than"),
        ({"colour": "red"}, "extra_forbidden"),
    ],
)
def test_artist_validation_rejects(
    kwargs: dict, error_type: str, project: Project
) -> None:
    line = project.figures[0].axes[0].artists[0]
    assert isinstance(line, ErrorbarPlot)
    with pytest.raises(ValidationError) as exc:
        LinePlot(x=line.x, y=line.y, **kwargs)
    assert exc.value.errors()[0]["type"] == error_type


def test_strict_mode_refuses_coercion() -> None:
    with pytest.raises(ValidationError) as exc:
        Figure(dpi="300")
    assert exc.value.errors()[0]["type"] == "float_type"


def test_figure_size_must_be_positive() -> None:
    for field in ("width_mm", "height_mm", "dpi"):
        with pytest.raises(ValidationError):
            Figure(**{field: 0.0})


def test_sha256_must_look_like_a_digest() -> None:
    with pytest.raises(ValidationError):
        CsvSource(path="x.csv", sha256="abc")


def test_assignment_is_validated() -> None:
    figure = Figure()
    with pytest.raises(ValidationError):
        figure.dpi = "nope"


def test_unknown_artist_kind_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Axes.model_validate_json('{"artists": [{"kind": "pie"}]}')
    assert exc.value.errors()[0]["type"] == "union_tag_invalid"


def test_newer_schema_version_is_refused(project: Project) -> None:
    text = dumps(project).replace(
        f'"schema_version": {SCHEMA_VERSION}', '"schema_version": 99', 1
    )
    with pytest.raises(SchemaVersionError, match="schema version 99"):
        loads(text)


def test_older_schema_version_needs_a_migration(project: Project) -> None:
    text = dumps(project).replace(
        f'"schema_version": {SCHEMA_VERSION}', '"schema_version": 0', 1
    )
    with pytest.raises(SchemaVersionError, match="no migration"):
        loads(text)


@pytest.mark.parametrize(
    "text", ["{}", "not json", '{"schema_version": "1"}', '{"schema_version": true}']
)
def test_malformed_project_files_are_refused(text: str) -> None:
    with pytest.raises(SchemaVersionError):
        loads(text)


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_non_finite_floats_roundtrip(value: float, project: Project) -> None:
    # curve_fit reports inf uncertainties when the covariance cannot be
    # estimated; such a project must still load after saving.
    fit = project.figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve) and fit.result is not None
    fit.result = fit.result.model_copy(update={"uncertainties": {"a": value}})

    assert loads(dumps(project)) == project


def test_nan_survives_a_roundtrip(project: Project) -> None:
    fit = project.figures[0].axes[0].artists[1]
    assert isinstance(fit, FitCurve) and fit.result is not None
    fit.result = fit.result.model_copy(update={"reduced_chi_square": math.nan})

    loaded = loads(dumps(project)).figures[0].axes[0].artists[1]
    assert isinstance(loaded, FitCurve) and loaded.result is not None
    assert math.isnan(loaded.result.reduced_chi_square)


def test_bin_count_must_be_positive(project: Project) -> None:
    ref = project.figures[0].axes[0].artists[0].x
    with pytest.raises(ValidationError):
        Histogram(values=ref, bins=0)
