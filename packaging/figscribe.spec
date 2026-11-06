# PyInstaller spec for figscribe, for all three systems (decision 0066).
# Run through packaging/make_installer.py, which sets the folders and writes the
# licenses (packaging/notices.py) that go into the program's folder.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

import figscribe

root = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is set by PyInstaller
icons = root / "packaging" / "icons"

analysis = Analysis(  # noqa: F821
    [str(root / "packaging" / "launcher.py")],
    # Fonts, icons and the examples ship inside the package; the licenses of
    # everything in it come with them, in `licenses`.
    datas=collect_data_files("figscribe")
    + [(os.environ["FIGSCRIBE_LICENSES"], "licenses")],
    excludes=["tkinter", "pytest"],
)
archive = PYZ(analysis.pure)  # noqa: F821


def program(name: str, console: bool):
    return EXE(  # noqa: F821
        archive,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=str(icons / "figscribe.ico") if sys.platform == "win32" else None,
    )


if sys.platform == "win32":
    # A window program has no console, so `figscribe-cli script …` and
    # `figscribe-cli mcp` are a second program that has one.
    programs = [program("figscribe", False), program("figscribe-cli", True)]
else:
    programs = [program("figscribe", sys.platform != "darwin")]

collected = COLLECT(  # noqa: F821
    *programs,
    analysis.binaries,
    analysis.datas,
    name="figscribe",
)

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        collected,
        name="figscribe.app",
        icon=str(icons / "figscribe.icns"),
        bundle_identifier="io.github.f4ren.figscribe",
        info_plist={
            "CFBundleName": "figscribe",
            "CFBundleDisplayName": "figscribe",
            "CFBundleShortVersionString": figscribe.__version__,
            "CFBundleVersion": figscribe.__version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.graphics-design",
            # Finder offers figscribe for a project and opens it on a double click
            # (the program gets the file as an event, see gui/app.py).
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "figscribe project",
                    "CFBundleTypeExtensions": ["figscribe"],
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "CFBundleTypeIconFile": "figscribe.icns",
                }
            ],
        },
    )
