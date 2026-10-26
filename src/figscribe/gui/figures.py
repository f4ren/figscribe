"""The figures of a project: a tab for each above the preview, and the menu
of what can be done with one, shared by the tabs and the outline.

The tabs show only while a project has more than one figure; with one, the
outline and the preview say all there is.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QTabBar,
    QToolButton,
    QWidget,
)

from figscribe.commands import MoveItem
from figscribe.gui import theme
from figscribe.gui.document import Document

ACTIONS = ["rename", "duplicate", "earlier", "later"]
"""What the figure menu offers before "Delete figure", in its order."""


def fill_figure_menu(
    menu: QMenu,
    document: Document,
    oid: str,
    ask: Callable[[str, str], None],
    across: bool = True,
) -> None:
    """Add what can be done with the figure `oid` to `menu`; `ask(oid, what)`
    asks for it, with `what` from ACTIONS or "delete". `across`: the figures
    are shown side by side, as tabs, rather than one below the other."""
    figures = [f.id for f in document.project.figures]
    index = figures.index(oid)
    texts = {
        "rename": "Rename…",
        "duplicate": "Duplicate",
        "earlier": "Move left" if across else "Move up",
        "later": "Move right" if across else "Move down",
    }
    for what in ACTIONS:
        action = menu.addAction(texts[what], lambda w=what: ask(oid, w))
        if what == "earlier":
            action.setEnabled(index > 0)
        elif what == "later":
            action.setEnabled(index < len(figures) - 1)
    menu.addSeparator()
    delete = menu.addAction("Delete figure", lambda: ask(oid, "delete"))
    delete.setEnabled(len(figures) > 1)


def move_figure(document: Document, oid: str, step: int) -> None:
    """Move the figure `oid` by `step` places, as one undo step."""
    figures = [f.id for f in document.project.figures]
    index = figures.index(oid) + step
    if 0 <= index < len(figures):
        document.push(MoveItem(None, "figures", oid, index, "Move figure"))


class FigureTabs(QWidget):
    """A tab for each figure; choosing one shows it and selects it."""

    requested = Signal(str, str)
    """(figure id, what): one of the figure menu's actions."""
    add_requested = Signal()

    def __init__(self, document: Document, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("figureTabs")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.bar = QTabBar()
        self.bar.setDocumentMode(True)
        self.bar.setExpanding(False)
        self.bar.setMovable(True)
        self.bar.setUsesScrollButtons(True)
        self.bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bar.currentChanged.connect(self._chosen)
        self.bar.tabMoved.connect(self._moved)
        self.bar.installEventFilter(self)
        self.bar.tabBarDoubleClicked.connect(self._double_clicked)
        self.bar.customContextMenuRequested.connect(self._context_menu)
        self.add_button = QToolButton()
        self.add_button.setObjectName("quiet")
        self.add_button.setIcon(theme.icon("plus"))
        self.add_button.setToolTip("Add a figure")
        self.add_button.clicked.connect(self.add_requested.emit)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 0)
        row.setSpacing(4)
        row.addWidget(self.bar)
        row.addWidget(self.add_button)
        row.addStretch(1)
        self._syncing = False
        self._dragged = False
        """Whether a tab was dragged to another place; its figure moves there
        when the button is released, as one undo step."""
        self.set_document(document)

    def set_document(self, document: Document) -> None:
        self.document = document
        document.changed.connect(self.rebuild)
        document.figure_changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        """A tab per figure, in their order, the shown one current."""
        figures = self.document.project.figures
        self.setVisible(len(figures) > 1)
        shown = self.document.figure
        self._syncing = True
        try:
            while self.bar.count() > len(figures):
                self.bar.removeTab(self.bar.count() - 1)
            while self.bar.count() < len(figures):
                self.bar.addTab("")
            for i, figure in enumerate(figures):
                self.bar.setTabText(i, figure.name)
                self.bar.setTabData(i, figure.id)
                self.bar.setTabToolTip(i, "Double-click to rename; drag to reorder")
                if figure is shown:
                    self.bar.setCurrentIndex(i)
        finally:
            self._syncing = False

    def figure_menu(self, index: int) -> QMenu:
        menu = QMenu(self)
        oid = self.bar.tabData(index)
        fill_figure_menu(menu, self.document, oid, self.requested.emit)
        return menu

    def _chosen(self, index: int) -> None:
        if self._syncing or index < 0:
            return
        self.document.select(self.bar.tabData(index))

    def _moved(self, src: int, dst: int) -> None:
        if not self._syncing:
            self._dragged = True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            watched is self.bar
            and event.type() == QEvent.Type.MouseButtonRelease
            and self._dragged
        ):
            self._dragged = False
            self._drop()
        return super().eventFilter(watched, event)

    def _drop(self) -> None:
        """Move the dragged tab's figure to where the tab is now."""
        index = self.bar.currentIndex()
        oid = self.bar.tabData(index)
        figures = [f.id for f in self.document.project.figures]
        if oid in figures and figures.index(oid) != index:
            self.document.push(MoveItem(None, "figures", oid, index, "Move figure"))
        self.rebuild()

    def _double_clicked(self, index: int) -> None:
        if index >= 0:
            self.requested.emit(self.bar.tabData(index), "rename")

    def _context_menu(self, pos) -> None:
        index = self.bar.tabAt(pos)
        if index >= 0:
            self.figure_menu(index).exec(self.bar.mapToGlobal(pos))
