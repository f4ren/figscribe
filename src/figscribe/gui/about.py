"""The text of Help > About figscribe: the versions a bug report needs."""

from __future__ import annotations

import platform

import matplotlib
import PySide6
from PySide6.QtCore import qVersion

import figscribe

REPOSITORY = "https://github.com/f4ren/figscribe"


def system_name() -> str:
    """The system as a person knows it: macOS 15.1, not Darwin 24.1.0."""
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{platform.system()} {platform.release()}"


def about_text() -> str:
    """Rich text for `QMessageBox.about`."""
    return (
        f"<h3>figscribe {figscribe.__version__}</h3>"
        "<p>A desktop editor for scientific Matplotlib figures that exports "
        "standalone Python code.</p>"
        f"<p>Python {platform.python_version()} · Matplotlib "
        f"{matplotlib.__version__} · PySide6 {PySide6.__version__} "
        f"(Qt {qVersion()})<br>{system_name()}</p>"
        f'<p><a href="{REPOSITORY}">{REPOSITORY.removeprefix("https://")}</a></p>'
    )
