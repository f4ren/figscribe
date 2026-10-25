"""How the generated script reads, and where it can be had from."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from figscribe.codegen import generate, script_name
from figscribe.fit import refit
from figscribe.io import load_data
from figscribe.model import Figure, FitCurve, PredefinedFit, loads


@pytest.fixture
def project(example: Path):
    return loads(example.read_text(encoding="utf-8"))


def test_the_script_reads_like_handwritten_code(project, example: Path) -> None:
    script = generate(project, base_dir=example.parent)
    assert script.startswith('"""Scan: 85 × 60 mm at 300 dpi.')
    assert (
        't, U, dU = np.loadtxt(scan_path, delimiter=",", skiprows=3, unpack=True)'
        in (script)
    )
    assert 'ax.set_xlabel("$t$ (s)")' in script
    assert 'fig.savefig(HERE / "scan.pdf")' in script
    assert "curve_fit" not in script and "scipy" not in script
    assert all(len(line) <= 88 for line in script.splitlines())
    compile(script, "scan.py", "exec")


def test_data_paths_are_relative_to_the_script(project, example: Path) -> None:
    elsewhere = example.parent / "code"
    script = generate(project, base_dir=example.parent, script_dir=elsewhere)
    assert 'scan_path = HERE / "../scan.csv"' in script


def test_an_unfitted_fit_is_left_out(project, example: Path) -> None:
    axes = project.figures[0].axes[0]
    axes.artists.append(
        FitCurve(target=axes.artists[0].id, model=PredefinedFit(name="linear"))
    )
    script = generate(project, base_dir=example.parent)
    assert "curve_fit" not in script
    assert "is not fitted yet" in script


def test_fit_data_with_gaps_is_filtered(project, example: Path) -> None:
    axes = project.figures[0].axes[0]
    fit = FitCurve(target=axes.artists[0].id, model=PredefinedFit(name="linear"))
    axes.artists.append(fit)
    data = load_data(project, example.parent)
    refit(project, fit.id, data).apply(project)
    clean = generate(project, base_dir=example.parent, data=data)
    assert "valid" not in clean and "t.min()" in clean
    unknown = generate(project, base_dir=example.parent)
    assert "valid = np.isfinite(t) & np.isfinite(U) & np.isfinite(dU)" in unknown


def test_names_for_files() -> None:
    assert script_name(Figure(name="Fig. 2 (b)")) == "fig_2_b.py"
    assert script_name(Figure(name="***")) == "figure.py"


def test_the_command_line_writes_the_script(example: Path, tmp_path: Path) -> None:
    folder = tmp_path / "copy"
    shutil.copytree(example.parent, folder)
    target = folder / "plot_scan.py"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "figscribe.cli",
            "script",
            str(folder / example.name),
            "-o",
            str(target),
        ],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "src"), **_env()},
    )
    assert done.returncode == 0, done.stderr
    assert 'fig.savefig(HERE / "plot_scan.pdf")' in target.read_text(encoding="utf-8")

    printed = subprocess.run(
        [sys.executable, "-m", "figscribe.cli", "script", str(folder / example.name)],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "src"), **_env()},
    )
    assert printed.stdout.startswith('"""Scan')

    wrong = subprocess.run(
        [sys.executable, "-m", "figscribe.cli", "script"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(Path(__file__).parents[2] / "src"), **_env()},
    )
    assert wrong.returncode == 2 and "usage" in wrong.stderr


def test_the_command_line_writes_the_script_without_unreadable_data(
    example: Path, tmp_path: Path, capsys
) -> None:
    from figscribe.cli import _script
    from figscribe.model import dumps

    project = loads(example.read_text(encoding="utf-8"))
    project.figures[0].axes[0].x.major_step = 2.0  # needs the data's range
    path = tmp_path / example.name
    path.write_text(dumps(project), encoding="utf-8")  # without its data file

    assert _script([str(path)]) == 0
    printed = capsys.readouterr()
    assert "MultipleLocator(2)" in printed.out
    assert "writing the script without it" in printed.err


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
