"""The settings of each kind of element, by what they are for (roadmap U11,
decisions 0060 to 0062): which sections, in which order, with which fields.
Proposed while the user was away; this test says what was built."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import Document
from figscribe.gui.properties import PropertyPanel

from .everything import build


@pytest.fixture(scope="module")
def project_file(tmp_path_factory) -> Path:
    return build(tmp_path_factory.mktemp("everything"))


def _first(project, kind: type):
    for figure in project.figures:
        for axes in figure.axes:
            for artist in axes.artists:
                if isinstance(artist, kind):
                    return artist
    raise AssertionError(kind)


def _sections(qtbot, project_file: Path, kind: type):
    document = Document.open(project_file)
    panel = PropertyPanel(document)
    qtbot.addWidget(panel)
    panel.resize(400, 900)
    panel.show()
    document.select(_first(document.project, kind).id)
    fields = {
        title: [
            ".".join(path)
            for path, editor in panel.editors.items()
            if section.isAncestorOf(editor.widget)
        ]
        for title, section in panel.sections.items()
    }
    return panel, fields


def _case(name: str):
    import figscribe.model as model

    return getattr(model, name)


EXPECTED = {
    "Annotation": {
        "Text": ["text", "fontsize", "color", "background"],
        "Place": ["position", "coords", "arrow_to", "axis"],
        "More": ["label", "alpha", "visible", "zorder"],
    },
    "ReferenceLine": {
        "Label and data": ["label", "orientation", "at", "axis"],
        "Look": ["color", "linestyle", "linewidth"],
        "More": ["alpha", "visible", "zorder"],
    },
    "ShadedSpan": {
        "Label and data": ["label", "orientation", "start", "end", "axis"],
        "Look": ["color", "alpha"],
        "More": ["visible", "zorder"],
    },
}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_the_sections_of_each_kind(qtbot, project_file: Path, name: str) -> None:
    panel, fields = _sections(qtbot, project_file, _case(name))
    assert fields == EXPECTED[name]
    assert list(panel.sections) == list(EXPECTED[name])  # in this order
    assert not panel.sections["More"].expanded
    for title in panel.sections:
        if title != "More":
            assert panel.sections[title].expanded, title


def test_a_legend_entry_is_called_that_everywhere(qtbot, project_file) -> None:
    for name in ("ReferenceLine", "ShadedSpan"):
        panel, _ = _sections(qtbot, project_file, _case(name))
        caption, _tip = panel._captions[("label",)]
        assert caption.text() == "Legend entry", name
