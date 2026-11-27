"""The installers carry the licenses of what they contain (decision 0066)."""

from __future__ import annotations

import importlib.util
import json
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
    sbom: list[dict] | None = None,
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
    if sbom is not None:
        path = info / "sboms" / f"{name}.cyclonedx.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"bomFormat": "CycloneDX", "components": sbom}))
        record.append(f"{info.name}/sboms/{path.name},,")
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


# --- Rust code compiled into packages -----------------------------------------


@pytest.mark.parametrize(
    ("expression", "chosen"),
    [
        ("MIT", ["MIT"]),
        ("Apache-2.0 OR MIT", ["MIT"]),
        ("Apache-2.0 OR GPL-2.0-only", ["Apache-2.0"]),
        ("MIT OR Apache-2.0 OR LGPL-2.1-or-later", ["MIT"]),
        ("(MIT OR Apache-2.0) AND Unicode-3.0", ["MIT", "Unicode-3.0"]),
        ("(Apache-2.0 OR MIT) AND BSD-3-Clause", ["MIT", "BSD-3-Clause"]),
        ("Apache-2.0 WITH LLVM-exception", ["Apache-2.0 WITH LLVM-exception"]),
        ("Zlib", ["Zlib"]),
    ],
)
def test_the_license_taken_where_there_is_a_choice(expression, chosen) -> None:
    assert notices.choose(expression) == chosen


@pytest.mark.parametrize("expression", ["GPL-3.0-only", "MIT AND Nobody-1.0", ""])
def test_a_license_without_a_text_stops_the_build(expression: str) -> None:
    with pytest.raises(SystemExit, match="license"):
        notices.choose(expression)


def _crate(name: str, expression: str | None, **fields) -> dict:
    licenses = [] if expression is None else [{"expression": expression}]
    return {
        "name": name,
        "version": "1.2.3",
        "purl": f"pkg:cargo/{name}@1.2.3",
        "licenses": licenses,
        **fields,
    }


def test_the_notices_list_the_crates_compiled_into_a_package(site: Site) -> None:
    site.add(
        "app",
        files={"LICENSE": "App."},
        sbom=[
            _crate("reader", "MIT", author="A. Writer <a@example.org>"),
            _crate("codec", "(MIT OR Apache-2.0) AND Unicode-3.0"),
        ],
    )

    text = notices.render(notices.closure(["app"], find=site), python_license="x")

    assert "reader 1.2.3 (MIT) by A. Writer <a@example.org>" in text
    assert "codec 1.2.3 (MIT, Unicode-3.0)" in text
    assert "https://crates.io/crates/reader/1.2.3" in text
    assert "Permission is hereby granted, free of charge" in text
    assert "UNICODE LICENSE V3" in text
    assert "UNICODE LICENSE" not in text.split("UNICODE LICENSE V3", 1)[1]
    assert "Apache License" not in text  # nothing was taken under it


def test_a_crate_that_names_no_license_stops_the_build(site: Site) -> None:
    site.add("app", files={"LICENSE": "App."}, sbom=[_crate("mystery", None)])

    with pytest.raises(SystemExit, match="mystery"):
        notices.render(notices.closure(["app"], find=site), python_license="x")


def test_the_license_of_every_crate_installed_here_has_its_text() -> None:
    """A new version of a package may bring a license without a text: found here
    rather than when an installer is built."""
    try:
        dists = notices.closure([notices.ROOT])
    except SystemExit as exc:  # without the extras the installers have
        pytest.skip(str(exc))
    notices.other_parts(dists)  # every other part is known, too
    crates = notices.crates(dists)
    # Older versions of the package carry no list of their parts.
    if any("sboms" in f.parts for f in dists["python-calamine"].files):
        assert any(crate["name"] == "calamine" for crate in crates)
    for crate in crates:
        assert notices.taken(crate), crate["name"]


# --- parts that are no Rust crates --------------------------------------------


def _part(name: str, **fields) -> dict:
    return {"name": name, "version": "4.0", "purl": "", **fields}


def test_openssl_is_named_with_its_license(site: Site) -> None:
    site.add("app", requires=("cryptography",), files={"LICENSE": "App."})
    site.add("cryptography", files={"LICENSE": "C."}, sbom=[_part("openssl")])

    text = notices.render(notices.closure(["app"], find=site), python_license="x")

    assert "openssl 4.0 (Apache-2.0)" in text and "in cryptography" in text
    assert "License text: Apache-2.0" in text and "Apache License" in text


def test_parts_a_package_names_itself_or_does_not_ship_are_not_repeated(
    site: Site,
) -> None:
    parts = [_part("FreeType"), _part("libimagequant"), _part("PIL._imaging")]
    site.add("pillow", files={"LICENSE": "P."}, sbom=parts)

    text = notices.render(notices.closure(["pillow"], find=site), python_license="x")

    assert "FreeType" not in text and "libimagequant" not in text


def test_an_unknown_part_stops_the_build(site: Site) -> None:
    site.add("app", files={"LICENSE": "A."}, sbom=[_part("libsurprise")])

    with pytest.raises(SystemExit, match="libsurprise"):
        notices.render(notices.closure(["app"], find=site), python_license="x")


def test_a_library_no_list_names_is_found_by_its_file(site: Site) -> None:
    dist = site.add("pillow", files={"LICENSE": "P."})
    info = dist._path
    library = info.parent / "pillow.libs" / "libXau-154567c4.so.6"
    library.parent.mkdir()
    library.write_bytes(b"")
    with (info / "RECORD").open("a") as record:
        record.write("pillow.libs/libXau-154567c4.so.6,,\n")

    dists = {"pillow": metadata.PathDistribution(info)}
    text = notices.render(dists, python_license="x")

    assert "libXau (MIT-open-group)" in text and "The Open Group" in text
