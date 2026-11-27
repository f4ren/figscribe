"""Which column of another data file takes the place of which.

Asked by *Use another file…* where the new file has the columns the plots use
under other names, or not at all.
"""

from __future__ import annotations

from collections.abc import Sequence

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


class ColumnDialog(QDialog):
    """Asks for each of `missing` which of `columns` takes its place."""

    def __init__(
        self,
        name: str,
        missing: Sequence[MissingColumn],
        columns: Sequence[str],
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
        self.combos: dict[str, QComboBox] = {}
        for column in missing:
            combo = QComboBox()
            for new in columns:
                combo.addItem(new, new)
            combo.addItem(NOT_THERE, None)
            chosen = combo.findData(column.default) if column.default else -1
            combo.setCurrentIndex(chosen if chosen >= 0 else combo.count() - 1)
            # A long column name does not widen the dialog; the list shows it whole.
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(24)
            combo.setToolTip(f"Used by {', '.join(column.plots)}")
            old = label(column.name, "value")
            old.setToolTip(combo.toolTip())
            form.addRow(old, combo)
            self.combos[column.name] = combo
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

    def chosen(self) -> dict[str, str | None]:
        """The new column by old name; None for one the new file lacks."""
        return {name: combo.currentData() for name, combo in self.combos.items()}
