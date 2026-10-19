"""GUI tests run without a display."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EXAMPLE = Path(__file__).parents[2] / "examples" / "gaussian-scan"


@pytest.fixture
def example(tmp_path: Path) -> Path:
    """A writable copy of the example project; returns its project file."""
    target = tmp_path / "gaussian-scan"
    shutil.copytree(EXAMPLE, target)
    return target / "scan.figscribe"
