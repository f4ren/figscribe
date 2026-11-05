"""Try the frozen program the way a person would, before an installer is made
from it (decision 0066).

    python packaging/smoke.py [PROJECT]

Run after `make_installer.py`, with the Python that has figscribe installed: it
runs the script the frozen program writes. Three things are tried: it says its
version, it writes a script from a bundled example that a normal Python runs and
that draws the figure, and its window starts (here without a screen) and stays up.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from make_installer import frozen_program, version

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "beam-profile" / "beam.figscribe"
WINDOW_SECONDS = 15


def fail(message: str) -> int:
    print(f"FAILED: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    system = platform.system()
    example = Path(argv[0]) if argv else EXAMPLE
    program = frozen_program(system, console=True)
    window = frozen_program(system, console=False)
    if not program.exists():
        return fail(f"{program} was not made")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}

    said = subprocess.run(
        [program, "--version"], capture_output=True, text=True, env=env
    )
    if said.stdout.strip() != f"figscribe {version()}":
        return fail(f"--version said {said.stdout!r} {said.stderr!r}")
    print("version ok", flush=True)

    # Resolved: macOS keeps temporary folders behind a link, and a script's
    # data path is worked out from the folder as it is named.
    with tempfile.TemporaryDirectory() as unresolved:
        folder = str(Path(unresolved).resolve())
        script = Path(folder) / "figure.py"
        made = subprocess.run(
            [program, "script", example, "-o", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=300,
        )
        if made.returncode or not script.exists():
            return fail(f"no script: {made.stdout} {made.stderr}")
        ran = subprocess.run(
            [sys.executable, script],
            cwd=folder,
            capture_output=True,
            text=True,
            env={**env, "MPLBACKEND": "Agg"},
            timeout=300,
        )
        if ran.returncode or not list(Path(folder).glob("*.pdf")):
            return fail(f"the script did not draw: {ran.stdout} {ran.stderr}")
    print("script ok", flush=True)

    shown = subprocess.Popen(
        [window, example], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    time.sleep(WINDOW_SECONDS)
    alive = shown.poll() is None
    shown.terminate()
    output = shown.communicate(timeout=30)[0].decode(errors="replace")
    if not alive:
        return fail(f"the window closed on its own: {output}")
    print("window ok", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
