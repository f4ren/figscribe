"""Adding a sheet of an Excel or LibreOffice Calc file (decision 0079)."""

from __future__ import annotations

import re

import numpy as np
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QSpinBox

from figscribe.gui.importdialog import (
    DataDialog,
    LineSpinBox,
    _decimal_box,
    _header_row,
)
from figscribe.io.errors import DataError
from figscribe.io.sheetfile import (
    cell_text,
    column_letters,
    read_cells,
    read_sheet,
    sheet_names,
    sheet_source,
)
from figscribe.model import SheetSource
from figscribe.suggest import units_line

_COMMA_NUMBER = re.compile(r"\s*[-+]?\d+,\d+([eE][-+]?\d+)?\s*")


def guess_sheet(cells: list[list[object]]) -> dict:
    """Read options for a sheet's cells as the import dialog first proposes
    them: perhaps a title, the column names, perhaps a row of units, then
    numbers."""
    decimal = "."
    if any(
        isinstance(cell, str) and _COMMA_NUMBER.fullmatch(cell)
        for row in cells[:100]
        for cell in row
    ):
        decimal = ","

    def number(cell: object) -> bool:
        if isinstance(cell, str):
            try:
                float(cell.strip().replace(decimal, "."))
            except ValueError:
                return False
            return True
        return isinstance(cell, int | float) and not isinstance(cell, bool)

    def filled(row: list[object]) -> int:
        return sum(1 for cell in row if str(cell).strip())

    counts = [sum(number(cell) for cell in row) for row in cells[:100]]
    # Two numbers in a row, or one where no row has more.
    wanted = min(2, max(counts, default=0))
    first = next((i for i, n in enumerate(counts) if wanted and n >= wanted), None)
    options = {"header_row": 0, "skip_rows": 0, "decimal": decimal}
    if first is None:
        return options
    above = first - 1
    while above >= 0 and not filled(cells[above]):
        above -= 1
    if above < 0:
        return {**options, "header_row": None, "skip_rows": first}
    top = above
    while top > 0 and filled(cells[top - 1]):
        top -= 1
    # In the block above the data, titles have one cell; the names come first
    # of the rows that have more.
    most = max(filled(row) for row in cells[top : above + 1])
    header = next(i for i in range(top, above + 1) if filled(cells[i]) >= min(2, most))
    return {**options, "header_row": header, "skip_rows": first - header - 1}


class SheetDialog(DataDialog):
    """Asks which sheet of `path` to read, and how (see `DataDialog`)."""

    def _settings_form(self, form: QFormLayout) -> None:
        self._names = sheet_names(self._raw, self.path.name)
        self._cells: dict[str, list[list[object]]] = {}
        self.sheet = QComboBox()
        self.sheet.addItems(self._names)
        self.has_header = QCheckBox("Column names in row")
        self.header_row = LineSpinBox()
        self.header_row.setRange(0, 1_000_000)
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 1_000_000)
        self.decimal = _decimal_box()
        self.decimal.setToolTip("The decimal mark of numbers stored as text")
        form.addRow("Sheet", self.sheet)
        form.addRow("Header", _header_row(self.has_header, self.header_row))
        form.addRow("Rows skipped after it", self.skip_rows)
        form.addRow("Decimal mark in text", self.decimal)

    def _start(self) -> None:
        self.sheet.setCurrentText(self._sheet_with_numbers())
        self.set_options(guess_sheet(self._sheet_cells()))
        self.sheet.currentIndexChanged.connect(self._choose_sheet)
        self.decimal.currentIndexChanged.connect(self.update_preview)
        for widget in (self.header_row, self.skip_rows):
            widget.valueChanged.connect(self.update_preview)
        self.has_header.toggled.connect(self.update_preview)

    def _sheet_with_numbers(self) -> str:
        """The first sheet that holds a number, else the first."""
        for name in self._names:
            try:
                cells = self._sheet_cells(name)
            except DataError:
                continue
            if any(
                isinstance(cell, int | float) and not isinstance(cell, bool)
                for row in cells
                for cell in row
            ):
                return name
        return self._names[0]

    def _sheet_cells(self, name: str | None = None) -> list[list[object]]:
        name = name or self.sheet.currentText()
        if name not in self._cells:
            self._cells[name] = read_cells(self._raw, self.path.name, name)
        return self._cells[name]

    def _choose_sheet(self) -> None:
        try:
            self.set_options(guess_sheet(self._sheet_cells()))
        except DataError:
            self.update_preview()  # which says why

    def set_options(self, options: dict) -> None:
        widgets = (self.has_header, self.header_row, self.skip_rows, self.decimal)
        for widget in widgets:
            widget.blockSignals(True)
        self.has_header.setChecked(options["header_row"] is not None)
        self.header_row.setValue(options["header_row"] or 0)
        self.skip_rows.setValue(options["skip_rows"])
        self.decimal.setCurrentIndex(self.decimal.findData(options["decimal"]))
        for widget in widgets:
            widget.blockSignals(False)
        self.update_preview()

    def options(self) -> dict:
        return {
            "sheet": self.sheet.currentText(),
            "header_row": self.header_row.value()
            if self.has_header.isChecked()
            else None,
            "skip_rows": self.skip_rows.value(),
            "decimal": self.decimal.currentData(),
        }

    def _read(self) -> tuple[SheetSource, np.ndarray]:
        source = sheet_source(
            self.path, self.base_dir or self.path.parent, **self.options()
        )
        source = self._relative_to_project(source)
        self._table = read_sheet(source, self._raw, self.path.name)
        first = source.first_column
        table = np.empty((len(self._table.rows), self._table.width), dtype=object)
        for i, (_, cells) in enumerate(self._table.rows):
            for at in range(self._table.width):
                table[i, at] = cells[first + at] if first + at < len(cells) else ""
        return source, table

    def _read_units(self, source: SheetSource, count: int) -> list[str] | None:
        if source.header_row is None or source.skip_rows < 1:
            return None
        row = self._sheet_cells()[source.header_row + 1]
        first = source.first_column
        cells = [
            cell_text(row[at]) if at < len(row) else ""
            for at in range(first, first + count)
        ]
        return units_line("\t".join(cells), "\t", count)

    def _cell(self, value) -> str:
        return cell_text(value)

    def _numbers_note(self, source: SheetSource, table: np.ndarray) -> list[str]:
        """The columns that are not numbers, and those with gaps."""
        names = source.columns
        self._numeric: list[str] = []
        notes = []
        for i, name in enumerate(names):
            try:
                values = self._table.column(i)
            except DataError as exc:
                at = f"{column_letters(source.first_column + i)}"
                found = re.search(rf"cell ({at}\d+)(: ('[^']*'))?", str(exc))
                shown = f"cell {found[1]}" if found else "a cell"
                if found and found[3]:
                    shown = f"{shown}: {found[3]}"
                notes.append(f"{name} is not numbers ({shown}).")
                continue
            gaps = int(np.isnan(values).sum())
            if gaps == len(values):
                continue  # an empty column is nothing to plot
            self._numeric.append(name)
            if gaps:
                what = "1 empty cell, which is a gap" if gaps == 1 else None
                what = what or f"{gaps} empty cells, which are gaps"
                notes.append(f"{name} has {what}.")
        if not notes:
            notes.append(f"All {table.shape[0]} rows read as numbers.")
        return notes

    def _plottable(self) -> list[str] | None:
        return self._numeric if self._source is not None else None

    def _chip_texts(self) -> list[str]:
        options = self.options()
        texts = [f"Sheet {options['sheet']}"]
        if options["header_row"] is None:
            texts.append("No column names")
        else:
            texts.append(f"Names in row {options['header_row'] + 1}")
            if self.units is not None:
                texts.append(f"Units in row {options['header_row'] + 2}")
            elif options["skip_rows"]:
                texts.append(f"{options['skip_rows']} rows skipped")
        if options["decimal"] == ",":
            texts.append("Decimal comma")
        return texts
