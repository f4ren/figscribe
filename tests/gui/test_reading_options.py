"""How a data file is read, changed in the property panel: the file is read
that way at once, or the change is refused."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel


@pytest.fixture
def document(qtbot, example: Path) -> Document:
    return Document.open(example)


@pytest.fixture
def panel(qtbot, document: Document) -> PropertyPanel:
    widget = PropertyPanel(document)
    qtbot.addWidget(widget)
    return widget


def _type(panel: PropertyPanel, field: str, text: str) -> None:
    line = panel.editors[(field,)].line
    line.setText(text)
    line.editingFinished.emit()


def test_a_separator_that_cannot_read_the_file_is_refused(panel, document) -> None:
    source = document.project.sources[0]
    document.select(source.id)
    _type(panel, "delimiter", "2")
    assert "scan.csv" in panel.error
    assert document.project.sources[0] == source
    assert not document.history.can_undo
    assert panel.editors[("delimiter",)].line.text() == source.delimiter
