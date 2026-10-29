"""Showing a data file in the file manager: the command per platform."""

from __future__ import annotations

from pathlib import Path

import pytest

from figscribe.gui import reveal


def test_finder_selects_the_file() -> None:
    path = Path("/data/my runs/scan 1.csv")
    assert reveal.reveal_command(path, "darwin") == ["open", "-R", str(path)]


def test_explorer_selects_the_file() -> None:
    path = Path("C:/data/my runs/scan 1.csv")
    assert reveal.reveal_command(path, "win32") == ["explorer", f"/select,{path}"]


def test_other_systems_open_the_folder() -> None:
    # There is no common way to select a file; the folder is opened instead.
    assert reveal.reveal_command(Path("/data/scan.csv"), "linux") is None


@pytest.mark.parametrize(
    ("platform", "text"),
    [
        ("darwin", "Show in Finder"),
        ("win32", "Show in Explorer"),
        ("linux", "Show in file manager"),
    ],
)
def test_the_entry_names_the_file_manager(platform: str, text: str) -> None:
    assert reveal.reveal_label(platform) == text
