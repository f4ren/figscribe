"""Which column of another data file takes the place of which.

Asked by *Use another file…* where the new file has the columns the plots use
under other names, or not at all.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from figscribe.datafile import MissingColumn
from figscribe.gui.widgets import label

NOT_THERE = "(not in the new file)"
NO_NAME = "(column without a name)"
SHOWN = 40
"""Characters of a column name written out; a longer one is cut in the middle,
and shown whole when pointed at."""


def _short(name: str) -> str:
    if len(name) <= SHOWN:
        return name
    return f"{name[: SHOWN // 2]}…{name[-(SHOWN // 2 - 1) :]}"


class _Choice(QComboBox):
    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt naming
        event.ignore()  # the list scrolls; no choice changes under the pointer


class ColumnDialog(QDialog):
    """Asks for each of `missing` which column takes its place."""

    def __init__(
        self,
        name: str,
        missing: Sequence[MissingColumn],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Columns of {name}")
        heading = label(f"{name} has other column names", "dialogTitle")
        hint = label("Choose which column takes the place of which.", "caption")
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        # A long name takes the line, and its choice the one below.
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        self.combos: dict[tuple[str, str], QComboBox] = {}
        twice = Counter(column.name for column in missing)
        for column in missing:
            combo = _Choice()
            for new in column.choices:
                combo.addItem(new or NO_NAME, new)
            combo.addItem(NOT_THERE, None)
            chosen = -1 if column.default is None else combo.findData(column.default)
            combo.setCurrentIndex(chosen if chosen >= 0 else combo.count() - 1)
            # A long column name does not widen the dialog; the list shows it whole.
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(24)
            used = f"Used by {', '.join(column.plots)}"
            combo.setToolTip(f"<qt>{escape(used)}</qt>")
            text = _short(column.name)
            if twice[column.name] > 1:  # two sources of the file: tell them apart
                text = f"{text} · {_short(', '.join(column.plots))}"
            old = label(text, "value")
            old.setTextFormat(Qt.TextFormat.PlainText)
            old.setToolTip(f"<qt>{escape(column.name)}<br>{escape(used)}</qt>")
            form.addRow(old, combo)
            self.combos[column.source, column.name] = combo
        rows = QWidget()
        rows.setObjectName("columnRows")
        rows.setLayout(form)
        scroll = QScrollArea()  # a file may have many columns
        scroll.setObjectName("columnScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(rows)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Use these columns")
        ok.setObjectName("primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(scroll, 1)
        layout.addWidget(buttons)
        self.resize(520, min(190 + 44 * len(missing), 560))

    def chosen(self) -> dict[tuple[str, str], str | None]:
        """The new column by source id and old name; None for one the new file
        lacks."""
        return {name: combo.currentData() for name, combo in self.combos.items()}
