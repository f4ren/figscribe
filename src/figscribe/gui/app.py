"""The `figscribe` command: start the GUI, optionally with a project file."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QSettings
from PySide6.QtGui import QFileOpenEvent
from PySide6.QtWidgets import QApplication

import figscribe
from figscribe.gui import theme
from figscribe.gui.mainwindow import MainWindow


def set_application_identity(app: QApplication) -> None:
    app.setApplicationName("figscribe")
    app.setApplicationVersion(figscribe.__version__)


def create_window(argv: Sequence[str], remember: bool = False) -> MainWindow:
    """The main window for the command line `argv` (program name excluded).

    With `remember`, the window keeps its switches in the user's settings.
    """
    settings = QSettings("figscribe", "figscribe") if remember else None
    window = MainWindow(settings=settings)
    if argv:
        window.open_path(argv[0])
    else:
        window.show_start()
        window.offer_recovery(None)  # the work of an untitled session that crashed
    return window


class FileOpenFilter(QObject):
    """Opens what the system asks the running program to open.

    On macOS, a double click on a project in Finder (or *Open With*) does not
    put its name on the command line; the system sends the program a file open
    event, also when it is started by it, and when it is running already. It is
    the window's child, so it goes with the window."""

    def __init__(self, window: MainWindow) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.FileOpen and isinstance(event, QFileOpenEvent):
            if event.file():
                self.window.open_dropped([Path(event.file())])
            return True
        return False


def install_file_open(app: QApplication, window: MainWindow) -> FileOpenFilter:
    """Let `window` open the files the system asks `app` to open."""
    opener = FileOpenFilter(window)
    app.installEventFilter(opener)
    return opener


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    set_application_identity(app)
    theme.apply(app)
    window = create_window(sys.argv[1:], remember=True)
    install_file_open(app, window)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
