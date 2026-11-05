"""What the installer build leaves in its output folder (decision 0066)."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

PACKAGING = Path(__file__).parents[1] / "packaging"


def _load():
    sys.path.insert(0, str(PACKAGING))  # as when the script is run
    try:
        spec = importlib.util.spec_from_file_location(
            "make_installer", PACKAGING / "make_installer.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(PACKAGING))
    return module


make_installer = _load()


def test_the_tool_that_builds_an_appimage_is_not_taken_for_an_installer(
    tmp_path: Path, monkeypatch
) -> None:
    # The workflow attaches every `*.AppImage` in `out` to the release; the
    # first release carried appimagetool along with the real one.
    content = b"a tool"
    monkeypatch.setattr(make_installer, "OUT", tmp_path)
    monkeypatch.setattr(
        make_installer, "APPIMAGETOOL_SHA256", hashlib.sha256(content).hexdigest()
    )
    monkeypatch.setattr(
        make_installer.urllib.request,
        "urlretrieve",
        lambda url, target: Path(target).write_bytes(content),
    )

    tool = make_installer.download_appimagetool()

    assert tool.read_bytes() == content
    assert list(tmp_path.glob("*.AppImage")) == []
