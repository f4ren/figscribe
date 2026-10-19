"""The look: colors, type, a style sheet and line icons, in one place.

A calm, light working surface with one accent: the figure is what should
stand out, not the tools around it. IBM Plex (SIL Open Font License, see
fonts/OFL.txt) is bundled so the application looks the same everywhere.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

GROUND = "#F6F6F3"
"""Behind the figure and between the panels."""
SURFACE = "#FFFFFF"
SUBTLE = "#F1F1EC"
BORDER = "#E3E3DE"
CONTROL_BORDER = "#D7D7D1"
INK = "#1C1C1E"
MUTED = "#5F5F66"
"""Secondary text; 6:1 on white."""
ACCENT = "#2459D6"
ACCENT_HOVER = "#1A43A8"
ACCENT_SOFT = "#E8EEFB"
WARN = "#B45309"
WARN_SOFT = "#FBF5EC"
ERROR = "#B00020"

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"

PLOT_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]
"""Matplotlib's default cycle: what "C0", "C1"... and no color at all draw."""

_FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
)

STYLE_SHEET = f"""
QMainWindow, QMainWindow::separator {{ background: {GROUND}; }}
QMainWindow::separator {{ width: 1px; height: 1px; background: {BORDER}; }}
QToolTip {{ background: {INK}; color: {SURFACE}; border: 0; padding: 4px 6px; }}

QToolBar#main {{
    background: {SURFACE}; border: 0; border-bottom: 1px solid {BORDER};
    padding: 6px 10px; spacing: 6px;
}}
QToolBar#main QToolButton {{
    color: {INK}; background: {SURFACE}; border: 1px solid {CONTROL_BORDER};
    border-radius: 8px; padding: 5px 10px; min-height: 22px;
}}
QToolBar#main QToolButton:hover {{ background: {SUBTLE}; }}
QToolBar#main QToolButton:disabled {{ color: #A0A0A6; border-color: {BORDER}; }}
QToolBar#main QToolButton#quiet {{ border-color: transparent; padding: 5px 6px; }}
QToolBar#main QToolButton#primary {{
    background: {ACCENT}; color: {SURFACE}; border-color: {ACCENT}; font-weight: 500;
}}
QToolBar#main QToolButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QLabel#projectName {{ font-weight: 600; font-size: 14px; padding: 0 8px 0 4px; }}
QLabel#saveState {{ color: {MUTED}; }}

QWidget#sidePanel {{ background: {SURFACE}; }}
QLabel#panelTitle {{ font-weight: 600; font-size: 14px; }}
QLabel#sectionTitle {{ font-weight: 600; padding-top: 6px; }}
QLabel#caption, QLabel#hint {{ color: {MUTED}; }}
QLabel#kicker {{ color: {MUTED}; font-size: 11px; font-weight: 500; }}
QLabel#error {{ color: {ERROR}; }}

QTreeWidget {{ background: {SURFACE}; border: 0; outline: 0; }}
QTreeWidget::item {{ height: 30px; padding-left: 4px; }}
QTreeWidget::item:hover {{ background: {SUBTLE}; }}
QTreeWidget::item:selected {{ background: {ACCENT_SOFT}; color: {INK}; }}
QTreeWidget::branch {{ background: transparent; }}

QListWidget#problems {{
    background: {WARN_SOFT}; border: 0; border-top: 1px solid #EAD9BC; color: {INK};
}}
QListWidget#problems::item {{ padding: 6px 10px; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {SURFACE}; border: 1px solid {CONTROL_BORDER}; border-radius: 6px;
    padding: 4px 8px; min-height: 22px; selection-background-color: {ACCENT_SOFT};
    selection-color: {INK};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 22px; }}
QCheckBox {{ spacing: 8px; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {CONTROL_BORDER}; border-radius: 8px;
    padding: 6px 14px; color: {INK};
}}
QPushButton:hover {{ background: {SUBTLE}; }}
QPushButton:default, QPushButton#primary {{
    background: {ACCENT}; border-color: {ACCENT}; color: {SURFACE}; font-weight: 500;
}}
QToolButton#swatch {{ border: 2px solid {SURFACE}; border-radius: 13px; }}
QToolButton#swatch:checked {{ border: 2px solid {INK}; }}
QToolButton#choice {{
    background: {SURFACE}; border: 1px solid {CONTROL_BORDER}; border-radius: 6px;
    min-width: 30px; min-height: 26px;
}}
QToolButton#choice:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QToolButton#link {{
    border: 0; color: {ACCENT}; padding: 4px 0; background: transparent;
}}
QToolButton#link:hover {{ color: {ACCENT_HOVER}; text-decoration: underline; }}
QLabel#chip {{
    background: {SUBTLE}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 1px 8px; font-family: "{MONO}"; font-size: 12px;
}}
QWidget#section {{ border-bottom: 1px solid {BORDER}; }}
QToolButton#sectionToggle {{
    border: 0; background: transparent; font-weight: 600; padding: 0;
}}
QFrame#card {{
    background: {GROUND}; border: 1px solid {BORDER}; border-radius: 10px;
}}
QLabel#value {{ font-family: "{MONO}"; }}
QLabel#panelKicker {{ color: {ACCENT}; font-size: 11px; font-weight: 600; }}

QScrollArea {{ border: 0; background: {SURFACE}; }}

QScrollArea#startPage, QWidget#startBody {{ background: {GROUND}; }}
QWidget#startHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
QLabel#startTitle {{ font-size: 30px; font-weight: 600; }}
QLabel#lead {{ color: {MUTED}; font-size: 15px; }}
QLabel#sectionHeading {{ font-size: 16px; font-weight: 600; }}
QLabel#zoneTitle {{ font-size: 17px; font-weight: 600; }}
QLabel#tileTitle {{ font-weight: 600; }}
QFrame#dropZone {{
    background: {SURFACE}; border: 2px dashed {CONTROL_BORDER}; border-radius: 16px;
}}
QFrame#dropZone[active="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QPushButton#tile, QPushButton#recentRow {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
    padding: 0; text-align: left;
}}
QPushButton#tile:hover, QPushButton#recentRow:hover {{ border-color: {ACCENT}; }}
QPushButton#link {{ border: 0; background: transparent; color: {ACCENT}; }}
QPushButton#link:hover {{ color: {ACCENT_HOVER}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: #CFCFC9; border-radius: 3px; min-height: 30px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
"""


def load_fonts() -> None:
    """Register the bundled fonts with Qt; missing files are skipped."""
    folder = resources.files("figscribe.gui") / "fonts"
    for name in _FONT_FILES:
        data = (folder / name).read_bytes()
        QFontDatabase.addApplicationFontFromData(QByteArray(data))


def apply(app: QApplication) -> None:
    """Give the application figscribe's look."""
    load_fonts()
    app.setStyle("Fusion")
    font = QFont(SANS)
    font.setPixelSize(13)
    app.setFont(font)
    palette = app.palette()
    for role, color in (
        (QPalette.ColorRole.Window, GROUND),
        (QPalette.ColorRole.Base, SURFACE),
        (QPalette.ColorRole.AlternateBase, SUBTLE),
        (QPalette.ColorRole.Text, INK),
        (QPalette.ColorRole.WindowText, INK),
        (QPalette.ColorRole.ButtonText, INK),
        (QPalette.ColorRole.Button, SURFACE),
        (QPalette.ColorRole.Highlight, ACCENT_SOFT),
        (QPalette.ColorRole.HighlightedText, INK),
        (QPalette.ColorRole.PlaceholderText, "#8A8A90"),
    ):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    arrow = resources.files("figscribe.gui") / "icons" / "chevron-down.svg"
    app.setStyleSheet(
        STYLE_SHEET
        + f"QComboBox::down-arrow {{ image: url({Path(str(arrow)).as_posix()}); }}"
    )


def mono_font(pixel_size: int = 12) -> QFont:
    font = QFont(MONO)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPixelSize(pixel_size)
    return font


def plot_color(color: str | None, index: int) -> str:
    """The color a plot is drawn in: its own, or the cycle's at `index`."""
    if color is None:
        return PLOT_COLORS[index % len(PLOT_COLORS)]
    if len(color) == 2 and color[0] == "C" and color[1].isdigit():
        return PLOT_COLORS[int(color[1])]
    if color.startswith("tab:"):
        names = ["blue", "orange", "green", "red", "purple", "brown", "pink", "gray"]
        name = color[4:]
        if name in names:
            return PLOT_COLORS[names.index(name)]
    return color if QColor.isValidColorName(color) else INK


# --- icons ---------------------------------------------------------------------

_ICONS = {
    "swatch": '<circle cx="8" cy="8" r="7" fill="{c}"/>',
    "marker-o": '<circle cx="8" cy="8" r="4.5" fill="{c}"/>',
    "marker-s": '<rect x="4" y="4" width="8" height="8" fill="{c}"/>',
    "marker-^": '<path d="M8 3 L13 12 H3 Z" fill="{c}"/>',
    "marker-v": '<path d="M8 13 L13 4 H3 Z" fill="{c}"/>',
    "marker-D": '<path d="M8 2.5 L13 8 L8 13.5 L3 8 Z" fill="{c}"/>',
    "marker-none": '<path d="M4 8 H12" stroke="{c}" stroke-width="1.5"/>',
    "plus": '<path d="M8 3v10M3 8h10" stroke="{c}" stroke-width="1.6" '
    'stroke-linecap="round"/>',
    "undo": '<path d="M6 4 L3 7 L6 10 M3 7 H11 A3.5 3.5 0 0 1 11 14" stroke="{c}" '
    'stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "redo": '<path d="M10 4 L13 7 L10 10 M13 7 H5 A3.5 3.5 0 0 0 5 14" stroke="{c}" '
    'stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "export": '<path d="M8 2v8M5 7l3 3 3-3M3 12v2h10v-2" stroke="{c}" '
    'stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
    "fit": '<path d="M2 13 C5 13 6 3 8 3 C10 3 11 13 14 13" stroke="{c}" '
    'stroke-width="1.6" fill="none"/>',
    "eye": '<path d="M1.5 8 C3.5 4 12.5 4 14.5 8 C12.5 12 3.5 12 1.5 8 Z" fill="none" '
    'stroke="{c}" stroke-width="1.2"/><circle cx="8" cy="8" r="2" fill="{c}"/>',
    "eye-off": '<path d="M1.5 8 C3.5 4 12.5 4 14.5 8 C12.5 12 3.5 12 1.5 8 Z" '
    'fill="none" stroke="{c}" stroke-width="1.2"/><path d="M3 13 L13 3" '
    'stroke="{c}" stroke-width="1.2"/>',
    "figure": '<rect x="2" y="2" width="12" height="12" rx="1.5" fill="none" '
    'stroke="{c}" stroke-width="1.3"/>',
    "file": '<rect x="3" y="1.5" width="10" height="13" rx="1.5" fill="none" '
    'stroke="{c}" stroke-width="1.3"/><path d="M5.5 6h5M5.5 9h5" stroke="{c}" '
    'stroke-width="1.2"/>',
    "line": '<path d="M1 12 L5 7 L9 9 L15 3" stroke="{c}" stroke-width="1.8" '
    'fill="none" stroke-linejoin="round"/>',
    "scatter": '<circle cx="4" cy="11" r="1.8" fill="{c}"/><circle cx="8" cy="6" '
    'r="1.8" fill="{c}"/><circle cx="12.5" cy="9" r="1.8" fill="{c}"/>',
    "errorbar": '<path d="M8 2 V14 M5 2 H11 M5 14 H11" stroke="{c}" '
    'stroke-width="1.3"/><circle cx="8" cy="8" r="2.6" fill="{c}"/>',
    "residual": '<path d="M1 8 H15" stroke="#8A8A90" stroke-width="1" '
    'stroke-dasharray="2 2"/><circle cx="5" cy="6" r="1.7" fill="{c}"/>'
    '<circle cx="11" cy="10" r="1.7" fill="{c}"/>',
    "annotation": '<path d="M2 13 L7 8 M7 8 H14" stroke="{c}" stroke-width="1.5" '
    'fill="none" stroke-linecap="round"/>',
    "histogram": '<path d="M2 14 V9 H5 V5 H8 V7 H11 V10 H14 V14 Z" fill="{c}"/>',
    "image": '<rect x="2" y="2" width="12" height="12" fill="{c}" opacity="0.35"/>'
    '<rect x="2" y="2" width="6" height="6" fill="{c}"/>',
    "code": '<path d="M6 4 L2 8 L6 12 M10 4 L14 8 L10 12" stroke="{c}" '
    'stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
}

ARTIST_ICONS = {
    "swatch": '<circle cx="8" cy="8" r="7" fill="{c}"/>',
    "marker-o": '<circle cx="8" cy="8" r="4.5" fill="{c}"/>',
    "marker-s": '<rect x="4" y="4" width="8" height="8" fill="{c}"/>',
    "marker-^": '<path d="M8 3 L13 12 H3 Z" fill="{c}"/>',
    "marker-v": '<path d="M8 13 L13 4 H3 Z" fill="{c}"/>',
    "marker-D": '<path d="M8 2.5 L13 8 L8 13.5 L3 8 Z" fill="{c}"/>',
    "marker-none": '<path d="M4 8 H12" stroke="{c}" stroke-width="1.5"/>',
    "line": "line",
    "scatter": "scatter",
    "errorbar": "errorbar",
    "fit": "fit",
    "residual": "residual",
    "annotation": "annotation",
    "histogram": "histogram",
    "image": "image",
    "colormesh": "image",
}


def icon(name: str, color: str = INK, size: int = 16) -> QIcon:
    """A line icon drawn in `color`, crisp at any screen scale."""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
        f"{_ICONS[name].format(c=color)}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):
        pixmap = QPixmap(QSize(size * scale, size * scale))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
        painter.end()
        pixmap.setDevicePixelRatio(scale)
        result.addPixmap(pixmap)
    return result
