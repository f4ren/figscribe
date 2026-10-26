"""The installers' icons are made from the same drawing as the window icon."""

from __future__ import annotations

import runpy
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).parents[1] / "packaging" / "make_icons.py"


def test_make_icons_writes_every_platforms_format(qapp, tmp_path: Path) -> None:
    runpy.run_path(str(SCRIPT))["make_icons"](tmp_path)

    with Image.open(tmp_path / "figscribe.icns") as icns:
        assert {(16, 16, 2), (512, 512, 2)} <= set(icns.info["sizes"])
    with Image.open(tmp_path / "figscribe.ico") as ico:
        assert {(16, 16), (256, 256)} <= ico.info["sizes"]
    with Image.open(tmp_path / "figscribe.png") as png:
        assert png.size == (1024, 1024)


def test_the_committed_icons_exist() -> None:
    for name in ("figscribe.icns", "figscribe.ico", "figscribe.png"):
        assert (SCRIPT.parent / "icons" / name).is_file()
