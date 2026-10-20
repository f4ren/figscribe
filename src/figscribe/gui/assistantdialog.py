"""Choosing the assistant's model: Claude, ChatGPT, or a local one."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.assistant.chat import (
    CLAUDE_MODELS,
    MODEL,
    SERVERS,
    ChatError,
    Provider,
    list_models,
)
from figscribe.gui.widgets import label

KINDS = [("Claude (Anthropic)", "anthropic"), ("OpenAI-compatible", "openai")]
OTHER = "Other server"


class AssistantDialog(QDialog):
    """Edits a Provider; the API key is kept for this session only."""

    def __init__(
        self, provider: Provider, api_key: str | None = None, parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assistant model")
        self.list_models: Callable[[Provider, str | None], list[str]] = list_models
        """Asks the server for its models; replaced in tests."""

        self.kind = QComboBox()
        for text, kind in KINDS:
            self.kind.addItem(text, kind)
        self.server = QComboBox()
        self.server.addItems([*SERVERS, OTHER])
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://host:port/v1")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.load = QPushButton("Load models")
        self.load.clicked.connect(self.load_models)
        self.vision = QCheckBox("The model reads images (lets it check the preview)")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.status = label("", "caption")
        self.status.setWordWrap(True)

        model_row = QWidget()
        row = QHBoxLayout(model_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.model, 1)
        row.addWidget(self.load)

        form = QFormLayout()
        form.addRow("Provider", self.kind)
        form.addRow("Server", self.server)
        form.addRow("Address", self.url)
        form.addRow("Model", model_row)
        form.addRow("", self.vision)
        form.addRow("API key", self.key)
        self._server_rows = [self.server, self.url, self.vision]
        self._form = form

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status)
        layout.addWidget(
            label(
                "Only file and column names and the project's structure are sent "
                "to the model, never data values. A local server keeps even "
                "those on this computer.",
                "caption",
            )
        )
        layout.addWidget(self.buttons)

        self._show(provider, api_key)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.server.currentIndexChanged.connect(self._server_changed)
        self.url.textChanged.connect(self._update)

    def provider(self) -> Provider:
        """The provider as edited."""
        kind = self.kind.currentData()
        model = self.model.currentText().strip()
        if kind == "anthropic":
            return Provider("anthropic", model or MODEL)
        return Provider(
            "openai", model, self.url.text().strip() or None, self.vision.isChecked()
        )

    def api_key(self) -> str | None:
        return self.key.text().strip() or None

    def load_models(self) -> None:
        """Fill the model list from the server."""
        try:
            models = self.list_models(self.provider(), self.api_key())
        except ChatError as exc:
            self.status.setText(str(exc))
            return
        current = self.model.currentText()
        self._set_models(models, current)
        self.status.setText(
            f"{len(models)} model(s) on the server." if models else "No models found."
        )

    def _show(self, provider: Provider, api_key: str | None) -> None:
        self.kind.setCurrentIndex(self.kind.findData(provider.kind))
        url = provider.base_url or ""
        names = {u: n for n, u in SERVERS.items()}
        self.server.setCurrentText(names.get(url, OTHER))
        self.url.setText(url)
        self.vision.setChecked(provider.vision)
        self.key.setText(api_key or "")
        self._set_models(
            CLAUDE_MODELS if provider.kind == "anthropic" else [], provider.model
        )
        self._update()

    def _set_models(self, models: list[str], current: str) -> None:
        self.model.clear()
        self.model.addItems(models)
        self.model.setCurrentText(current)

    def _kind_changed(self) -> None:
        if self.kind.currentData() == "anthropic":
            self._set_models(CLAUDE_MODELS, MODEL)
        else:
            self._set_models([], "")
            if not self.url.text():
                self._server_changed()
        self.status.setText("")
        self._update()

    def _server_changed(self) -> None:
        url = SERVERS.get(self.server.currentText())
        if url is not None:
            self.url.setText(url)
            # ChatGPT sees; most local models do not.
            self.vision.setChecked(url == SERVERS["ChatGPT (OpenAI)"])
        self._set_models([], "")

    def _update(self) -> None:
        openai = self.kind.currentData() == "openai"
        for widget in self._server_rows:
            self._form.setRowVisible(widget, openai)
        local = openai and "api.openai.com" not in self.url.text()
        self.key.setPlaceholderText(
            "not needed for a local server"
            if local
            else "kept for this session only; else from the environment"
        )
