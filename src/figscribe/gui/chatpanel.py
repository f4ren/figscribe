"""The assistant bar: describe a change, and Claude makes it in the project.

Requests to the model run in a worker thread so the window stays responsive;
the tools run here, on the GUI thread, where they may change the document.
"""

from __future__ import annotations

import html
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from figscribe.assistant.chat import Chat, ChatError, ClaudeModel, Model
from figscribe.gui import theme
from figscribe.gui.document import Document
from figscribe.gui.widgets import label
from figscribe.tools import Toolbox


class _Turn(QThread):
    """One model turn, off the GUI thread."""

    text = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, chat: Chat):
        super().__init__()
        self.chat = chat

    def run(self) -> None:
        try:
            response = self.chat.respond(self.text.emit)
        except ChatError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never take the window down
            self.failed.emit(f"Unexpected error: {exc}")
        else:
            self.done.emit(response)


class ChatPanel(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("chatPanel")
        self.document = document
        self.make_model: Callable[[str | None], Model] = ClaudeModel
        """Creates the model from an optional API key; replaced in tests."""
        self.chat: Chat | None = None
        self._turn: _Turn | None = None
        self._reply = ""

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(True)
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Describe a change – e.g. “share the x axis and move the legend top left”"
        )
        self.input.returnPressed.connect(self.send)
        self.send_button = QPushButton("Apply")
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self.send)
        self.key = QLineEdit()
        self.key.setPlaceholderText("Anthropic API key (kept for this session only)")
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.hide()
        self.status = label("", "caption")

        header = QHBoxLayout()
        header.addWidget(label("Assistant", "tileTitle"))
        header.addWidget(
            label("changes are undoable · sees names, not your data", "caption"), 1
        )
        row = QHBoxLayout()
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.transcript, 1)
        layout.addWidget(self.key)
        layout.addLayout(row)
        layout.addWidget(self.status)

    def set_document(self, document: Document) -> None:
        """Talk about another project: the conversation starts over."""
        if document is self.document:
            return
        self.wait()
        self.document = document
        self.chat = None
        self.transcript.clear()

    @property
    def busy(self) -> bool:
        return self._turn is not None

    def send(self) -> None:
        """Ask the model for the change described in the input field."""
        text = self.input.text().strip()
        if not text or self.busy:
            return
        if self.chat is None:
            try:
                self.chat = Chat(self.make_model(self.key.text().strip() or None))
            except ChatError as exc:
                self._show_error(str(exc))
                return
        self.input.clear()
        self._add("you", text)
        self.chat.ask(text)
        self._start()

    def _start(self) -> None:
        self._reply = ""
        self._set_busy(True)
        turn = _Turn(self.chat)
        turn.text.connect(self._on_text)
        turn.done.connect(self._on_done)
        turn.failed.connect(self._on_failed)
        turn.finished.connect(turn.deleteLater)
        self._turn = turn
        turn.start()

    def _on_text(self, text: str) -> None:
        self._reply += text
        self.status.setText("Writing…")

    def _on_done(self, response) -> None:
        self._turn = None
        # The final message is the record; the streamed text only showed progress.
        reply = "".join(b.text for b in response.content if b.type == "text")
        if reply.strip():
            self._add("assistant", reply.strip())
        try:
            more = self.chat.handle(response, self._run_tool, self._on_tool)
        except ChatError as exc:
            self._on_failed(str(exc))
            return
        if more:
            self._start()
        else:
            self._set_busy(False)

    def _on_failed(self, message: str) -> None:
        self._turn = None
        self._set_busy(False)
        self._show_error(message)
        if "API key" in message:
            self.key.show()
            self.chat = None  # make the model again with the key

    def _run_tool(self, name: str, arguments: dict) -> dict:
        self.status.setText(f"Using {name}…")
        return Toolbox(self.document).call(name, arguments)

    def _on_tool(self, name: str, arguments: dict, error: str | None) -> None:
        if name in {"get_project", "get_schema", "list_columns", "render_preview"}:
            return  # reading, not worth a line
        if error is None:
            self._add("tool", f"{name}")
        else:
            self._add("tool", f"{name} refused: {error}")

    def _set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.input.setEnabled(not busy)
        self.status.setText("Thinking…" if busy else "")
        self.busy_changed.emit(busy)

    def _show_error(self, message: str) -> None:
        self._add("error", message)

    def _add(self, who: str, text: str) -> None:
        body = html.escape(text).replace("\n", "<br>")
        styles = {
            "you": f"color:{theme.INK}; font-weight:600",
            "assistant": f"color:{theme.INK}",
            "tool": f"color:{theme.MUTED}; font-family:'{theme.MONO}'; font-size:11px",
            "error": f"color:{theme.ERROR}",
        }
        prefix = {"tool": "→ ", "error": "⚠ "}.get(who, "")
        self.transcript.append(f'<p style="{styles[who]}">{prefix}{body}</p>')

    def wait(self, timeout_ms: int = 30000) -> None:
        """Block until the current turn is done; for tests and shutdown."""
        while self._turn is not None:
            self._turn.wait(timeout_ms)
            QApplication.processEvents()
