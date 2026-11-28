"""Projects over data with times, for the tests of date axes."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from figscribe.io.csvfile import csv_source
from figscribe.model import Axes, ColumnRef, Figure, Project


def log_file(folder: Path, step: int = 600, count: int = 24, zone: str = "") -> Path:
    """A logger's file: a time every `step` seconds from 2026-11-01 22:00, a
    temperature T, its error dT and a pressure p."""
    start = np.datetime64("2026-11-01T22:00:00")
    rows = ["time,T,dT,p"]
    for i in range(count):
        stamp = start + np.timedelta64(i * step, "s")
        rows.append(f"{stamp}{zone},{20 + np.sin(i / 3):.4f},0.1,{1000 + i}")
    path = folder / "log.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def project_of(folder: Path, *artists, path: Path | None = None, **axes):
    """(the project, the function that refers to a column of its data)."""
    source = csv_source(path or log_file(folder), folder)

    def ref(column: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=column)

    panel = Axes(artists=[a(ref) for a in artists], **axes)
    return Project(sources=[source], figures=[Figure(axes=[panel])]), ref
