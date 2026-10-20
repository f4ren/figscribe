"""Adding a plot: its kind, its columns and the axes it goes into."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from figscribe.commands import InsertItem, Macro
from figscribe.commands.core import noun
from figscribe.model import (
    ArtistBase,
    Axes,
    ColumnRef,
    ErrorbarPlot,
    Figure,
    Histogram,
    LinePlot,
    ScatterPlot,
)

KINDS: dict[str, type[ArtistBase]] = {
    "Line": LinePlot,
    "Scatter": ScatterPlot,
    "Error bars": ErrorbarPlot,
    "Histogram": Histogram,
}


class PlotDialog(QDialog):
    """Asks for a plot of two (or, with error bars, up to four) columns."""

    def __init__(self, columns: list[tuple[str, ColumnRef]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add plot")
        self.columns = columns

        self.kind = QComboBox()
        self.kind.addItems(list(KINDS))
        self.x = self._column_box(optional=False)
        self.y = self._column_box(optional=False)
        self.yerr = self._column_box(optional=True)
        self.xerr = self._column_box(optional=True)
        self.label = QLineEdit()
        self.label.setPlaceholderText("(not in the legend)")

        form = QFormLayout()
        form.addRow("Kind", self.kind)
        form.addRow("x", self.x)
        form.addRow("y", self.y)
        form.addRow("y error", self.yerr)
        form.addRow("x error", self.xerr)
        form.addRow("Legend label", self.label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        # A sensible start: the first column against the second, labelled.
        if len(columns) > 1:
            self.y.setCurrentIndex(1)
        self.kind.currentIndexChanged.connect(self._update)
        self.y.currentIndexChanged.connect(self._update_label)
        self._update()
        self._update_label()

    def artist(self) -> ArtistBase:
        """The plot as chosen."""
        cls = KINDS[self.kind.currentText()]
        if cls is Histogram:
            return Histogram(
                values=self.y.currentData(), label=self.label.text() or None
            )
        fields = {
            "x": self.x.currentData(),
            "y": self.y.currentData(),
            "label": self.label.text() or None,
        }
        if cls is ErrorbarPlot:
            fields["yerr"] = self.yerr.currentData()
            fields["xerr"] = self.xerr.currentData()
        return cls(**fields)

    def _column_box(self, optional: bool) -> QComboBox:
        box = QComboBox()
        if optional:
            box.addItem("(none)", None)
        for text, ref in self.columns:
            box.addItem(text, ref)
        return box

    def _update(self) -> None:
        kind = KINDS[self.kind.currentText()]
        self.yerr.setEnabled(kind is ErrorbarPlot)
        self.xerr.setEnabled(kind is ErrorbarPlot)
        self.x.setEnabled(kind is not Histogram)  # a histogram has only values

    def _update_label(self) -> None:
        ref = self.y.currentData()
        if ref is not None and isinstance(ref.column, str):
            self.label.setText(ref.column)


def add_plot(figure: Figure, axes_id: str | None, artist: ArtistBase) -> Macro:
    """Put `artist` into the axes `axes_id`, or into a new one if there is none.

    A figure without axes gets one in the top left cell, in the same undo
    step, so that adding the first plot to a new figure is a single action.
    """
    steps = []
    if axes_id is None:
        axes = Axes(row=0, col=0)
        steps.append(InsertItem(figure.id, "axes", axes))
        axes_id = axes.id
    steps.append(InsertItem(axes_id, "artists", artist))
    return Macro(f"Add {noun(artist)}", steps)
