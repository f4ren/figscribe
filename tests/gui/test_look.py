"""The look: theme, names on screen, and the redesigned panels' behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QDropEvent, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QLabel, QToolButton

from figscribe.commands import InsertItem, SetField
from figscribe.gui import Document, MainWindow, theme
from figscribe.gui.app import create_window
from figscribe.gui.names import artist_name, panel_name, with_error
from figscribe.gui.outline import VISIBLE_ROLE, Outline
from figscribe.gui.properties import PropertyPanel
from figscribe.model import (
    Axes,
    Figure,
    FitCurve,
    FitResult,
    GridLayout,
    PredefinedFit,
    ResidualPlot,
)


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


def _with_fit(document: Document) -> FitCurve:
    """Turn the example into two panels: data with a fit, residuals below."""
    figure = document.figure
    data = figure.axes[0].artists[0]
    fit = FitCurve(
        target=data.id,
        model=PredefinedFit(name="gaussian"),
        result=FitResult(
            parameters={"a": 1.0101, "mu": 4.9671},
            uncertainties={"a": 0.0182, "mu": 0.0233},
            reduced_chi_square=0.751,
        ),
    )
    document.push(SetField(figure.id, ("layout",), GridLayout(rows=2)))
    document.push(InsertItem(figure.axes[0].id, "artists", fit))
    residuals = Axes(row=1, artists=[ResidualPlot(target=fit.id)])
    document.push(InsertItem(figure.id, "axes", residuals))
    return fit


# --- theme and names ------------------------------------------------------------


def test_the_bundled_fonts_load(qapp) -> None:
    theme.load_fonts()
    families = QFontDatabase.families()
    assert theme.SANS in families and theme.MONO in families


def test_icons_render(qapp) -> None:
    for name in theme._ICONS:
        assert not theme.icon(name, theme.ACCENT).pixmap(16, 16).isNull()


def test_apply_styles_the_application(qapp: QApplication) -> None:
    theme.apply(qapp)
    try:
        assert "QToolBar#main" in qapp.styleSheet()
        assert "chevron-down.svg" in qapp.styleSheet()
    finally:
        qapp.setStyleSheet("")


def test_apply_gives_the_application_its_icon(qapp: QApplication) -> None:
    theme.apply(qapp)
    try:
        sizes = qapp.windowIcon().availableSizes()
        assert QSize(16, 16) in sizes and QSize(512, 512) in sizes
    finally:
        qapp.setStyleSheet("")
        qapp.setWindowIcon(QIcon())


def test_small_icons_fill_their_square(qapp) -> None:
    """Up to 48 px the drawing has no margin, so it stays legible."""
    icon = theme.app_icon()
    small = icon.pixmap(QSize(16, 16)).toImage()
    large = icon.pixmap(QSize(512, 512)).toImage()
    assert small.size() == QSize(16, 16) and large.size() == QSize(512, 512)
    assert small.pixelColor(8, 1).alpha() == 255
    assert large.pixelColor(256, 20).alpha() == 0


@pytest.mark.parametrize(
    ("color", "index", "expected"),
    [
        (None, 0, "#1f77b4"),
        (None, 11, "#ff7f0e"),
        ("C3", 0, "#d62728"),
        ("tab:green", 0, "#2ca02c"),
        ("#123456", 0, "#123456"),
        ("not a color", 0, theme.INK),
    ],
)
def test_plot_colors_follow_matplotlib(color, index, expected) -> None:
    assert theme.plot_color(color, index) == expected


@pytest.mark.parametrize(
    ("value", "error", "expected"),
    [
        (4.9671, 0.0233, "4.967 ± 0.023"),
        (1234.5, 12.0, "1234 ± 12"),
        (0.5, None, "0.5"),
        (2.0, 0.0, "2"),
        (3.0e-7, 1.0e-8, "3.000e-07 ± 1.00e-08"),
    ],
)
def test_values_are_rounded_to_their_error(value, error, expected) -> None:
    assert with_error(value, error) == expected


def test_panels_are_named_by_letter_and_place() -> None:
    top, bottom = Axes(row=0), Axes(row=1)
    figure = Figure(layout=GridLayout(rows=2), axes=[top, bottom])
    assert panel_name(figure, top) == "Panel A · top"
    assert panel_name(figure, bottom) == "Panel B · bottom"
    assert panel_name(Figure(axes=[top]), top) == "Panel A"
    bottom.title = "Residuals"
    assert panel_name(figure, bottom) == "Panel B · Residuals"


def test_unlabelled_plots_are_named_by_what_they_are(document) -> None:
    fit = _with_fit(document)
    assert artist_name(fit) == "Gaussian fit"
    assert artist_name(document.figure.axes[0].artists[0]) == "measurement"


# --- outline --------------------------------------------------------------------


@pytest.fixture
def outline(qtbot, document: Document) -> Outline:
    widget = Outline(document)
    qtbot.addWidget(widget)
    widget.resize(260, 600)
    return widget


def test_outline_heads_each_panel(outline: Outline, document) -> None:
    _with_fit(document)
    figure = document.figure
    assert outline.item_for(figure.axes[0].id).text(0) == "PANEL A · TOP"
    assert outline.item_for(figure.axes[1].id).text(0) == "PANEL B · BOTTOM"
    assert outline.item_for(figure.id).text(1) == "85 × 60 mm"


def test_outline_shows_the_fit_quality(outline: Outline, document) -> None:
    fit = _with_fit(document)
    assert outline.item_for(fit.id).text(1) == "χ²ᵣ 0.75"


def test_the_eye_hides_and_shows_a_plot(outline: Outline, document) -> None:
    artist = document.figure.axes[0].artists[0]
    item = outline.item_for(artist.id)
    assert item.data(0, VISIBLE_ROLE) is True
    outline.itemClicked.emit(item, 1)
    assert document.figure.axes[0].artists[0].visible is False
    assert outline.item_for(artist.id).data(0, VISIBLE_ROLE) is False
    assert document.history.undo_text == "Set visible"

    outline.itemClicked.emit(outline.item_for(artist.id), 0)  # the name: no toggle
    assert document.figure.axes[0].artists[0].visible is False


def test_data_files_list_their_columns(outline: Outline, document) -> None:
    source = document.project.sources[0]
    assert outline.item_for(source.id).text(1) == "3 columns"
    chips = {label.text() for label in outline.viewport().findChildren(QLabel)}
    assert {"t", "U", "dU"} <= chips


def test_links_ask_for_a_plot_or_data(qtbot, outline: Outline, document) -> None:
    axes = document.figure.axes[0]
    with qtbot.waitSignal(outline.add_requested) as signal:
        _link(outline, "+ Add to panel A").click()
    assert signal.args == [axes.id]

    outline.set_document(Document())
    with qtbot.waitSignal(outline.import_requested):
        _link(outline, "+ Add data…").click()
    with qtbot.waitSignal(outline.add_requested) as signal:
        _link(outline, "+ Add a plot").click()
    assert signal.args == [outline.document.figure.id]


def _link(outline: Outline, text: str) -> QToolButton:
    for button in outline.viewport().findChildren(QToolButton):
        if button.text() == text and button.isVisibleTo(outline):
            return button
    raise AssertionError(f"no link {text!r}")


# --- property panel -------------------------------------------------------------


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def test_fields_are_grouped_in_sections(panel: PropertyPanel, document) -> None:
    document.select(document.figure.axes[0].artists[0].id)
    assert list(panel.sections) == ["Data", "Look", "Legend", "More"]
    assert not panel.sections["Look"].body.isHidden()
    assert panel.sections["More"].body.isHidden()
    assert panel._kicker.text() == "ERROR BAR PLOT"
    assert panel._title.text() == "measurement"

    document.select(document.figure.axes[0].id)
    assert list(panel.sections)[:4] == ["Panel", "Axes", "Position", "Legend"]


def test_an_opened_section_stays_open(panel: PropertyPanel, document) -> None:
    artist = document.figure.axes[0].artists[0]
    document.select(artist.id)
    panel.sections["More"].header.setChecked(True)
    document.select(None)
    document.select(artist.id)
    assert panel.sections["More"].expanded


def test_swatches_and_marker_buttons_commit(panel: PropertyPanel, document) -> None:
    document.select(document.figure.axes[0].artists[0].id)
    panel.editors[("color",)].swatches["C1"].click()
    assert document.figure.axes[0].artists[0].color == "C1"
    assert panel.editors[("color",)].swatches["C1"].isChecked()

    combo = panel.editors[("marker",)].widget
    texts = [combo.itemText(i) for i in range(combo.count())]
    combo.activated.emit(texts.index("Square"))
    assert document.figure.axes[0].artists[0].marker == "s"
    combo = panel.editors[("marker",)].widget
    assert combo.currentText() == "Square"
    assert "No marker" in texts  # "none": the error bars alone


def test_line_styles_have_names(panel: PropertyPanel, document) -> None:
    document.select(document.figure.axes[0].artists[0].id)
    combo = panel.editors[("linestyle",)].widget
    assert combo.currentText() == "None"
    combo.activated.emit(combo.findText("Dashed"))
    assert document.figure.axes[0].artists[0].linestyle == "--"


def test_a_fit_shows_its_result(panel: PropertyPanel, document) -> None:
    fit = _with_fit(document)
    document.select(fit.id)
    texts = [label.text() for label in panel.widget().findChildren(QLabel)]
    assert "μ" in texts and "4.967 ± 0.023" in texts and "0.75" in texts
    assert "measurement" in texts  # what it is fitted to, by name


# --- main window ----------------------------------------------------------------


@pytest.fixture
def window(qtbot, example: Path) -> MainWindow:
    win = create_window([str(example)])
    qtbot.addWidget(win)
    win.ask = lambda title, question: True
    return win


def test_the_toolbar_names_the_project(window: MainWindow) -> None:
    assert window._project_name.text() == "scan"
    assert window._save_state.text() == "Saved"
    window.document.push(SetField(window.document.figure.id, ("name",), "X"))
    assert window._save_state.text() == "Unsaved changes"
    window.ask = lambda title, question: True
    window.new_project()
    assert window._project_name.text() == "Untitled"
    assert window._save_state.text() == "Not saved yet"


def test_problems_show_only_when_there_are_some(window: MainWindow) -> None:
    assert window.problems_dock.isHidden()
    figure = window.document.figure  # two ratios for one column
    window.document.push(SetField(figure.id, ("layout", "width_ratios"), [1.0, 2.0]))
    assert not window.problems_dock.isHidden()
    window.document.undo()
    assert window.problems_dock.isHidden()


def _drop(window: MainWindow, path: Path) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)


def test_dropping_data_imports_it(window: MainWindow, tmp_path: Path) -> None:
    imported = []
    window.import_csv = imported.append
    data = tmp_path / "more.csv"
    data.write_text("a,b\n1,2\n", encoding="utf-8")
    _drop(window, data)
    assert imported == [data]


def test_dropping_a_project_opens_it(window: MainWindow, example: Path) -> None:
    window.new_project()
    _drop(window, example)
    assert window.document.path == example


def _contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two #RRGGBB colors."""

    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_check_boxes_can_be_seen() -> None:
    """A control needs 3:1 against what is around it (WCAG 1.4.11); the
    style's own check box had a 1.45:1 edge and was hard to find."""
    for ground in (theme.SURFACE, theme.GROUND):
        assert _contrast(theme.CHECK_BORDER, ground) >= 3
        assert _contrast(theme.ACCENT, ground) >= 3
    assert "QCheckBox::indicator" in theme.STYLE_SHEET
