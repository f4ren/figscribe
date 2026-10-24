"""Zooming, panning and dragging the legend in the preview."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from figscribe.commands import SetField
from figscribe.gui import Document
from figscribe.gui.preview import Preview


@pytest.fixture
def preview(qtbot, example: Path) -> Preview:
    widget = Preview(Document.open(example))
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    widget.show()
    qtbot.waitExposed(widget)
    widget.grab()  # paint once, which places the image
    return widget


def _axes(preview: Preview):
    return preview._figure.axes[0]


def _centre(preview: Preview, ax) -> QPointF:
    box = ax.bbox
    return preview._to_widget((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)


def test_zooming_keeps_the_point_under_the_cursor(preview: Preview) -> None:
    ax = _axes(preview)
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    middle = ax.transData.inverted().transform(
        ((ax.bbox.x0 + ax.bbox.x1) / 2, (ax.bbox.y0 + ax.bbox.y1) / 2)
    )
    preview.zoom(_centre(preview, ax), 2.0)
    (vx0, vx1), (vy0, vy1) = preview.view[ax.get_gid()]
    assert vx1 - vx0 == pytest.approx((x1 - x0) / 2, rel=1e-3)
    assert vy1 - vy0 == pytest.approx((y1 - y0) / 2, rel=1e-3)
    assert (vx0 + vx1) / 2 == pytest.approx(middle[0], abs=1e-6 * (x1 - x0))
    assert _axes(preview).get_xlim() == pytest.approx((vx0, vx1))
    assert "Zoomed here only" in preview.caption()
    assert not preview.view_bar.isHidden()
    assert not preview.document.history.can_undo  # the model is untouched


def test_zoom_along_one_axis(preview: Preview) -> None:
    ax = _axes(preview)
    ylim = ax.get_ylim()
    preview.zoom(_centre(preview, ax), 2.0, axis="x")
    assert preview.view[ax.get_gid()][1] == pytest.approx(ylim)


def test_the_view_becomes_the_axis_range(preview: Preview) -> None:
    ax = _axes(preview)
    preview.zoom(_centre(preview, ax), 1.6)
    xlim, ylim = preview.view[ax.get_gid()]
    preview.view_bar.adopt.click()
    axes = preview.document.figure.axes[0]
    assert axes.x.limits == pytest.approx(xlim) and axes.y.limits == pytest.approx(ylim)
    assert preview.document.history.undo_text == "Use the view as axis ranges"
    assert preview.view == {} and preview.view_bar.isHidden()
    assert "Exactly as exported" in preview.caption()


def test_reset_drops_the_view(preview: Preview) -> None:
    preview.zoom(_centre(preview, _axes(preview)), 3.0)
    preview.view_bar.reset.click()
    assert preview.view == {}
    assert preview.document.figure.axes[0].x.limits is None


def test_panning_moves_the_data_with_the_mouse(preview: Preview) -> None:
    ax = _axes(preview)
    x0, x1 = ax.get_xlim()
    preview.pan(ax.get_gid(), 100, 0)  # mouse to the right
    vx0, vx1 = preview.view[ax.get_gid()][0]
    assert vx0 < x0 and vx1 - vx0 == pytest.approx(x1 - x0)


def test_a_log_axis_zooms_in_its_own_scale(preview: Preview) -> None:
    axes = preview.document.figure.axes[0]
    preview.document.push(SetField(axes.id, ("x", "scale"), "log"))
    preview.document.push(SetField(axes.id, ("x", "limits"), (0.1, 10.0)))
    preview.grab()
    preview.zoom(_centre(preview, _axes(preview)), 2.0, axis="x")
    vx0, vx1 = preview.view[axes.id][0]
    assert vx0 > 0 and vx0 * vx1 == pytest.approx(1.0, rel=1e-3)  # centred at 1


def test_the_wheel_zooms(qtbot, preview: Preview) -> None:
    point = _centre(preview, _axes(preview))
    event = QWheelEvent(
        point,
        preview.mapToGlobal(point),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    preview.wheelEvent(event)
    assert preview.view


def test_dragging_the_background_pans(qtbot, preview: Preview) -> None:
    ax = _axes(preview)
    start = _centre(preview, ax).toPoint() + QPoint(0, 60)
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(preview, start + QPoint(40, 0))
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=start + QPoint(40, 0))
    assert ax.get_gid() in preview.view
    assert preview.document.selected is None  # a drag selects nothing


def test_dragging_the_legend_moves_it(qtbot, preview: Preview) -> None:
    axes = preview.document.figure.axes[0]
    legend = _axes(preview).get_legend()
    before = legend.get_window_extent()
    corner = preview._to_widget(before.x0 + 5, before.y0 + 5).toPoint()
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=corner)
    qtbot.mouseMove(preview, corner + QPoint(-60, 40))
    assert preview._moved_legend_rect() is not None
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=corner + QPoint(-60, 40))
    assert preview.document.figure.axes[0].legend.position is not None
    assert preview.document.history.undo_text == "Set legend position"
    after = _axes(preview).get_legend().get_window_extent()
    assert after.x0 == pytest.approx(before.x0 - 60, abs=1.5)
    assert after.y0 == pytest.approx(before.y0 - 40, abs=1.5)
    assert preview.view == {}  # moving the legend is no pan
    assert axes.id == preview.document.figure.axes[0].id


def test_escape_resets_and_a_new_document_forgets_the_view(qtbot, preview) -> None:
    preview.zoom(_centre(preview, _axes(preview)), 2.0)
    qtbot.keyClick(preview, Qt.Key.Key_Escape)
    assert preview.view == {}
    preview.zoom(_centre(preview, _axes(preview)), 2.0)
    preview.set_document(Document())
    assert preview.view == {}


def _drawn(qtbot, preview: Preview) -> None:
    """Let the preview draw what zooming and panning asked for."""
    qtbot.waitUntil(lambda: not preview.redraw_pending, timeout=5000)


def test_zooming_and_panning_do_not_render_the_model_again(
    qtbot, preview: Preview, monkeypatch
) -> None:
    from figscribe.gui import preview as module

    renders = []
    real = module.render
    monkeypatch.setattr(
        module, "render", lambda *a, **k: renders.append(1) or real(*a, **k)
    )
    figure = preview._figure
    preview.zoom(_centre(preview, _axes(preview)), 1.5)
    preview.pan(_axes(preview).get_gid(), 30, 10)
    _drawn(qtbot, preview)
    assert renders == [] and preview._figure is figure


def test_quick_moves_are_drawn_once(qtbot, preview: Preview, monkeypatch) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    draws = []
    real = FigureCanvasAgg.draw
    monkeypatch.setattr(FigureCanvasAgg, "draw", lambda c: draws.append(1) or real(c))
    gid = _axes(preview).get_gid()
    for _ in range(5):
        preview.pan(gid, 10, 0)
    _drawn(qtbot, preview)
    assert len(draws) == 1
    assert preview.view[gid][0] != preview.document.figure.axes[0].x.limits


def test_the_quick_view_looks_exactly_like_a_full_render(qtbot, preview) -> None:
    preview.zoom(_centre(preview, _axes(preview)), 1.7)
    preview.pan(_axes(preview).get_gid(), -25, 15)
    _drawn(qtbot, preview)
    quick = preview._image.copy()
    preview.refresh()
    assert preview._image == quick


def test_zooming_far_out_keeps_the_tick_limit(qtbot, preview) -> None:
    from matplotlib.ticker import MultipleLocator

    axes = preview.document.figure.axes[0]
    preview.document.push(SetField(axes.id, ("x", "major_step"), 0.25))
    preview.zoom(_centre(preview, _axes(preview)), 0.01, axis="x")  # 100 times out
    _drawn(qtbot, preview)
    assert not isinstance(_axes(preview).xaxis.get_major_locator(), MultipleLocator)
