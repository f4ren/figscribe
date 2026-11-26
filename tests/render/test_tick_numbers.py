"""The numbers figscribe writes along an axis itself."""

from __future__ import annotations

from matplotlib.backends.backend_agg import FigureCanvasAgg

from figscribe.model import Axes, AxisSpec, Figure
from figscribe.render import render


def _labels(spec: AxisSpec, **figure_fields) -> list[str]:
    """The x tick numbers of an empty panel whose x axis is `spec`."""
    fig = render(Figure(axes=[Axes(x=spec)], **figure_fields), None)
    FigureCanvasAgg(fig).draw()
    return [t.get_text() for t in fig.axes[0].get_xticklabels()]


def test_a_stepped_axis_with_a_prefix_writes_zero_as_zero() -> None:
    # MultipleLocator places this "zero" at -6.9e-18.
    spec = AxisSpec(prefix="m", limits=(-0.0533, 0.0533), major_step=0.01)
    assert "0" in _labels(spec)


def test_a_prefixed_axis_writes_the_minus_sign_as_matplotlib_does() -> None:
    labels = _labels(AxisSpec(prefix="m", limits=(-0.05, 0.05)))
    assert labels[0].startswith("−") and not any("-" in text for text in labels)
