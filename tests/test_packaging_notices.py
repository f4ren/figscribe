"""The installers carry the licenses of what they contain (decision 0066)."""

from __future__ import annotations

import importlib.util
import sys
from importlib import metadata
from pathlib import Path

import pytest

PACKAGING = Path(__file__).parents[1] / "packaging"


def _load():
    spec = importlib.util.spec_from_file_location("notices", PACKAGING / "notices.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["notices"] = module
    spec.loader.exec_module(module)
    return module


notices = _load()


def make_dist(
    root: Path,
    name: str,
    version: str = "1.0",
    requires: tuple[str, ...] = (),
    files: dict[str, str] | None = None,
    license_expression: str = "MIT",
) -> metadata.Distribution:
    """A distribution on disk, as pip leaves one: `files` are relative to the
    `licenses` folder of its dist-info."""
    info = root / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = [
        "Metadata-Version: 2.4",
        f"Name: {name}",
        f"Version: {version}",
        f"License-Expression: {license_expression}",
    ]
    lines += [f"Requires-Dist: {r}" for r in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n")
    record = ["METADATA,,"]
    for relative, text in (files or {}).items():
        path = info / "licenses" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        record.append(f"{info.name}/licenses/{relative},,")
    (info / "RECORD").write_text("\n".join(record) + "\n")
    return metadata.PathDistribution(info)


class Site:
    """Distributions in a folder, found by name like `metadata.distribution`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.found: dict[str, metadata.Distribution] = {}

    def add(self, name: str, **kwargs) -> metadata.Distribution:
        dist = make_dist(self.root, name, **kwargs)
        self.found[notices.normalize(name)] = dist
        return dist

    def __call__(self, name: str) -> metadata.Distribution:
        try:
            return self.found[notices.normalize(name)]
        except KeyError:
            raise metadata.PackageNotFoundError(name) from None


@pytest.fixture
def site(tmp_path: Path) -> Site:
    return Site(tmp_path)


def test_names_are_compared_the_way_pip_does() -> None:
    assert notices.normalize("PySide6_Essentials") == "pyside6-essentials"
    assert notices.normalize("zope.interface") == "zope-interface"


def test_the_closure_follows_requirements_and_the_extras_asked_for(site: Site) -> None:
    site.add(
        "app", requires=("lib", 'chat-lib; extra == "chat"', 'mcp-lib; extra == "mcp"')
    )
    site.add("lib", requires=("deep",))
    site.add("deep")
    site.add("chat-lib")
    site.add("mcp-lib")

    plain = notices.closure(["app"], find=site)
    both = notices.closure(["app[chat]"], find=site)

    assert set(plain) == {"app", "lib", "deep"}
    assert set(both) == {"app", "lib", "deep", "chat-lib"}


def test_the_extras_a_requirement_asks_for_count(site: Site) -> None:
    site.add("app", requires=("lib[fast]",))
    site.add("lib", requires=('speed; extra == "fast"', 'slow; extra == "other"'))
    site.add("speed")
    site.add("slow")

    assert set(notices.closure(["app"], find=site)) == {"app", "lib", "speed"}


def test_requirements_of_another_system_or_python_are_left_out(site: Site) -> None:
    site.add(
        "app",
        requires=(
            'nowhere; sys_platform == "no such system"',
            'here; python_version >= "3.0"',
        ),
    )
    site.add("nowhere")
    site.add("here")

    assert set(notices.closure(["app"], find=site)) == {"app", "here"}


def test_a_requirement_that_is_not_installed_is_an_error(site: Site) -> None:
    site.add("app", requires=("missing",))

    with pytest.raises(SystemExit, match="missing"):
        notices.closure(["app"], find=site)


def test_every_license_file_of_a_package_is_read(site: Site) -> None:
    dist = site.add(
        "lib",
        files={
            "LICENSE": "The license.",
            "NOTICE": "Credit where due.",
            "vendored/LICENSE.APACHE": "Vendored code.",
        },
    )

    assert dict(notices.license_files(dist)) == {
        "LICENSE": "The license.",
        "NOTICE": "Credit where due.",
        "vendored/LICENSE.APACHE": "Vendored code.",
    }


def test_the_old_place_of_a_license_file_is_read_too(tmp_path: Path) -> None:
    dist = make_dist(tmp_path, "old")
    info = dist._path
    (info / "LICENSE.txt").write_text("Old style.")
    with (info / "RECORD").open("a") as record:
        record.write(f"{info.name}/LICENSE.txt,,\n")

    assert dict(notices.license_files(metadata.PathDistribution(info))) == {
        "LICENSE.txt": "Old style."
    }


def test_the_notices_name_each_package_with_its_license(site: Site) -> None:
    site.add("app", requires=("lib",), files={"LICENSE": "App text."})
    site.add(
        "lib",
        version="2.5",
        files={"LICENSE": "Lib text."},
        license_expression="BSD-3-Clause",
    )

    text = notices.render(
        notices.closure(["app"], find=site),
        python_license="Python text.",
    )

    assert "lib 2.5" in text and "BSD-3-Clause" in text
    assert "Lib text." in text and "App text." in text
    assert "Python text." in text


def test_a_package_without_a_license_text_stops_the_build(site: Site) -> None:
    site.add("app", requires=("bare",), files={"LICENSE": "App text."})
    site.add("bare")

    with pytest.raises(SystemExit, match="bare"):
        notices.render(notices.closure(["app"], find=site), python_license="x")


def test_qt_for_python_is_one_entry_with_the_lgpl_and_where_the_source_is(
    site: Site,
) -> None:
    site.add("app", requires=("PySide6", "shiboken6"), files={"LICENSE": "App."})
    site.add("PySide6", version="6.12.0", requires=("PySide6-Essentials",))
    site.add("PySide6-Essentials", version="6.12.0")
    site.add("shiboken6", version="6.12.0")

    text = notices.render(notices.closure(["app"], find=site), python_license="x")

    assert text.count("Qt for Python") >= 1
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "6.12.0" in text
    assert "code.qt.io" in text
    assert "replace" in text  # the libraries may be swapped for another build
    # one entry for the family, not one for each wheel
    assert "PySide6-Essentials" not in text


def test_the_pythons_license_is_found_next_to_the_standard_library() -> None:
    text = notices.python_license()

    assert "Python" in text and len(text) > 1000


def test_the_texts_that_no_wheel_carries_are_committed() -> None:
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt"):
        assert (PACKAGING / "licenses" / name).read_text().strip()
