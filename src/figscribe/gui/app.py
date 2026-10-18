"""The `figscribe` command: start the GUI, optionally with a project file."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtWidgets import QApplication

from figscribe.gui.mainwindow import MainWindow


def create_window(argv: Sequence[str]) -> MainWindow:
    """The main window for the command line `argv` (program name excluded)."""
    window = MainWindow()
    if argv:
        window.open_path(argv[0])
    return window


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("figscribe")
    window = create_window(sys.argv[1:])
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
