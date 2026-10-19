"""The `figscribe` command: start the GUI, optionally with a project file."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from figscribe.gui import theme
from figscribe.gui.mainwindow import MainWindow


def create_window(argv: Sequence[str], remember: bool = False) -> MainWindow:
    """The main window for the command line `argv` (program name excluded).

    With `remember`, the window keeps its switches in the user's settings.
    """
    settings = QSettings("figscribe", "figscribe") if remember else None
    window = MainWindow(settings=settings)
    if argv:
        window.open_path(argv[0])
    return window


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("figscribe")
    theme.apply(app)
    window = create_window(sys.argv[1:], remember=True)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
