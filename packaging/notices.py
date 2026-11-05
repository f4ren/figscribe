"""The licenses of what an installer contains (decision 0066).

    python packaging/notices.py [FOLDER]

writes `THIRD-PARTY-NOTICES.txt` and `LICENSE.txt` into FOLDER (default
`packaging/out/licenses`). `make_installer.py` does it before it freezes the
program and puts the folder into every installer.

The packages are those figscribe needs with the extras the installers have
(`chat`, `mcp`), found in the environment the program is frozen from, with the
license files each one carries; so the list is the one of the installer it goes
into, on that system. A package without a license file stops the build: an
installer must not leave out what a license asks to be handed on.

Two things no wheel carries are added: Qt for Python (PySide6 and shiboken6 say
LGPL in their metadata but ship no text) and the Python the program runs on.
The texts of the LGPL and the GPL are in `packaging/licenses`.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

HERE = Path(__file__).resolve().parent
LICENSES = HERE / "licenses"
OUT = HERE / "out"

# figscribe with the extras of the installers. PyInstaller is added by itself:
# its bootloader is part of every installer (and its license has an exception
# for that), the packages it needs to freeze are not.
ROOT = "figscribe[chat,mcp]"
FREEZER = "pyinstaller"

QT_SOURCE = (
    "https://code.qt.io/cgit/pyside/pyside-setup.git (the tag v{version}) and "
    "https://download.qt.io/official_releases/QtForPython/"
)
QT_SOURCE_OF_QT = "https://download.qt.io/official_releases/qt/"
QT_THIRD_PARTY = "https://doc.qt.io/qt-6/licenses-used-in-qt.html"

Find = Callable[[str], metadata.Distribution]


def normalize(name: str) -> str:
    """A package name the way pip compares them."""
    return re.sub(r"[-_.]+", "-", name).lower()


def is_qt(name: str) -> bool:
    return normalize(name).startswith("pyside6") or normalize(name) == "shiboken6"


def closure(
    roots: list[str], find: Find = metadata.distribution
) -> dict[str, metadata.Distribution]:
    """The packages the requirements `roots` (such as `app[extra]`) lead to,
    by normalized name, with the requirements that apply here: the markers
    of the system and the extras each requirement asks for."""
    found: dict[str, metadata.Distribution] = {}
    seen: set[tuple[str, frozenset[str]]] = set()
    pending = [Requirement(root) for root in roots]
    while pending:
        requirement = pending.pop()
        key = (normalize(requirement.name), frozenset(requirement.extras))
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = find(requirement.name)
        except metadata.PackageNotFoundError:
            raise SystemExit(
                f"{requirement.name} is required but not installed here"
            ) from None
        found[key[0]] = dist
        extras = {"", *requirement.extras}
        for text in dist.requires or []:
            child = Requirement(text)
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in extras
            ):
                pending.append(child)
    return found


def license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """The license files a package carries, as (name, text): those in the
    `licenses` folder of its metadata, and the ones older tools put beside it."""
    files = []
    for file in dist.files or []:
        parts = file.parts
        if not parts[0].endswith((".dist-info", ".egg-info")):
            continue
        rest = parts[1:]
        if rest and rest[0] == "licenses" and len(rest) > 1:
            name = "/".join(rest[1:])
        elif len(rest) == 1 and re.match(r"(?i)(licen[cs]e|copying|notice)", rest[0]):
            name = rest[0]
        else:
            continue
        text = Path(dist.locate_file(file)).read_text(
            encoding="utf-8", errors="replace"
        )
        files.append((name, text.strip("\n")))
    return sorted(files)


def python_license() -> str:
    """The license text of the Python the program is frozen from."""
    candidates = [
        Path(os.__file__).parent / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace").strip("\n")
    raise SystemExit(
        "the license of Python was not found in " + ", ".join(map(str, candidates))
    )


RULE = "=" * 78

HEADER = """\
Third-party software in figscribe

figscribe is free software under the MIT license (LICENSE.txt). It contains
the programs below, each under its own license, which is given in full. This
list is made when the installer is built, from the packages that went into it.
"""


def _section(title: str, body: str) -> str:
    return f"{RULE}\n{title}\n{RULE}\n\n{body.strip(chr(10))}\n"


def _qt_section(versions: dict[str, str]) -> str:
    version = versions.get("pyside6", "")
    shiboken = versions.get("shiboken6", version)
    lgpl = (LICENSES / "LGPL-3.0.txt").read_text(encoding="utf-8")
    gpl = (LICENSES / "GPL-3.0.txt").read_text(encoding="utf-8")
    intro = f"""\
figscribe uses Qt through Qt for Python (PySide6 {version}, shiboken6 {shiboken}),
under the GNU Lesser General Public License, version 3 (the text follows, and
the GNU General Public License, version 3, which it refers to). Qt for Python
and Qt are also available under other licenses; figscribe uses them under this one.

The Qt libraries are separate files in the folder of this program, not
compiled into it. You may replace them with another build of the same version
of Qt for Python, and the program will use that.

The source code of Qt for Python: {QT_SOURCE.format(version=version)}
The source code of Qt: {QT_SOURCE_OF_QT}
Third-party code inside Qt and its licenses: {QT_THIRD_PARTY}
"""
    return "\n".join(
        [
            _section("Qt for Python and Qt (LGPL-3.0)", intro),
            _section("GNU Lesser General Public License, version 3", lgpl),
            _section("GNU General Public License, version 3", gpl),
        ]
    )


def render(dists: dict[str, metadata.Distribution], python_license: str) -> str:
    """The text of THIRD-PARTY-NOTICES.txt for the packages `dists`."""
    sections = [HEADER]
    qt = {name: dist.version for name, dist in dists.items() if is_qt(name)}
    if qt:
        sections.append(_qt_section({normalize(n): v for n, v in qt.items()}))
    missing = []
    for name, dist in sorted(dists.items()):
        if is_qt(name):
            continue
        texts = license_files(dist)
        if not texts:
            missing.append(name)
            continue
        meta = dist.metadata
        kind = meta.get("License-Expression") or ""
        title = f"{meta['Name']} {dist.version}" + (f" ({kind})" if kind else "")
        body = "\n\n".join(
            f"--- {file} ---\n\n{text}" if len(texts) > 1 else text
            for file, text in texts
        )
        sections.append(_section(title, body))
    if missing:
        raise SystemExit(
            "no license file in the metadata of " + ", ".join(missing) + "; "
            "an installer must carry its license (decision 0066)"
        )
    sections.append(_section("Python", python_license))
    return "\n".join(sections)


def write(folder: Path) -> Path:
    """Write the notices and figscribe's own license into `folder`; returns the
    notices file."""
    folder.mkdir(parents=True, exist_ok=True)
    notices = folder / "THIRD-PARTY-NOTICES.txt"
    dists = closure([ROOT])
    try:
        dists[FREEZER] = metadata.distribution(FREEZER)
    except metadata.PackageNotFoundError:
        raise SystemExit(f"{FREEZER} is not installed here") from None
    notices.write_text(render(dists, python_license()), encoding="utf-8", newline="\n")
    shutil.copy(HERE.parent / "LICENSE", folder / "LICENSE.txt")
    return notices


if __name__ == "__main__":
    target = write(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "licenses")
    print(f"wrote {target} ({target.stat().st_size / 1e3:.0f} kB)")
