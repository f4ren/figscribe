"""Adding a CSV file: guessed options, a live preview, and a first plot."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from figscribe.gui import theme
from figscribe.gui.widgets import label
from figscribe.io.csvfile import ENCODING, csv_source, read_csv
from figscribe.io.errors import DataError
from figscribe.model import CsvSource
from figscribe.suggest import Suggestion, error_columns, suggest, units_line

DELIMITERS: list[tuple[str, str | None]] = [
    ("Comma", ","),
    ("Semicolon", ";"),
    ("Tab", "\t"),
    ("Spaces", None),
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


class LineSpinBox(QSpinBox):
    """A line number: stored from 0 like the model, shown from 1 like an editor."""

    def textFromValue(self, value: int) -> str:  # noqa: N802 - Qt naming
        return str(value + 1)

    def valueFromText(self, text: str) -> int:  # noqa: N802
        return int(text) - 1


class ImportDialog(QDialog):
    """Asks how to read `path`; `source()` then describes it for the model.

    Shows what was detected as a row of chips, the table as it will be read,
    and first plots to choose from. `mode` says what to do on accept: "plot"
    (add the data and the chosen plot), "data" (only the data) or "custom"
    (the data, then the plot dialog).

    `base_dir` is the project's directory; files below it are stored relative
    to it. Without one (an unsaved project), the path is stored absolute.
    """

    def __init__(self, path: str | Path, base_dir: Path | None, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.base_dir = base_dir
        self.setWindowTitle(f"Add {self.path.name}")
        self._text = self.path.read_bytes().decode(ENCODING, errors="replace")
        self._source: CsvSource | None = None
        self.units: list[str] | None = None
        """One unit per column, from a line of units below the header."""
        self.errors: dict[str, str] = {}
        """{error column: value column}, as the names suggest."""
        self.suggestions: list[Suggestion] = []
        self.mode = "plot"

        self.delimiter = QComboBox()
        for text, _ in DELIMITERS:
            self.delimiter.addItem(text)
        self.decimal = QComboBox()
        self.decimal.addItem("Point (1.5)", ".")
        self.decimal.addItem("Comma (1,5)", ",")
        self.has_header = QCheckBox("Column names in line")
        self.header_row = LineSpinBox()
        self.header_row.setRange(0, 10_000)
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 10_000)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("none")
        self.comment.setMaxLength(3)

        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.has_header)
        row.addWidget(self.header_row)
        row.addStretch(1)

        self.settings = QWidget()
        form = QFormLayout(self.settings)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Separator", self.delimiter)
        form.addRow("Decimal mark", self.decimal)
        form.addRow("Header", header)
        form.addRow("Lines skipped after it", self.skip_rows)
        form.addRow("Comments start with", self.comment)
        self.settings.hide()

        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        self.table = QTableWidget()
        self.table.setObjectName("dataTable")
        self.table.setFont(theme.mono_font(12))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.summary = label("", "caption")
        self.status = label("", "caption")
        self.error = label("", "error")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Add and plot")
        ok.setObjectName("primary")
        self.data_only = self.buttons.addButton(
            "Only add the data", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.data_only.clicked.connect(lambda: self._finish("data"))
        self.buttons.accepted.connect(lambda: self._finish(self.mode))
        self.buttons.rejected.connect(self.reject)

        self.choices = QButtonGroup(self)
        self.choices.setExclusive(True)
        self.choices.idToggled.connect(self._remember_choice)
        self._wanted: Suggestion | None = None
        """The last plot chosen; chosen again when the columns come back."""
        self._choice_box = QVBoxLayout()
        self._choice_box.setSpacing(8)
        self.custom = QPushButton("Choose columns myself…")
        self.custom.setObjectName("link")
        self.custom.clicked.connect(lambda: self._finish("custom"))

        self._layout(form)
        self.resize(980, 600)

        self.set_options(guess_options(self._text))
        for widget in (self.delimiter, self.decimal):
            widget.currentIndexChanged.connect(self.update_preview)
        for widget in (self.header_row, self.skip_rows):
            widget.valueChanged.connect(self.update_preview)
        self.has_header.toggled.connect(self.update_preview)
        self.comment.textChanged.connect(self.update_preview)
        self.update_preview()

    def _layout(self, form: QFormLayout) -> None:
        top = QVBoxLayout()
        top.setContentsMargins(24, 20, 24, 16)
        top.setSpacing(4)
        top.addWidget(label(f"Add {self.path.name}", "dialogTitle"))
        top.addWidget(self.summary)

        left = QVBoxLayout()
        left.setContentsMargins(24, 16, 24, 16)
        left.setSpacing(12)
        chips = QHBoxLayout()
        chips.addWidget(label("Detected", "caption"))
        chips.addLayout(self.chips)
        chips.addStretch(1)
        left.addLayout(chips)
        left.addWidget(self.settings)
        left.addWidget(self.table, 1)
        left.addWidget(self.status)
        left.addWidget(self.error)

        aside = QWidget()
        aside.setObjectName("aside")
        aside.setFixedWidth(320)
        right = QVBoxLayout(aside)
        right.setContentsMargins(20, 16, 20, 16)
        right.setSpacing(10)
        right.addWidget(label("Plot it as", "sectionHeading"))
        right.addLayout(self._choice_box)
        right.addWidget(self.custom, 0, Qt.AlignmentFlag.AlignLeft)
        right.addStretch(1)

        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.addLayout(left, 1)
        middle.addWidget(aside)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(24, 12, 24, 16)
        bottom.addWidget(
            label("You can change the plot and its columns any time.", "caption"), 1
        )
        bottom.addWidget(self.buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(top)
        layout.addWidget(_rule())
        layout.addLayout(middle, 1)
        layout.addWidget(_rule())
        layout.addLayout(bottom)

    # --- options ------------------------------------------------------------

    def set_options(self, options: dict) -> None:
        delimiters = [d for _, d in DELIMITERS]
        self.delimiter.setCurrentIndex(delimiters.index(options["delimiter"]))
        self.decimal.setCurrentIndex(self.decimal.findData(options["decimal"]))
        self.has_header.setChecked(options["header_row"] is not None)
        self.header_row.setValue(options["header_row"] or 0)
        self.skip_rows.setValue(options["skip_rows"])
        self.comment.setText(options["comment"] or "")
        self.update_preview()

    def options(self) -> dict:
        return {
            "delimiter": DELIMITERS[self.delimiter.currentIndex()][1],
            "decimal": self.decimal.currentData(),
            "header_row": self.header_row.value()
            if self.has_header.isChecked()
            else None,
            "skip_rows": self.skip_rows.value(),
            "comment": self.comment.text() or None,
        }

    def source(self) -> CsvSource | None:
        """The file as the model will record it; None while it does not parse."""
        return self._source

    # --- the plot -------------------------------------------------------------

    @property
    def suggestion(self) -> Suggestion | None:
        """The chosen first plot, if any."""
        index = self.choices.checkedId()
        return self.suggestions[index] if index >= 0 else None

    def choose(self, index: int) -> None:
        self.choices.button(index).setChecked(True)

    def planned_artist(self):
        """The chosen plot of the source, ready for the model; or None."""
        if self._source is None or self.suggestion is None:
            return None
        return self.suggestion.build(self._source.id)

    def unit_of(self, column: str | int) -> str | None:
        if self.units is None or self._source is None:
            return None
        names = self._source.columns or list(range(len(self.units)))
        if column not in names:
            return None
        return self.units[names.index(column)] or None

    def _remember_choice(self, index: int, checked: bool) -> None:
        if checked and 0 <= index < len(self.suggestions):
            self._wanted = self.suggestions[index]

    def _finish(self, mode: str) -> None:
        if self._source is None:
            return
        self.mode = mode
        self.accept()

    # --- preview ------------------------------------------------------------

    def update_preview(self) -> None:
        self.header_row.setEnabled(self.has_header.isChecked())
        self._source = None
        self.units = None
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
            self.summary.setText("Not readable with these settings. Change one below.")
            self.status.setText("")
            self.settings.show()
            table = None
        else:
            if source.columns and len(source.columns) != table.shape[1]:
                self.error.setText(
                    f"The header names {len(source.columns)} columns, "
                    f"the data has {table.shape[1]}."
                )
                self.settings.show()
            else:
                self.error.setText("")
                self._source = source
            self.units = self._read_units(source, table.shape[1])
            self._fill(source, table)
        self._show_chips()
        self._show_suggestions()
        enabled = self._source is not None
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(enabled)
        self.data_only.setEnabled(enabled)
        self.custom.setEnabled(enabled)
        if self._source is not None and not self.suggestions:
            ok.setText("Add")
            self.mode = "data"
        else:
            ok.setText("Add and plot")
            self.mode = "plot"

    def _read_units(self, source: CsvSource, count: int) -> list[str] | None:
        if source.header_row is None or source.skip_rows < 1:
            return None
        lines = self._text.splitlines()
        index = source.header_row + 1
        if index >= len(lines):
            return None
        return units_line(lines[index], source.delimiter, count)

    def _fill(self, source: CsvSource, table) -> None:
        rows, cols = min(table.shape[0], PREVIEW_ROWS), table.shape[1]
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)
        names = (
            source.columns
            if len(source.columns) == cols
            else [str(i) for i in range(cols)]
        )
        self.errors = error_columns([str(n) for n in names])
        headers = []
        for i, name in enumerate(names):
            unit = self.units[i] if self.units else ""
            headers.append(f"{name} [{unit}]" if unit else str(name))
        self.table.setHorizontalHeaderLabels(headers)
        for i, name in enumerate(names):
            if str(name) in self.errors:
                item = self.table.horizontalHeaderItem(i)
                item.setToolTip(f"Looks like the error of {self.errors[str(name)]}")
        for r in range(rows):
            for c in range(cols):
                self.table.setItem(r, c, QTableWidgetItem(f"{table[r, c]:g}"))
        count = table.shape[0]
        self.summary.setText(
            f"{count} rows · {cols} columns · read as shown below. "
            "Wrong? Change any setting, the table follows."
        )
        notes = [f"All {count} rows read as numbers."]
        notes += [
            f"{err} looks like the error of {value}."
            for err, value in self.errors.items()
        ]
        notes.append("The file's fingerprint is stored, so a changed file is noticed.")
        self.status.setText(" ".join(notes))

    def _show_chips(self) -> None:
        while self.chips.count():
            _discard(self.chips.takeAt(0).widget())
        options = self.options()
        texts = [
            DELIMITER_NAMES[DELIMITERS[self.delimiter.currentIndex()][0]],
            "Decimal point" if options["decimal"] == "." else "Decimal comma",
        ]
        if options["header_row"] is None:
            texts.append("No column names")
        else:
            texts.append(f"Names in line {options['header_row'] + 1}")
            if self.units is not None:
                texts.append(f"Units in line {options['header_row'] + 2}")
            elif options["skip_rows"]:
                texts.append(f"{options['skip_rows']} lines skipped")
        if options["comment"]:
            texts.append(f"{options['comment']} comments")
        for text in texts:
            chip = QToolButton()
            chip.setObjectName("pill")
            chip.setText(f"{text} ▾")
            chip.setToolTip("Change how the file is read")
            chip.clicked.connect(lambda: self.settings.setVisible(True))
            self.chips.addWidget(chip)

    def _show_suggestions(self) -> None:
        columns = (self._source.columns or None) if self._source else None
        if self._source is not None and columns is None:
            columns = list(range(self.table.columnCount()))
        found = suggest(columns) if columns else []
        if found == self.suggestions:
            return
        wanted = self._wanted
        self.suggestions = found
        for button in self.choices.buttons():
            self.choices.removeButton(button)
            _discard(button)
        for i, suggestion in enumerate(found):
            tile = _choice_tile(suggestion)
            self.choices.addButton(tile, i)
            self._choice_box.addWidget(tile)
        if found:
            self.choose(found.index(wanted) if wanted in found else 0)


DELIMITER_NAMES = {
    "Comma": "Comma-separated",
    "Semicolon": "Semicolon-separated",
    "Tab": "Tab-separated",
    "Spaces": "Space-separated",
}


def _choice_tile(suggestion: Suggestion) -> QPushButton:
    tile = QPushButton()
    tile.setObjectName("choiceTile")
    tile.setCheckable(True)
    row = QHBoxLayout(tile)
    row.setContentsMargins(12, 10, 12, 10)
    row.setSpacing(12)
    mark = QLabel()
    mark.setPixmap(theme.icon(suggestion.kind, theme.ACCENT, 28).pixmap(28, 28))
    mark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    row.addWidget(mark)
    text = QVBoxLayout()
    text.setSpacing(2)
    for part, name in ((suggestion.title, "tileTitle"), (suggestion.detail, "caption")):
        part_label = label(part, name)
        part_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        text.addWidget(part_label)
    row.addLayout(text, 1)
    tile.setMinimumHeight(row.sizeHint().height() + 4)
    return tile


def _discard(widget: QWidget) -> None:
    """Take a widget off screen at once; Qt deletes it later."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def _rule() -> QFrame:
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    return line
