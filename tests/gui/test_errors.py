"""Messages for scientists: what went wrong, in their words."""

from __future__ import annotations

import pytest

from figscribe.commands import CommandError
from figscribe.gui.errors import explain
from figscribe.io import DataError
from figscribe.model import loads


def test_errors_written_for_people_pass_unchanged() -> None:
    assert explain(DataError("scan.csv has changed")) == "scan.csv has changed"
    assert explain(CommandError("'blu' is not a color")) == "'blu' is not a color"


def test_file_errors_name_the_file_and_the_reason() -> None:
    error = PermissionError(13, "Permission denied", "/data/out.pdf")
    assert explain(error) == "Permission denied: /data/out.pdf"


def test_a_damaged_project_file_says_where(example) -> None:
    text = example.read_text(encoding="utf-8").replace('"dpi": 300.0', '"dpi": -1.0')
    with pytest.raises(ValueError) as caught:
        loads(text)
    assert explain(caught.value).startswith("not a valid figscribe project: ")
    assert "dpi" in explain(caught.value)


def test_anything_else_is_called_a_bug_with_its_details() -> None:
    text = explain(TypeError("unsupported operand type(s)"))
    assert "bug in figscribe" in text
    assert "TypeError: unsupported operand type(s)" in text


def test_the_preview_explains_what_it_cannot_draw(qtbot, monkeypatch) -> None:
    from figscribe.gui import Document
    from figscribe.gui import preview as module

    def broken(*args):
        raise TypeError("unsupported operand type(s)")

    monkeypatch.setattr(module, "render", broken)
    view = module.Preview(Document())
    qtbot.addWidget(view)
    assert "bug in figscribe" in view.error
