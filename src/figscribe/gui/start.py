"""The start page: drop data, pick a layout, or go back to a recent project.

Shown when figscribe starts without a file. It only asks; the main window
does the work, through the signals below.
"""

from __future__ import annotations

from datetime import datetime
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import figscribe
from figscribe.gui import theme
from figscribe.gui.widgets import label
from figscribe.model import Figure
from figscribe.templates import TEMPLATES, Template

DOCS_URL = "https://github.com/f4ren/figscribe#readme"


def bundled_example() -> Path:
    """The example project's folder: inside the package when installed, in
    the repository when run from a checkout."""
    packaged = resources.files("figscribe") / "examples" / "gaussian-scan"
    if packaged.is_dir():
        return Path(str(packaged))
    return Path(figscribe.__file__).parents[2] / "examples" / "gaussian-scan"


class StartPage(QScrollArea):
    files_dropped = Signal(list)
    """Paths of files dropped on the page or chosen in the file dialog."""
    choose_file = Signal()
    open_project = Signal()
    template_chosen = Signal(str)
    example_requested = Signal()
    assistant_requested = Signal()
    recent_chosen = Signal(Path)
    docs_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("startPage")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.recent_rows: list[QPushButton] = []
        self.template_tiles: dict[str, QPushButton] = {}

        body = QWidget()
        body.setObjectName("startBody")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._header())
        centred = QHBoxLayout()
        centred.addStretch(1)
        self._content = QVBoxLayout()
        self._content.setSpacing(28)
        self._content.setContentsMargins(24, 40, 24, 48)
        holder = QWidget()
        holder.setLayout(self._content)
        holder.setMaximumWidth(1040)
        holder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        centred.addWidget(holder, 100)
        centred.addStretch(1)
        outer.addLayout(centred)
        outer.addStretch(1)

        self._content.addLayout(self._intro())
        self._content.addLayout(self._start_row())
        self._content.addLayout(self._templates())
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(8)
        self._content.addLayout(self._recent_box)
        self.set_recent([])
        self.setWidget(body)

    # --- parts ----------------------------------------------------------------

    def _header(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("startHeader")
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 10, 20, 10)
        mark = QLabel()
        mark.setPixmap(theme.icon("fit", theme.ACCENT, 20).pixmap(20, 20))
        row.addWidget(mark)
        row.addWidget(label("figscribe", "projectName"))
        row.addStretch(1)
        self.back = _button("", "link")
        self.back.clicked.connect(self.back_requested)
        self.back.hide()
        row.addWidget(self.back)
        docs = _button("Documentation", "link")
        docs.clicked.connect(self.docs_requested)
        row.addWidget(docs)
        opener = _button("Open project…")
        opener.clicked.connect(self.open_project)
        row.addWidget(opener)
        return bar

    def _intro(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(6)
        column.addWidget(label("Make a figure", "startTitle"))
        text = label(
            "Start from your data. figscribe draws it at the size you will "
            "publish it, you refine it, and you keep a clean Python script "
            "that redraws it exactly.",
            "lead",
        )
        text.setMaximumWidth(640)
        column.addWidget(text)
        return column

    def _start_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setMinimumHeight(220)
        zone = QVBoxLayout(self.drop_zone)
        zone.setSpacing(8)
        zone.addStretch(1)
        icon = QLabel()
        icon.setPixmap(theme.icon("file", theme.ACCENT, 32).pixmap(32, 32))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone.addWidget(icon)
        title = label("Drop a data file here", "zoneTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone.addWidget(title)
        hint = label("CSV, TSV or text columns · or a figscribe project", "caption")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone.addWidget(hint)
        chooser = _button("Choose a file…", "primary")
        chooser.clicked.connect(self.choose_file)
        line = QHBoxLayout()
        line.addStretch(1)
        line.addWidget(chooser)
        line.addStretch(1)
        zone.addSpacing(6)
        zone.addLayout(line)
        zone.addStretch(1)
        row.addWidget(self.drop_zone, 3)

        side = QVBoxLayout()
        side.setSpacing(10)
        side.addWidget(label("New to figscribe?", "sectionTitle"))
        self.example_tile = _tile(
            "Open the example", "A Gaussian scan with error bars", "errorbar"
        )
        self.example_tile.clicked.connect(self.example_requested)
        side.addWidget(self.example_tile)
        assistant = _tile(
            "Describe it instead",
            "Connect an assistant and say what you want",
            "code",
        )
        assistant.clicked.connect(self.assistant_requested)
        side.addWidget(assistant)
        side.addStretch(1)
        row.addLayout(side, 2)
        return row

    def _templates(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(label("Start from a layout", "sectionHeading"))
        caption = label("Exact sizes in millimetres, ready for the journal", "caption")
        heading.addWidget(caption, 1)
        column.addLayout(heading)
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, template in enumerate(TEMPLATES):
            tile = _template_tile(template)
            tile.clicked.connect(
                lambda _=False, key=template.key: self.template_chosen.emit(key)
            )
            self.template_tiles[template.key] = tile
            grid.addWidget(tile, 0, i)
        column.addLayout(grid)
        return column

    def set_back(self, name: str | None) -> None:
        """Offer a way back to the open project `name`, or none."""
        self.back.setText(f"Back to {name}" if name else "")
        self.back.setVisible(bool(name))

    def set_recent(self, paths: list[Path]) -> None:
        """Show these project files, most recent first; missing ones are left out."""
        while self._recent_box.count():
            item = self._recent_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.recent_rows = []
        existing = [p for p in paths if p.is_file()]
        if not existing:
            return
        self._recent_box.addWidget(label("Recent", "sectionHeading"))
        for path in existing:
            row = _recent_row(path)
            row.clicked.connect(lambda _=False, p=path: self.recent_chosen.emit(p))
            self._recent_box.addWidget(row)
            self.recent_rows.append(row)

    # --- dropping -------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._highlight(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        self._highlight(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._highlight(False)
        urls = event.mimeData().urls()
        paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)

    def _highlight(self, on: bool) -> None:
        self.drop_zone.setProperty("active", on)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)


# --- tiles -----------------------------------------------------------------------


def _button(text: str, name: str | None = None) -> QPushButton:
    button = QPushButton(text)
    if name is not None:
        button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _passive(widget: QWidget) -> QWidget:
    """Let clicks through to the tile underneath."""
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def _tile(title: str, detail: str, icon: str) -> QPushButton:
    tile = _button("", "tile")
    row = QHBoxLayout(tile)
    row.setContentsMargins(14, 12, 14, 12)
    row.setSpacing(12)
    mark = QLabel()
    mark.setPixmap(theme.icon(icon, theme.ACCENT, 20).pixmap(20, 20))
    row.addWidget(_passive(mark))
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(_passive(label(title, "tileTitle")))
    text.addWidget(_passive(label(detail, "caption")))
    row.addLayout(text, 1)
    tile.setMinimumHeight(row.sizeHint().height())
    return tile


def _template_tile(template: Template) -> QPushButton:
    tile = _button("", "tile")
    tile.setToolTip(f"{template.name} · {template.detail}")
    column = QVBoxLayout(tile)
    column.setContentsMargins(12, 12, 12, 12)
    column.setSpacing(4)
    column.addWidget(_passive(LayoutThumbnail(template.build())))
    column.addSpacing(6)
    column.addWidget(_passive(label(template.name, "tileTitle")))
    column.addWidget(_passive(label(template.detail, "caption")))
    tile.setMinimumHeight(column.sizeHint().height())
    tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return tile


def _recent_row(path: Path) -> QPushButton:
    row = _button("", "recentRow")
    line = QHBoxLayout(row)
    line.setContentsMargins(14, 10, 14, 10)
    line.setSpacing(12)
    mark = QLabel()
    mark.setPixmap(theme.icon("figure", theme.MUTED).pixmap(16, 16))
    line.addWidget(_passive(mark))
    text = QVBoxLayout()
    text.setSpacing(1)
    text.addWidget(_passive(label(path.stem, "tileTitle")))
    text.addWidget(_passive(label(_short(path.parent), "caption")))
    line.addLayout(text, 1)
    edited = datetime.fromtimestamp(path.stat().st_mtime)
    line.addWidget(_passive(label(f"edited {edited:%d %b %Y}", "caption")))
    row.setMinimumHeight(line.sizeHint().height())
    row.setToolTip(str(path))
    return row


def _short(folder: Path) -> str:
    """The folder, with the home directory written as ~."""
    try:
        return str(Path("~") / folder.relative_to(Path.home()))
    except ValueError:
        return str(folder)


class LayoutThumbnail(QWidget):
    """A small drawing of a figure's shape and panels, true to its proportions."""

    HEIGHT = 64

    def __init__(self, figure: Figure, parent: QWidget | None = None):
        super().__init__(parent)
        self.figure = figure
        self.setFixedHeight(self.HEIGHT)
        self.setMinimumWidth(90)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        figure = self.figure
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(
            (self.width() - 2) / figure.width_mm, (self.height() - 2) / figure.height_mm
        )
        paper = QRectF(0, 0, figure.width_mm * scale, figure.height_mm * scale)
        paper.moveCenter(QRectF(self.rect()).center())
        painter.setPen(QPen(QColor(theme.CONTROL_BORDER), 1))
        painter.setBrush(QColor(theme.SURFACE))
        painter.drawRoundedRect(paper, 3, 3)
        for box in panel_boxes(figure, paper.adjusted(6, 5, -4, -6)):
            painter.setPen(QPen(QColor(theme.MUTED), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(box.bottomLeft(), box.topLeft())
            painter.drawLine(box.bottomLeft(), box.bottomRight())
            painter.setPen(QPen(QColor(theme.ACCENT), 1.4))
            w, h = box.width(), box.height()
            points = [(0.08, 0.8), (0.3, 0.55), (0.5, 0.2), (0.7, 0.5), (0.92, 0.75)]
            for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
                painter.drawLine(
                    box.left() + x0 * w,
                    box.top() + y0 * h,
                    box.left() + x1 * w,
                    box.top() + y1 * h,
                )


def panel_boxes(figure: Figure, area: QRectF) -> list[QRectF]:
    """Where each panel sits in `area`, following the grid and its ratios."""
    layout = figure.layout
    widths = layout.width_ratios or [1.0] * layout.cols
    heights = layout.height_ratios or [1.0] * layout.rows
    gap = 6.0
    usable_w = area.width() - gap * (layout.cols - 1)
    usable_h = area.height() - gap * (layout.rows - 1)

    def span(ratios, start, count, usable):
        total = sum(ratios)
        before = sum(ratios[:start]) / total * usable + gap * start
        size = sum(ratios[start : start + count]) / total * usable + gap * (count - 1)
        return before, size

    boxes = []
    for axes in figure.axes:
        if axes.col >= layout.cols or axes.row >= layout.rows:
            continue
        x, w = span(widths, axes.col, axes.colspan, usable_w)
        y, h = span(heights, axes.row, axes.rowspan, usable_h)
        boxes.append(QRectF(area.left() + x, area.top() + y, w, h))
    return boxes
