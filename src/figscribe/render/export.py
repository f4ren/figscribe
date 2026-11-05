"""Export a rendered figure to PDF, SVG, EPS, PNG or TIFF at its exact physical
size."""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

from figscribe.model import Figure
from figscribe.render.figure import DataProvider, render, style_context

# Timestamps and random ids are dropped so that an unchanged figure gives a
# byte-identical file, which keeps exports diffable and reproducible.
_METADATA = {
    ".png": {"Software": None},
    ".pdf": {"Creator": None, "Producer": None, "CreationDate": None},
    ".svg": {"Creator": None, "Date": None},
    ".eps": {"Creator": None},
    ".tif": None,
    ".tiff": None,
}
FORMATS = {".tif": "tiff", ".tiff": "tiff"}
"""The name Matplotlib knows a suffix by, where it is not the suffix itself."""
TIFF = {"compression": "tiff_lzw"}
"""Journals ask for TIFF with LZW compression, which loses nothing."""


def export(
    figure: Figure, data: DataProvider, path: str | Path, transparent: bool = False
) -> None:
    """Render `figure` and write it to `path`; the suffix picks the format.
    With `transparent`, the figure's and the panels' backgrounds are left out
    (PNG, TIFF, SVG; PDF and EPS have none to begin with).

    Never uses bbox_inches="tight", which would crop the figure away from the
    size the user asked for.
    """
    path = Path(path)
    _save(figure, data, path, path.suffix.lower(), transparent)


def export_bytes(
    figure: Figure, data: DataProvider, suffix: str, transparent: bool = False
) -> bytes:
    """The file `export` would write for `suffix` (".png", ".pdf", ".svg" …),
    as bytes: what goes to the clipboard."""
    target = io.BytesIO()
    _save(figure, data, target, suffix.lower(), transparent)
    return target.getvalue()


def _save(
    figure: Figure, data: DataProvider, target, suffix: str, transparent: bool = False
) -> None:
    if suffix not in _METADATA:
        raise ValueError(
            f"cannot export to {suffix!r}; supported are {', '.join(_METADATA)}"
        )

    fig = render(figure, data)
    # A fixed salt makes the SVG element ids deterministic.
    rc = {"svg.hashsalt": "figscribe"} if suffix == ".svg" else {}
    with style_context(figure), matplotlib.rc_context(rc):
        extra = {"metadata": _METADATA[suffix]} if _METADATA[suffix] else {}
        if FORMATS.get(suffix) == "tiff":
            extra["pil_kwargs"] = TIFF
        fig.savefig(
            target,
            format=FORMATS.get(suffix, suffix[1:]),
            dpi=figure.dpi,
            transparent=transparent,
            **extra,
        )
