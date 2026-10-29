"""Show a file in the system's file manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def reveal_command(path: Path, platform: str = sys.platform) -> list[str] | None:
    """The command that opens the file manager with `path` selected; None on
    a system where there is none and the folder is opened instead."""
    if platform == "darwin":
        return ["open", "-R", str(path)]
    if platform == "win32":
        return ["explorer", f"/select,{path}"]
    return None


def reveal_label(platform: str = sys.platform) -> str:
    """The text of the menu entry, naming the file manager of the system."""
    return {
        "darwin": "Show in Finder",
        "win32": "Show in Explorer",
    }.get(platform, "Show in file manager")


def show_in_file_manager(path: Path) -> None:
    """Open the file manager at `path`: with the file selected where the
    system can, else on its folder. Tests replace this function."""
    command = reveal_command(path)
    if command is not None:
        subprocess.Popen(command)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
