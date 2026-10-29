"""Export a rendered figure to PNG, PDF or SVG at its exact physical size."""

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
}


def export(figure: Figure, data: DataProvider, path: str | Path) -> None:
    """Render `figure` and write it to `path`; the suffix picks the format.

    Never uses bbox_inches="tight", which would crop the figure away from the
    size the user asked for.
    """
    path = Path(path)
    _save(figure, data, path, path.suffix.lower())


def export_bytes(figure: Figure, data: DataProvider, suffix: str) -> bytes:
    """The file `export` would write for `suffix` (".png", ".pdf" or ".svg"),
    as bytes: what goes to the clipboard."""
    target = io.BytesIO()
    _save(figure, data, target, suffix.lower())
    return target.getvalue()


def _save(figure: Figure, data: DataProvider, target, suffix: str) -> None:
    if suffix not in _METADATA:
        raise ValueError(
            f"cannot export to {suffix!r}; supported are {', '.join(_METADATA)}"
        )

    fig = render(figure, data)
    # A fixed salt makes the SVG element ids deterministic.
    rc = {"svg.hashsalt": "figscribe"} if suffix == ".svg" else {}
    with style_context(figure), matplotlib.rc_context(rc):
        fig.savefig(
            target,
            format=suffix[1:],
            dpi=figure.dpi,
            metadata=_METADATA[suffix],
        )
