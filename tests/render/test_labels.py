"""How an axis label and its unit are joined."""

from __future__ import annotations

import pytest

from figscribe.model import Axes, AxisSpec, Figure, GridLayout, Inset, PanelLabels
from figscribe.render import axis_label
from figscribe.render.labels import panel_labels


@pytest.mark.parametrize(
    ("unit_format", "expected"),
    [
        ("slash", "$U$ / V"),
        ("parentheses", "$U$ (V)"),
        ("brackets", "$U$ [V]"),
    ],
)
def test_unit_formats(unit_format: str, expected: str) -> None:
    assert axis_label(AxisSpec(label="$U$", unit="V"), unit_format) == expected


def test_compound_unit_is_parenthesised_after_a_slash() -> None:
    # "v / m/s" would read as v divided by m divided by s.
    spec = AxisSpec(label="$v$", unit="m/s")
    assert axis_label(spec, "slash") == "$v$ / (m/s)"
    assert axis_label(spec, "parentheses") == "$v$ (m/s)"


def test_label_without_unit_is_left_alone() -> None:
    assert axis_label(AxisSpec(label="counts"), "slash") == "counts"


def test_no_label_means_no_label_even_with_a_unit() -> None:
    assert axis_label(AxisSpec(unit="V"), "slash") is None


def test_parentheses_are_the_default() -> None:
    from figscribe.model import Figure

    assert Figure().unit_format == "parentheses"


def test_unit_is_set_as_text_so_it_stays_upright() -> None:
    # The quantity symbol is italic because the user writes it as math; the
    # unit must not be pulled into math mode, where it would turn italic too.
    label = axis_label(AxisSpec(label="$U$", unit="mV"), "parentheses")
    assert label == "$U$ (mV)"
    assert label.count("$") == 2


def _grid_with_inset() -> tuple[Figure, list[Axes]]:
    """A 2 × 2 grid listed out of reading order, with an inset in the
    second panel (top right)."""
    top_left, top_right = Axes(), Axes(col=1)
    bottom_left, bottom_right = Axes(row=1), Axes(row=1, col=1)
    inset = Axes(inset=Inset(parent=top_right.id))
    axes = [bottom_right, inset, top_right, bottom_left, top_left]
    figure = Figure(layout=GridLayout(rows=2, cols=2), axes=axes)
    return figure, [top_left, top_right, inset, bottom_left, bottom_right]


def test_panels_are_lettered_in_reading_order() -> None:
    figure, (top_left, top_right, inset, bottom_left, bottom_right) = _grid_with_inset()
    assert panel_labels(figure) == {}
    figure.panel_labels = PanelLabels()
    texts = {figure.axes[i].id: text for i, text in panel_labels(figure).items()}
    assert texts == {
        top_left.id: "(a)",
        top_right.id: "(b)",
        bottom_left.id: "(c)",
        bottom_right.id: "(d)",
    }
    figure.panel_labels = PanelLabels(insets=True)
    texts = {figure.axes[i].id: text for i, text in panel_labels(figure).items()}
    assert [texts[a.id] for a in (top_left, top_right, inset, bottom_left)] == [
        "(a)",
        "(b)",
        "(c)",
        "(d)",
    ]


def test_a_panel_spanning_rows_comes_before_those_beside_it() -> None:
    tall, upper, lower = Axes(rowspan=2), Axes(col=1), Axes(row=1, col=1)
    figure = Figure(
        layout=GridLayout(rows=2, cols=2),
        axes=[lower, upper, tall],
        panel_labels=PanelLabels(style="A"),
    )
    texts = {figure.axes[i].id: text for i, text in panel_labels(figure).items()}
    assert texts == {tall.id: "A", upper.id: "B", lower.id: "C"}


@pytest.mark.parametrize(
    ("style", "first", "twenty_seventh"),
    [("(a)", "(a)", "(aa)"), ("a)", "a)", "aa)"), ("a", "a", "aa"), ("A", "A", "AA")],
)
def test_label_styles(style: str, first: str, twenty_seventh: str) -> None:
    figure = Figure(
        layout=GridLayout(rows=1, cols=28),
        axes=[Axes(col=i) for i in range(28)],
        panel_labels=PanelLabels(style=style),
    )
    texts = panel_labels(figure)
    assert texts[0] == first and texts[26] == twenty_seventh
    assert len(set(texts.values())) == 28
