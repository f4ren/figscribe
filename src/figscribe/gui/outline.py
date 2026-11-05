"""The contents panel: each figure's panels and plots, then the data.

Reads like the figure, not like the model: panels are headed "Panel A ·
top", plots carry the color they are drawn in and an eye to hide them, fits
show their χ²ᵣ, and each data file lists its columns. Clicking a row selects
the object everywhere; nothing here edits the model except the eye, which
pushes one SetField like any other editor.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from figscribe.commands import CommandError, SetField, drawing_order, find, to_front
from figscribe.gui import theme
from figscribe.gui.axisform import AXIS_TITLES, axis_summary, plain, unit_shown
from figscribe.gui.document import Document, axis_id, split_axis
from figscribe.gui.figures import fill_figure_menu
from figscribe.gui.markings import ENTRIES
from figscribe.gui.names import artist_name, panel_name, size_text
from figscribe.gui.reveal import reveal_label
from figscribe.gui.widgets import FlowLayout, chip
from figscribe.model import Axes, Figure

ID_ROLE = Qt.ItemDataRole.UserRole
PANEL_SIDES = [
    ("right", "Add panel to the right"),
    ("left", "Add panel to the left"),
    ("above", "Add panel above"),
    ("below", "Add panel below"),
    ("inset", "Add inset"),
]
VISIBLE_ROLE = Qt.ItemDataRole.UserRole + 1
COLOR_ROLE = Qt.ItemDataRole.UserRole + 2
"""On plot rows: the colour the plot is drawn in, as shown by its icon."""
"""On plot rows: whether the plot is drawn; the eye column toggles it."""

LINE_CYCLE = {"line", "errorbar", "fit", "residual"}
PATCH_CYCLE = {"scatter", "histogram"}
"""Matplotlib draws these from two separate color cycles."""


class Outline(QTreeWidget):
    add_requested = Signal(str)
    """Add a plot to the panel (or figure) with this id."""
    import_requested = Signal()
    panel_requested = Signal(str, str)
    """Add a panel beside or inside the panel with this id: (id, side)."""
    delete_requested = Signal(str)
    note_requested = Signal(str)
    same_range_requested = Signal(str, str)
    """Give every panel the range this panel shows on an axis: (panel id,
    "x" or "y")."""
    reveal_requested = Signal(str)
    """Show the data file with this id in the file manager."""
    marking_requested = Signal(str, str, str)
    figure_requested = Signal(str, str)
    """Something done with the figure with this id: (id, what), as
    `figures.fill_figure_menu` asks for it."""
    """A reference line or shaded range for a panel: (panel id, kind,
    orientation), as `markings.ENTRIES` has them."""
    """Add a note to the panel with this id."""

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(2)
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setIndentation(0)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # Ctrl or Shift and click choose several plots, changed together.
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._syncing = False
        self._chip_rows: list[tuple[QTreeWidgetItem, QWidget]] = []
        self.itemSelectionChanged.connect(self._on_tree_selection)
        self.itemClicked.connect(self._on_click)
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.rebuild)
        document.selection_changed.connect(self._show_selection)
        self.rebuild()

    def rebuild(self) -> None:
        self._syncing = True
        try:
            self.clear()
            self._chip_rows = []
            for figure in self.document.project.figures:
                self._figure_rows(figure)
            self._data_rows()
        finally:
            self._syncing = False
        self._fit_chip_rows()
        self._show_selection(self.document.selected)

    def item_for(self, oid: str) -> QTreeWidgetItem | None:
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, ID_ROLE) == oid:
                return item
        return None

    def set_visible(self, oid: str, visible: bool) -> None:
        try:
            self.document.push(SetField(oid, ("visible",), visible))
        except CommandError:
            pass  # the plot is gone; the next rebuild drops its row

    def set_order(self, oid: str, front: bool) -> None:
        """Draw the plot `oid` above (`front`) or below every other plot of its
        panel, as one undo step."""
        command = to_front(self.document.project, oid, front)
        if command is not None:
            self.document.push(command)

    # --- rows -----------------------------------------------------------------

    def _figure_rows(self, figure: Figure) -> None:
        item = self._row(figure.name, figure.id, icon="figure")
        item.setText(1, size_text(figure))
        item.setForeground(1, QBrush(QColor(theme.MUTED)))
        _bold(item)
        for axes in figure.axes:
            self._axes_rows(figure, axes)
        if not figure.axes:
            self._link("+ Add a plot", lambda: self.add_requested.emit(figure.id))

    def _axes_rows(self, figure: Figure, axes: Axes) -> None:
        heading = self._row(panel_name(figure, axes).upper(), axes.id)
        _kicker(heading)
        self._axis_rows(axes)
        # Every Matplotlib axes has its own colour cycle; a right y axis too.
        cycles = {}
        for artist in axes.artists:
            side = artist.axis if axes.y_right is not None else "left"
            family = ("line" if artist.kind in LINE_CYCLE else "patch", side)
            cycles.setdefault(family, 0)
            color = getattr(artist, "color", None)
            shown = theme.plot_color(color, cycles[family])
            if color is None and artist.kind in LINE_CYCLE | PATCH_CYCLE:
                cycles[family] += 1
            name = theme.ARTIST_ICONS.get(artist.kind, "line")
            item = self._row(artist_name(artist), artist.id)
            item.setIcon(0, theme.icon(name, shown if artist.visible else "#B5B5BA"))
            item.setData(0, VISIBLE_ROLE, artist.visible)
            item.setData(0, COLOR_ROLE, shown)
            eye = "eye" if artist.visible else "eye-off"
            item.setIcon(1, theme.icon(eye, "#8A8A90"))
            item.setToolTip(1, "Hide" if artist.visible else "Show")
            if not artist.visible:
                item.setForeground(0, QBrush(QColor("#8A8A90")))
            result = getattr(artist, "result", None)
            if result is not None and result.reduced_chi_square is not None:
                item.setText(1, f"χ²ᵣ {result.reduced_chi_square:.2f}")
                item.setForeground(1, QBrush(QColor(theme.MUTED)))
                item.setFont(1, theme.mono_font(11))
        letter = panel_name(figure, axes).split(" ")[1]
        self._link(f"+ Add to panel {letter}", lambda: self.add_requested.emit(axes.id))

    def _axis_rows(self, axes: Axes) -> None:
        """The panel's axes, before its plots: where to go for their settings."""
        for field in ("x", "y", "y_right"):
            spec = getattr(axes, field)
            if spec is None:
                continue
            what = AXIS_TITLES[field].capitalize()
            label = plain(spec.label) if spec.label else ""
            unit = unit_shown(spec)
            if unit:
                label = f"{label} ({plain(unit)})" if label else f"({plain(unit)})"
            item = self._row(
                f"{what} · {label}" if label else what, axis_id(axes.id, field)
            )
            item.setIcon(
                0, theme.icon("axis_y" if field != "x" else "axis_x", theme.MUTED)
            )
            item.setToolTip(0, axis_summary(spec))

    def _data_rows(self) -> None:
        sources = self.document.project.sources
        _kicker(self._row("DATA", None, selectable=False))
        for source in sources:
            item = self._row(Path(source.path).name, source.id, icon="file")
            item.setToolTip(0, source.path)
            count = len(source.columns)
            item.setText(1, f"{count} column{'s' if count != 1 else ''}")
            item.setForeground(1, QBrush(QColor(theme.MUTED)))
            if source.columns:
                self._chips([str(c) for c in source.columns])
        if not sources:
            self._link("+ Add data…", self.import_requested.emit)

    def _row(
        self,
        text: str,
        oid: str | None,
        icon: str | None = None,
        selectable: bool = True,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(self, [text])
        item.setData(0, ID_ROLE, oid)
        if icon is not None:
            item.setIcon(0, theme.icon(icon, theme.MUTED))
        if not selectable:
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        return item

    def _link(self, text: str, slot) -> None:
        item = self._row("", None, selectable=False)
        item.setFirstColumnSpanned(True)
        button = QToolButton()
        button.setObjectName("link")
        button.setText(text)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(24, 0, 0, 0)
        row.addWidget(button)
        row.addStretch(1)
        self.setItemWidget(item, 0, holder)

    def _chips(self, names: list[str]) -> None:
        item = self._row("", None, selectable=False)
        item.setFirstColumnSpanned(True)
        holder = QWidget()
        holder.setObjectName("chips")
        flow = FlowLayout(holder)
        flow.setContentsMargins(26, 0, 4, 6)
        for name in names:
            flow.addWidget(chip(name))
        self.setItemWidget(item, 0, holder)
        self._chip_rows.append((item, holder))

    def _fit_chip_rows(self) -> None:
        width = max(self.viewport().width(), 120)
        for item, holder in self._chip_rows:
            height = holder.layout().heightForWidth(width)
            item.setSizeHint(0, QSize(width, height))

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._fit_chip_rows()

    # --- selection ------------------------------------------------------------

    def context_menu(self, oid: str) -> QMenu | None:
        """What can be done with the object `oid`, as a menu; None if nothing."""
        axis = split_axis(oid)
        if axis is not None:
            return self._axis_menu(*axis)
        try:
            obj = find(self.document.project, oid)
        except CommandError:
            return None
        menu = QMenu(self)
        if isinstance(obj, Axes):
            if obj.inset is None:
                for side, text in PANEL_SIDES:
                    action = menu.addAction(text)
                    action.triggered.connect(
                        lambda _=False, s=side: self.panel_requested.emit(oid, s)
                    )
                menu.addSeparator()
            menu.addAction("Add note…", lambda: self.note_requested.emit(oid))
            lines = menu.addMenu("Add line or range")
            for text, kind, orientation in ENTRIES:
                lines.addAction(
                    text,
                    lambda k=kind, o=orientation: self.marking_requested.emit(
                        oid, k, o
                    ),
                )
            if obj.inset is None:
                menu.addSeparator()
                others = self._other_panels(obj)
                for field in ("x", "y"):
                    action = menu.addAction(
                        f"Same {field} range in all panels",
                        lambda f=field: self.same_range_requested.emit(oid, f),
                    )
                    action.setEnabled(others)
            menu.addSeparator()
            menu.addAction("Delete panel", lambda: self.delete_requested.emit(oid))
        elif isinstance(obj, Figure):
            if not obj.axes:
                menu.addAction(
                    "Add a panel", lambda: self.panel_requested.emit(oid, "right")
                )
                menu.addSeparator()
            fill_figure_menu(
                menu, self.document, oid, self.figure_requested.emit, across=False
            )
        elif any(source.id == oid for source in self.document.project.sources):
            menu.addAction(reveal_label(), lambda: self.reveal_requested.emit(oid))
            menu.addSeparator()
            menu.addAction("Remove data file", lambda: self.delete_requested.emit(oid))
        elif hasattr(obj, "visible") and hasattr(obj, "kind"):
            menu.addAction(
                "Hide" if obj.visible else "Show",
                lambda: self.set_visible(oid, not obj.visible),
            )
            drawn = drawing_order(self.document.project, oid)
            front = menu.addAction("Bring to front", lambda: self.set_order(oid, True))
            front.setEnabled(drawn[-1] is not obj)
            back = menu.addAction("Send to back", lambda: self.set_order(oid, False))
            back.setEnabled(drawn[0] is not obj)
            menu.addSeparator()
            menu.addAction("Delete", lambda: self.delete_requested.emit(oid))
        else:
            return None
        return menu

    def _axis_menu(self, axes_id: str, field: str) -> QMenu | None:
        """What can be done with one axis: give every panel its range. Nothing
        for the right y axis or an inset, which `same_range` leaves alone."""
        try:
            axes = find(self.document.project, axes_id)
        except CommandError:
            return None
        if field == "y_right" or axes.inset is not None:
            return None
        menu = QMenu(self)
        action = menu.addAction(
            f"Same {field} range in all panels",
            lambda: self.same_range_requested.emit(axes_id, field),
        )
        action.setEnabled(self._other_panels(axes))
        return menu

    def _other_panels(self, axes: Axes) -> bool:
        """Whether the figure of `axes` has another panel in its grid."""
        for figure in self.document.project.figures:
            if axes in figure.axes:
                return any(a is not axes and a.inset is None for a in figure.axes)
        return False

    def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt naming
        item = self.itemAt(event.pos())
        oid = item.data(0, ID_ROLE) if item is not None else None
        menu = self.context_menu(oid) if oid else None
        if menu is not None:
            self.document.select(oid)
            menu.exec(event.globalPos())

    def _on_click(self, item: QTreeWidgetItem, column: int) -> None:
        visible = item.data(0, VISIBLE_ROLE)
        if column == 1 and visible is not None:
            self.set_visible(item.data(0, ID_ROLE), not visible)

    def _on_tree_selection(self) -> None:
        """One row selects its object; several rows select their plots
        together, or, with anything else among them, the row clicked last."""
        if self._syncing:
            return
        ids = [item.data(0, ID_ROLE) for item in self.selectedItems()]
        ids = [oid for oid in ids if oid is not None]
        plots = {a.id for _, a in self._plots()}
        current = self.currentItem()
        if len(ids) > 1 and all(oid in plots for oid in ids):
            last = current.data(0, ID_ROLE) if current is not None else None
            if last in ids:  # the one clicked last leads, as when it is alone
                ids = [*(oid for oid in ids if oid != last), last]
            self.document.select_many(ids)
        elif len(ids) > 1 and current is not None:
            self.document.select(current.data(0, ID_ROLE))
            self._show_selection(self.document.selected)
        else:
            self.document.select(ids[0] if ids else None)

    def _plots(self):
        for figure in self.document.project.figures:
            for axes in figure.axes:
                for artist in axes.artists:
                    yield axes, artist

    def _show_selection(self, oid: str | None) -> None:
        self._syncing = True
        try:
            many = self.document.selection
            if len(many) > 1:
                self.clearSelection()
                for each in many:
                    item = self.item_for(each)
                    if item is not None:
                        item.setSelected(True)
                return
            item = self.item_for(oid) if oid is not None else None
            axis = split_axis(oid)
            if item is None and axis is not None:
                item = self.item_for(axis[0])  # no row of its own: its panel's
            self.setCurrentItem(item) if item else self.clearSelection()
        finally:
            self._syncing = False


def _bold(item: QTreeWidgetItem) -> None:
    font = QFont(item.font(0))
    font.setWeight(QFont.Weight.DemiBold)
    item.setFont(0, font)


def _kicker(item: QTreeWidgetItem) -> None:
    font = QFont(item.font(0))
    font.setPixelSize(11)
    font.setWeight(QFont.Weight.Medium)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.6)
    item.setFont(0, font)
    item.setForeground(0, QBrush(QColor(theme.MUTED)))
