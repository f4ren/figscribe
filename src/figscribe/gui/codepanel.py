"""The Python code drawer: the generated script, always up to date.

Shows what *File > Export Python Script…* would write, refreshed shortly after
every change while the drawer is open; nothing is generated while it is
closed.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.codegen import generate, script_name
from figscribe.gui import theme
from figscribe.gui.document import Document
from figscribe.gui.errors import explain
from figscribe.gui.widgets import label

DELAY_MS = 250
"""Wait this long after a change before writing the script again."""


class CodePanel(QWidget):
    save_requested = Signal()

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("codePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.text = QPlainTextEdit()
        self.text.setObjectName("code")
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(theme.mono_font(12))
        self._highlighter = _PythonHighlighter(self.text.document())
        self.copy = QPushButton("Copy")
        self.copy.clicked.connect(self.copy_to_clipboard)
        self.save = QPushButton("Save as .py…")
        self.save.clicked.connect(self.save_requested)

        header = QHBoxLayout()
        header.setContentsMargins(16, 10, 12, 6)
        header.setSpacing(10)
        header.addWidget(label("Python code", "tileTitle"))
        header.addWidget(
            label("updates as you edit · runs without figscribe", "caption"), 1
        )
        header.addWidget(self.copy)
        header.addWidget(self.save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.text, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self.update_now)
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.schedule)
        document.figure_changed.connect(self.schedule)
        self.schedule()

    def schedule(self) -> None:
        """Write the script again soon, if the drawer is open."""
        if self.isVisible():
            self._timer.start()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().showEvent(event)
        self.update_now()

    def update_now(self) -> None:
        self._timer.stop()
        self.text.setPlainText(self.script())

    def script(self) -> str:
        """The script for the shown figure, or a comment saying why there is none."""
        document = self.document
        figure = document.figure
        if figure is None:
            return "# The project has no figure yet."
        folder = document.project_dir or document.base_dir
        try:
            return generate(
                document.project,
                figure,
                base_dir=document.base_dir,
                script_dir=folder,
                output=script_name(figure).replace(".py", ".pdf"),
                data=document.data,
            )
        except Exception as exc:  # shown in the drawer, never fatal
            return f"# The script cannot be written yet:\n# {explain(exc)}"

    def copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self.text.toPlainText())


class _PythonHighlighter(QSyntaxHighlighter):
    """Comments, strings, keywords and numbers, in the theme's quiet colors."""

    RULES = [
        (r"\b(import|from|as|def|return|for|in|if|raise|True|False|None)\b", "#7C3AED"),
        (r"\b\d+(\.\d+)?([eE][-+]?\d+)?\b", "#B45309"),
        (r"[rf]?\"[^\"\n]*\"|[rf]?'[^'\n]*'", "#15803D"),
        (r"#[^\n]*", "#8A8A90"),
    ]

    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        for pattern, color in self.RULES:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            self.rules.append((re.compile(pattern), style))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt naming
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)
