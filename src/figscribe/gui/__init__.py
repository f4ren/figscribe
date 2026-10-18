"""The desktop GUI (PySide6).

The GUI reads and mutates the model only through a `Document`, which pushes
commands onto the undo history; the preview renders the model exactly as the
export does.
"""

from figscribe.gui.document import Document
from figscribe.gui.mainwindow import MainWindow

__all__ = ["Document", "MainWindow"]
