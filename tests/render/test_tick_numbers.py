"""The numbers figscribe writes along an axis itself, and the decimal comma."""

from __future__ import annotations

import numpy as np
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import LogNorm
from pydantic import ValidationError

from figscribe.model import (
    ArrayRef,
    Axes,
    AxisSpec,
    Colorbar,
    ColorMesh,
    Figure,
)
from figscribe.render import render


def _drawn(figure: Figure, data=None):
    fig = render(figure, data)
    FigureCanvasAgg(fig).draw()
    return fig


def _texts(axis, which: str = "major") -> list[str]:
    """The numbers of the ticks within the axis's range."""
    low, high = sorted(axis.get_view_interval())
    ticks = (
        zip(axis.get_majorticklocs(), axis.get_majorticklabels(), strict=False)
        if which == "major"
        else zip(axis.get_minorticklocs(), axis.get_minorticklabels(), strict=False)
    )
    return [label.get_text() for at, label in ticks if low <= at <= high]


def _labels(spec: AxisSpec, **figure_fields) -> list[str]:
    """The x tick numbers of an empty panel whose x axis is `spec`."""
    fig = _drawn(Figure(axes=[Axes(x=spec)], **figure_fields))
    return _texts(fig.axes[0].xaxis)


# --- zero and the minus sign ---------------------------------------------------


@pytest.mark.parametrize("number_format", ["auto", "scientific"])
def test_a_stepped_axis_writes_zero_as_zero(number_format) -> None:
    # MultipleLocator places this "zero" at -6.9e-18.
    spec = AxisSpec(
        prefix="m",
        number_format=number_format,
        limits=(-0.0533, 0.0533),
        major_step=0.01,
    )
    assert "0" in _labels(spec)


def test_a_prefixed_axis_writes_the_minus_sign_as_matplotlib_does() -> None:
    labels = _labels(AxisSpec(prefix="m", limits=(-0.05, 0.05)))
    assert labels[0].startswith("−") and not any("-" in text for text in labels)


# --- number formats ------------------------------------------------------------


def test_fixed_decimals() -> None:
    spec = AxisSpec(number_format="fixed", decimals=2, limits=(-1, 1), major_step=0.5)
    assert _labels(spec) == ["−1.00", "−0.50", "0.00", "0.50", "1.00"]


def test_fixed_decimals_never_write_a_negative_zero() -> None:
    spec = AxisSpec(number_format="fixed", decimals=0, ticks=[-0.4, 0.4])
    assert _labels(spec) == ["0", "0"]


def test_scientific_numbers_are_a_power_of_ten_each() -> None:
    spec = AxisSpec(number_format="scientific", limits=(0, 400), major_step=200)
    assert _labels(spec) == [
        "0",
        r"$\mathdefault{2.0\times10^{2}}$",
        r"$\mathdefault{4.0\times10^{2}}$",
    ]


def test_a_format_applies_to_the_prefixed_value() -> None:
    spec = AxisSpec(
        prefix="k", number_format="fixed", limits=(0, 2000), major_step=1000
    )
    assert _labels(spec) == ["0.0", "1.0", "2.0"]


def test_typed_tick_labels_win_over_the_format() -> None:
    spec = AxisSpec(number_format="fixed", ticks=[1, 2], tick_labels=["a.b", "c"])
    assert _labels(spec, decimal_comma=True) == ["a.b", "c"]


def test_a_log_axis_with_a_format_leaves_out_matplotlibs_minor_numbers() -> None:
    spec = AxisSpec(scale="log", number_format="fixed", limits=(0.05, 3000))
    fig = _drawn(Figure(axes=[Axes(x=spec)]))
    assert _texts(fig.axes[0].xaxis) == ["0.1", "1.0", "10.0", "100.0", "1000.0"]
    assert set(_texts(fig.axes[0].xaxis, "minor")) == {""}


@pytest.mark.parametrize("decimals", [-1, 11])
def test_decimals_are_bounded(decimals) -> None:
    with pytest.raises(ValidationError):
        AxisSpec(decimals=decimals)


@pytest.mark.parametrize(
    "spec",
    [
        AxisSpec(scale="log", prefix="k", limits=(200, 800)),
        AxisSpec(scale="log", number_format="fixed", decimals=0, limits=(200, 800)),
    ],
    ids=["prefix", "fixed"],
)
def test_a_log_axis_of_less_than_a_decade_keeps_numbers(spec) -> None:
    """There Matplotlib numbers the minor ticks, having no major one: leaving
    those out left the axis without a single number."""
    fig = _drawn(Figure(axes=[Axes(x=spec)]))
    numbers = [text for text in _texts(fig.axes[0].xaxis, "minor") if text]
    assert len(numbers) >= 3
    allowed = {0.2, 0.3, 0.4, 0.6, 200, 300, 400, 600}
    assert {float(text) for text in numbers} <= allowed


# --- the decimal comma ---------------------------------------------------------


def test_the_comma_replaces_the_point_of_matplotlibs_own_numbers() -> None:
    labels = _labels(AxisSpec(limits=(0, 1)), decimal_comma=True)
    assert labels[:3] == ["0,0", "0,2", "0,4"]


def test_without_the_switch_the_point_stays() -> None:
    assert _labels(AxisSpec(limits=(0, 1)))[:2] == ["0.0", "0.2"]


def test_the_comma_in_the_offset_at_the_end_of_an_axis() -> None:
    spec = AxisSpec(limits=(1000.15, 1000.55))
    fig = _drawn(Figure(axes=[Axes(x=spec)], decimal_comma=True))
    axis = fig.axes[0].xaxis
    assert all("." not in text for text in _texts(axis))
    assert (
        axis.get_offset_text().get_text()
        and "." not in axis.get_offset_text().get_text()
    )


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (AxisSpec(number_format="fixed", ticks=[1.5]), "1,5"),
        (AxisSpec(prefix="k", ticks=[1500.0]), "1,5"),
        (
            AxisSpec(number_format="scientific", ticks=[150.0]),
            r"$\mathdefault{1{,}5\times10^{2}}$",
        ),
    ],
)
def test_the_comma_in_numbers_figscribe_writes(spec, expected) -> None:
    assert _labels(spec, decimal_comma=True) == [expected]


def test_the_comma_on_a_log_axis_is_set_without_a_space() -> None:
    spec = AxisSpec(scale="log", limits=(100, 1000), ticks=[150.0])
    assert _labels(spec, decimal_comma=True) == [r"$\mathdefault{1{,}5\times10^{2}}$"]


def test_the_comma_on_both_y_axes() -> None:
    panel = Axes(y=AxisSpec(limits=(0, 1)), y_right=AxisSpec(limits=(0, 0.5)))
    left, right = _drawn(Figure(axes=[panel], decimal_comma=True)).axes
    assert _texts(left.yaxis)[1] == "0,2" and _texts(right.yaxis)[1] == "0,1"


@pytest.mark.parametrize("norm", ["linear", "log"])
def test_the_comma_on_a_color_bar(norm) -> None:
    z = np.array([[2.0, 3.0], [4.0, 4.5]])
    mesh = ColorMesh(c=ArrayRef(source="s"), norm=norm, colorbar=Colorbar())
    figure = Figure(axes=[Axes(artists=[mesh])], decimal_comma=True)
    fig = _drawn(figure, lambda ref: z)
    bar = fig.axes[1].yaxis
    texts = _texts(bar) + _texts(bar, "minor")
    assert any(texts) and not any("." in text for text in texts)
    if norm == "linear":
        assert any("," in text for text in texts)
    else:
        assert isinstance(fig.axes[0].collections[0].norm, LogNorm)
