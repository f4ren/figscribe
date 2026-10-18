"""Importing a CSV file: guessed options, adjustable, with a live preview."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from figscribe.io.csvfile import ENCODING, csv_source, read_csv
from figscribe.io.errors import DataError
from figscribe.model import CsvSource

DELIMITERS: list[tuple[str, str | None]] = [
    (",", ","),
    (";", ";"),
    ("Tab", "\t"),
    ("Whitespace", None),
]

PREVIEW_ROWS = 20


def guess_options(text: str) -> dict:
    """Read options for `text` as the import dialog first proposes them.

    Handles the common shapes: a comment block, a header line, an optional
    line of units, then numbers; comma, semicolon, tab or whitespace between
    fields; a decimal comma next to a semicolon, as spreadsheets in many
    European locales write it.
    """
    lines = text.splitlines()
    content = [
        (i, line)
        for i, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    sample_lines = [line for _, line in content[:20]]
    sample = "\n".join(sample_lines)
    # The candidate found in the most lines; on a tie tab, then semicolon,
    # since a comma may be a decimal separator. csv.Sniffer is no help here:
    # it gives up as soon as the header and the data differ in width.
    counts = {d: sum(d in line for line in sample_lines) for d in ("\t", ";", ",")}
    best = max(counts, key=counts.get)
    delimiter: str | None = best if counts[best] else None
    decimal = "," if delimiter != "," and re.search(r"\d,\d", sample) else "."

    def numeric(line: str) -> bool:
        fields = line.split() if delimiter is None else line.split(delimiter)
        try:
            [float(f.strip().replace(decimal, ".")) for f in fields if f.strip()]
        except ValueError:
            return False
        return True

    first_data = next((k for k, (_, line) in enumerate(content) if numeric(line)), None)
    options = {"delimiter": delimiter, "decimal": decimal, "comment": "#"}
    if first_data is None or first_data == 0:
        return {**options, "header_row": None, "skip_rows": 0}
    header = content[0][0]
    return {
        **options,
        "header_row": header,
        "skip_rows": content[first_data][0] - header - 1,
    }


class ImportDialog(QDialog):
    """Asks how to read `path`; `source()` then describes it for the model.

    `base_dir` is the project's directory; files below it are stored relative
    to it. Without one (an unsaved project), the path is stored absolute.
    """

    def __init__(self, path: str | Path, base_dir: Path | None, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.base_dir = base_dir
        self.setWindowTitle(f"Import {self.path.name}")
        self._text = self.path.read_bytes().decode(ENCODING, errors="replace")
        self._source: CsvSource | None = None

        self.delimiter = QComboBox()
        for text, _ in DELIMITERS:
            self.delimiter.addItem(text)
        self.decimal = QComboBox()
        self.decimal.addItems([".", ","])
        self.has_header = QCheckBox("Column names in line")
        self.header_row = QSpinBox()
        self.header_row.setRange(0, 10_000)
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 10_000)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("(none)")
        self.comment.setMaxLength(3)

        header = QWidget()
        row = QFormLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.addRow(self.has_header, self.header_row)

        form = QFormLayout()
        form.addRow("Delimiter", self.delimiter)
        form.addRow("Decimal separator", self.decimal)
        form.addRow("Header", header)
        form.addRow("Skip lines after it", self.skip_rows)
        form.addRow("Comment marker", self.comment)

        self.table = QTableWidget()
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b00020")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.error)
        layout.addWidget(self.buttons)
        self.resize(640, 520)

        self.set_options(guess_options(self._text))
        for widget in (self.delimiter, self.decimal):
            widget.currentIndexChanged.connect(self.update_preview)
        for widget in (self.header_row, self.skip_rows):
            widget.valueChanged.connect(self.update_preview)
        self.has_header.toggled.connect(self.update_preview)
        self.comment.textChanged.connect(self.update_preview)
        self.update_preview()

    def set_options(self, options: dict) -> None:
        delimiters = [d for _, d in DELIMITERS]
        self.delimiter.setCurrentIndex(delimiters.index(options["delimiter"]))
        self.decimal.setCurrentText(options["decimal"])
        self.has_header.setChecked(options["header_row"] is not None)
        self.header_row.setValue(options["header_row"] or 0)
        self.skip_rows.setValue(options["skip_rows"])
        self.comment.setText(options["comment"] or "")
        self.update_preview()

    def options(self) -> dict:
        return {
            "delimiter": DELIMITERS[self.delimiter.currentIndex()][1],
            "decimal": self.decimal.currentText(),
            "header_row": self.header_row.value()
            if self.has_header.isChecked()
            else None,
            "skip_rows": self.skip_rows.value(),
            "comment": self.comment.text() or None,
        }

    def source(self) -> CsvSource | None:
        """The file as the model will record it; None while it does not parse."""
        return self._source

    def update_preview(self) -> None:
        self.header_row.setEnabled(self.has_header.isChecked())
        self._source = None
        try:
            source = csv_source(
                self.path, self.base_dir or self.path.parent, **self.options()
            )
            if self.base_dir is None:
                source = source.model_copy(update={"path": str(self.path.resolve())})
            table = read_csv(source, self._text, self.path.name)
        except (DataError, ValueError) as exc:
            self.error.setText(str(exc))
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
        else:
            if source.columns and len(source.columns) != table.shape[1]:
                self.error.setText(
                    f"The header names {len(source.columns)} columns, "
                    f"the data has {table.shape[1]}."
                )
            else:
                self.error.setText("")
                self._source = source
            self._fill(source, table)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self._source is not None
        )

    def _fill(self, source: CsvSource, table) -> None:
        rows, cols = min(table.shape[0], PREVIEW_ROWS), table.shape[1]
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)
        names = (
            source.columns
            if len(source.columns) == cols
            else [str(i) for i in range(cols)]
        )
        self.table.setHorizontalHeaderLabels(names)
        for r in range(rows):
            for c in range(cols):
                self.table.setItem(r, c, QTableWidgetItem(f"{table[r, c]:g}"))
