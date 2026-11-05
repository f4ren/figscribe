"""Build the installer for the system this runs on (decision 0066).

    python packaging/make_installer.py

Run it in an environment that has figscribe installed from its wheel (with the
`chat` and `mcp` extras) and PyInstaller. The result is in `packaging/out`:

    macOS    figscribe-VERSION-macos-arm64.dmg
    Windows  figscribe-VERSION-windows-x64-setup.exe
    Linux    figscribe-VERSION-linux-x86_64.AppImage

The program is frozen into a folder first (PyInstaller, one directory rather
than one file: it starts faster, and Qt stays a set of libraries that can be
replaced), then wrapped in what the system installs from. The licenses of what
is inside (`notices.py`) go into the folder, and are beside the program in each
installer.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

import notices

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FROZEN = OUT / "pyinstaller"
SPEC = HERE / "figscribe.spec"
LICENSES = OUT / "licenses"  # what notices.py writes, and the spec reads
LICENSE_FILES = ("THIRD-PARTY-NOTICES.txt", "LICENSE.txt")

APPIMAGETOOL = (
    "https://github.com/AppImage/appimagetool/releases/download/1.9.1/"
    "appimagetool-x86_64.AppImage"
)
APPIMAGETOOL_SHA256 = "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"


def version() -> str:
    import figscribe

    return figscribe.__version__


def artifact_name(version: str, system: str, machine: str) -> str:
    """The file name of the installer for `system` (what `platform.system()`
    says) on `machine`: the version, the system and the architecture, so that
    a download says what it is."""
    machine = machine.lower()
    if system == "Darwin":
        kind = "arm64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"figscribe-{version}-macos-{kind}.dmg"
    if system == "Windows":
        return f"figscribe-{version}-windows-x64-setup.exe"
    if system == "Linux":
        return f"figscribe-{version}-linux-x86_64.AppImage"
    raise SystemExit(f"no installer is made for {system}")


def frozen_program(system: str, console: bool = True) -> Path:
    """The program inside the frozen folder; on Windows the one with a console
    when `console`, which can print, or the window one."""
    if system == "Darwin":
        return FROZEN / "figscribe.app" / "Contents" / "MacOS" / "figscribe"
    if system == "Windows":
        name = "figscribe-cli.exe" if console else "figscribe.exe"
        return FROZEN / "figscribe" / name
    return FROZEN / "figscribe" / "figscribe"


def run(*command: str | Path, **kwargs) -> None:
    print("+", " ".join(str(c) for c in command), flush=True)
    subprocess.run([str(c) for c in command], check=True, **kwargs)


def copy_licenses(folder: Path) -> None:
    """Put the license files beside what an installer installs."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in LICENSE_FILES:
        shutil.copy(LICENSES / name, folder / name)


def freeze() -> None:
    shutil.rmtree(FROZEN, ignore_errors=True)
    shutil.rmtree(LICENSES, ignore_errors=True)
    notices.write(LICENSES)
    # In the program's folder (`licenses`) through the spec, before macOS signs
    # the app: nothing may be added to a signed app afterwards.
    os.environ["FIGSCRIBE_LICENSES"] = str(LICENSES)
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        FROZEN,
        "--workpath",
        OUT / "work",
        SPEC,
    )


def make_dmg(target: Path) -> None:
    staging = OUT / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    # Symbolic links kept: an app is a folder with some of them inside.
    shutil.copytree(FROZEN / "figscribe.app", staging / "figscribe.app", symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    copy_licenses(staging)  # beside the app, since the app itself is signed
    target.unlink(missing_ok=True)
    run(
        "hdiutil",
        "create",
        "-volname",
        "figscribe",
        "-srcfolder",
        staging,
        "-ov",
        "-format",
        "UDZO",
        target,
    )


def make_windows_installer(target: Path) -> None:
    copy_licenses(FROZEN / "figscribe")
    compiler = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    run(
        compiler,
        f"/DAppVersion={version()}",
        f"/DSourceDir={FROZEN / 'figscribe'}",
        f"/DIconFile={HERE / 'icons' / 'figscribe.ico'}",
        f"/DLicenseFile={LICENSES / 'LICENSE.txt'}",
        f"/DOutputDir={target.parent}",
        f"/DOutputName={target.stem}",
        HERE / "figscribe.iss",
    )


DESKTOP_FILE = """\
[Desktop Entry]
Type=Application
Name=figscribe
Comment=Scientific figures, exported as Python code
Exec=figscribe %f
Icon=figscribe
Categories=Graphics;Science;DataVisualization;
MimeType=application/x-figscribe;
Terminal=false
"""

APP_RUN = """\
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/figscribe/figscribe" "$@"
"""


def download_appimagetool() -> Path:
    tool = OUT / "appimagetool.AppImage"
    if not tool.exists():
        urllib.request.urlretrieve(APPIMAGETOOL, tool)
    digest = hashlib.sha256(tool.read_bytes()).hexdigest()
    if digest != APPIMAGETOOL_SHA256:
        tool.unlink()
        raise SystemExit(f"appimagetool has the checksum {digest}, not the pinned one")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    return tool


def make_appimage(target: Path) -> None:
    appdir = OUT / "figscribe.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(
        FROZEN / "figscribe", appdir / "usr" / "lib" / "figscribe", symlinks=True
    )
    copy_licenses(appdir / "usr" / "share" / "doc" / "figscribe")
    (appdir / "figscribe.desktop").write_text(DESKTOP_FILE)
    shutil.copy(HERE / "icons" / "figscribe.png", appdir / "figscribe.png")
    run_file = appdir / "AppRun"
    run_file.write_text(APP_RUN)
    run_file.chmod(0o755)
    target.unlink(missing_ok=True)
    # Run unpacked: the runners have no FUSE.
    env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}
    run(download_appimagetool(), appdir, target, env=env)


def main() -> int:
    system = platform.system()
    target = OUT / artifact_name(version(), system, platform.machine())
    OUT.mkdir(exist_ok=True)
    freeze()
    if system == "Darwin":
        make_dmg(target)
    elif system == "Windows":
        make_windows_installer(target)
    else:
        make_appimage(target)
    print(f"made {target} ({target.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
