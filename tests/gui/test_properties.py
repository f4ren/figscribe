"""The property panel: generated editors that change the model by command."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel

from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel, spec_for
from figscribe.model import (
    Annotation,
    AxisSpec,
    ColumnRef,
    CsvSource,
    ErrorbarPlot,
    Figure,
    FitCurve,
    GridLayout,
    Legend,
    LinePlot,
)


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def _figure(document):
    return document.project.figures[0]


def _axes(document):
    return _figure(document).axes[0]


def _artist(document):
    return _axes(document).artists[0]


def _type(panel: PropertyPanel, path: tuple[str, ...], text: str) -> None:
    line = panel.editors[path].line
    line.setText(text)
    line.editingFinished.emit()


def test_shows_a_hint_without_selection(panel: PropertyPanel) -> None:
    assert panel.editors == {}
    texts = [label.text() for label in panel.widget().findChildren(QLabel)]
    assert any("Select" in t for t in texts)


@pytest.mark.parametrize(
    ("cls", "expected", "absent"),
    [
        (
            Figure,
            {("name",), ("width_mm",), ("dpi",), ("unit_format",), ("layout", "rows")},
            {("id",), ("axes",)},
        ),
        (
            ErrorbarPlot,
            {("label",), ("alpha",), ("x",), ("yerr",), ("color",), ("capsize",)},
            {("id",), ("kind",)},
        ),
    ],
)
def test_every_simple_field_gets_an_editor(
    panel: PropertyPanel, document: Document, cls, expected, absent
) -> None:
    obj = _figure(document) if cls is Figure else _artist(document)
    document.select(obj.id)
    assert expected <= set(panel.editors)
    assert not absent & set(panel.editors)


def test_a_panel_links_its_axes_and_nests_its_legend(panel, document) -> None:
    document.select(_axes(document).id)
    assert ("legend", "visible") in panel.editors
    assert ("x", "label") not in panel.editors  # each axis has its own form
    assert set(panel.axis_links) == {"x", "y"}
    assert panel.axis_links["x"].text().startswith("X axis\nt (s) · linear")


def test_a_number_commits_as_one_undo_step(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    _type(panel, ("width_mm",), "175")
    assert _figure(document).width_mm == 175.0
    assert document.history.undo_text == "Set width mm"
    document.undo()
    assert panel.editors[("width_mm",)].line.text() == "85.0"


def test_an_unchanged_value_pushes_nothing(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    _type(panel, ("width_mm",), "85.0")
    assert not document.history.can_undo


def test_a_refused_value_is_reported_and_reverted(
    panel: PropertyPanel, document
) -> None:
    document.select(_figure(document).id)
    _type(panel, ("dpi",), "-5")
    assert _figure(document).dpi == 300.0
    assert "dpi" in panel.error
    assert panel.editors[("dpi",)].line.text() == "300.0"
    assert not document.history.can_undo

    _type(panel, ("dpi",), "150")
    assert _figure(document).dpi == 150.0
    assert panel._error.isHidden()


def test_text_that_is_no_number_is_reported(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    _type(panel, ("height_mm",), "tall")
    assert "not a number" in panel.error
    assert not document.history.can_undo


def test_numbers_typed_with_a_decimal_comma(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    _type(panel, ("height_mm",), "62,5")
    assert _figure(document).height_mm == 62.5
    _type(panel, ("height_mm",), "inf")
    assert "'inf'" in panel.error
    assert _figure(document).height_mm == 62.5


def test_empty_text_clears_an_optional_field(panel: PropertyPanel, document) -> None:
    artist = _artist(document)
    document.select(artist.id)
    _type(panel, ("label",), "")
    assert _artist(document).label is None
    _type(panel, ("label",), "data")
    assert _artist(document).label == "data"


def test_a_color_matplotlib_does_not_know_is_reported(
    panel: PropertyPanel, document
) -> None:
    document.select(_artist(document).id)
    _type(panel, ("color",), "blu")
    assert "'blu' is not a color" in panel.error
    assert _artist(document).color is None


def test_literals_are_a_choice(panel: PropertyPanel, document) -> None:
    document.select(_axes(document).id)
    combo = panel.editors[("legend", "location")].widget
    assert isinstance(combo, QComboBox)
    combo.activated.emit(combo.findText("upper left"))
    assert _axes(document).legend.location == "upper left"


def test_booleans_are_a_checkbox(panel: PropertyPanel, document) -> None:
    document.select(_axes(document).id)
    box = panel.editors[("legend", "visible")].widget
    assert isinstance(box, QCheckBox) and box.isChecked()
    box.setChecked(False)
    assert _axes(document).legend.visible is False


def test_pairs_and_lists_of_numbers(panel: PropertyPanel, document) -> None:
    document.select(_axes(document).id)
    _type(panel, ("legend", "position"), "0.1, 0.9")
    assert _axes(document).legend.position == (0.1, 0.9)
    _type(panel, ("legend", "position"), "3")
    assert "two numbers" in panel.error
    _type(panel, ("legend", "position"), "")
    assert _axes(document).legend.position is None

    document.select(_figure(document).id)
    _type(panel, ("layout", "width_ratios"), "1, 2.5")
    assert _figure(document).layout.width_ratios == [1.0, 2.5]


def test_whole_numbers(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    _type(panel, ("layout", "rows"), "2")
    assert _figure(document).layout.rows == 2
    _type(panel, ("layout", "rows"), "1.5")
    assert "whole number" in panel.error


def test_columns_are_chosen_from_the_sources(panel: PropertyPanel, document) -> None:
    artist = _artist(document)
    source = document.project.sources[0]
    document.select(artist.id)
    combo = panel.editors[("y",)].widget
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts == [f"{source.path}: {c}" for c in source.columns]

    combo.activated.emit(texts.index(f"{source.path}: dU"))
    assert _artist(document).y == ColumnRef(source=source.id, column="dU")

    optional = panel.editors[("xerr",)].widget
    assert optional.itemText(0) == "no x errors"
    assert optional.currentIndex() == 0


def test_nested_fields_explain_themselves_in_their_own_words(
    panel: PropertyPanel, document
) -> None:
    from figscribe.gui.properties import tip_for
    from figscribe.model import Colorbar, LinePlot

    document.select(_axes(document).id)
    location = panel.editors[("legend", "location")].widget
    assert "upper right" in location.toolTip()
    assert tip_for(Colorbar, "label") != tip_for(LinePlot, "label")


def test_a_dangling_column_is_shown_as_missing(panel: PropertyPanel, document) -> None:
    artist = _artist(document)
    artist.y = ColumnRef(source="gone", column="U")
    document.select(artist.id)
    combo = panel.editors[("y",)].widget
    assert "(missing)" in combo.currentText()


def test_colors_by_text_or_picker(panel: PropertyPanel, document) -> None:
    document.select(_artist(document).id)
    _type(panel, ("color",), "tab:red")
    assert _artist(document).color == "tab:red"

    panel.pick_color = lambda current: "#00ff00"
    panel.editors[("color",)].button.click()
    assert _artist(document).color == "#00ff00"
    panel.pick_color = lambda current: None  # cancelled
    panel.editors[("color",)].button.click()
    assert _artist(document).color == "#00ff00"


def test_data_sources_show_their_file_read_only(panel: PropertyPanel, document) -> None:
    source = document.project.sources[0]
    document.select(source.id)
    assert ("path",) not in panel.editors and ("sha256",) not in panel.editors
    assert ("row_count",) not in panel.editors  # recorded on import, not typed
    texts = [label.text() for label in panel.widget().findChildren(QLabel)]
    assert source.path in texts
    assert "not recorded" in texts  # the example predates counting rows
    _type(panel, ("comment",), "%")
    assert document.project.sources[0].comment == "%"


def test_editors_follow_undo_without_rebuilding(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    editor = panel.editors[("name",)]
    _type(panel, ("name",), "Renamed")
    document.undo()
    assert panel.editors[("name",)] is editor
    assert editor.line.text() == "Scan"


def test_late_input_of_a_replaced_editor_is_ignored(
    panel: PropertyPanel, document
) -> None:
    document.select(_figure(document).id)
    old = panel.editors[("name",)]
    document.select(_artist(document).id)
    # The widget is gone; what it emitted while going down reaches commit.
    old.commit("Late")
    assert _figure(document).name == "Scan"
    assert not document.history.can_undo
    assert panel._error.isHidden()


def test_selection_change_rebuilds(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    document.select(_artist(document).id)
    assert ("capsize",) in panel.editors and ("dpi",) not in panel.editors
    document.select(None)
    assert panel.editors == {}


@pytest.mark.parametrize(
    ("cls", "fields"),
    [
        (AxisSpec, AxisSpec.model_fields),
        (Legend, Legend.model_fields),
        (GridLayout, GridLayout.model_fields),
        (LinePlot, LinePlot.model_fields),
        (CsvSource, CsvSource.model_fields),
        (Annotation, Annotation.model_fields),
        (FitCurve, FitCurve.model_fields),
    ],
)
def test_specs_cover_the_model(cls, fields) -> None:
    """Every field has an editor or is deliberately left out."""
    from figscribe.gui.properties import READ_ONLY, SKIPPED

    for name, field in fields.items():
        if name in SKIPPED or name in READ_ONLY:
            continue
        assert spec_for(name, field.annotation) is not None, f"{cls.__name__}.{name}"


def test_a_source_offers_its_text_encoding(panel: PropertyPanel, document) -> None:
    document.select(document.project.sources[0].id)
    editor = panel.editors[("encoding",)]
    combo = editor.widget
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts == ["UTF-8", "Windows (cp1252)", "Latin-1 (ISO 8859-1)"]
    assert "cp1252" in combo.toolTip()
    combo.activated.emit(1)
    assert document.project.sources[0].encoding == "cp1252"


def test_font_tick_and_grid_settings_have_names(panel: PropertyPanel, document) -> None:
    document.select(_figure(document).id)
    assert ("font_size",) in panel.editors
    assert panel.editors[("font_size",)].line.placeholderText() == "default"
    _type(panel, ("font_size",), "8")
    assert _figure(document).font_size == 8.0

    document.select(_axes(document).id)
    combo = panel.editors[("grid_axis",)].widget
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "both axes",
        "x only",
        "y only",
    ]
    combo.activated.emit(2)
    assert _axes(document).grid_axis == "y"


def test_the_grid_color_is_a_color_field(panel: PropertyPanel, document) -> None:
    document.select(_axes(document).id)
    editor = panel.editors[("grid_color",)]
    assert editor.line.placeholderText() == "automatic"
    _type(panel, ("grid_color",), "#696969")
    assert _axes(document).grid_color == "#696969"
