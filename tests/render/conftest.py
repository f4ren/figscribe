"""Fixtures for renderer tests: in-memory data instead of files."""

from __future__ import annotations

import numpy as np
import pytest

from figscribe.model import ColumnRef, CsvSource


@pytest.fixture
def source() -> CsvSource:
    return CsvSource(path="scan.csv", sha256="0" * 64, columns=["t", "U", "dU"])


@pytest.fixture
def columns() -> dict[str, np.ndarray]:
    t = np.linspace(0.0, 10.0, 21)
    return {
        "t": t,
        "U": np.exp(-((t - 5.0) ** 2) / 4.0),
        "dU": np.full_like(t, 0.05),
    }


@pytest.fixture
def data(columns: dict[str, np.ndarray]):
    """A data provider that resolves every reference against `columns`."""

    def resolve(ref: ColumnRef) -> np.ndarray:
        return columns[ref.column]

    return resolve


@pytest.fixture
def ref(source: CsvSource):
    def make(column: str) -> ColumnRef:
        return ColumnRef(source=source.id, column=column)

    return make
