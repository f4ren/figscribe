# figscribe — notes for coding sessions

A desktop GUI for scientific Matplotlib figures that exports standalone Python
code. Start here:

- **What to work on:** [`plan/roadmap.md`](plan/roadmap.md). Take the first
  open task of the lowest open phase unless the user names another, and follow
  its "How to work on this plan" rules. Tasks marked `[decide]` need the
  user's answer before any code.
- **Why things are as they are:** [`docs/decisions.md`](docs/decisions.md).
  Read the entries for the area you touch before changing it.
- **The vision and non-goals:** [`plan/project-brief.md`](plan/project-brief.md).
- **How the GUI is tested:** [`docs/testing.md`](docs/testing.md), and the
  manual checklist there for changes that are seen.

## Architecture in one paragraph

The plot model (`src/figscribe/model/`, pydantic) is the single source of
truth. The renderer (`render/`), the code generator (`codegen/`) and the
project file all read it; the GUI (`gui/`) and the assistant (`assistant/`,
`tools/`) change it only through undoable commands (`commands/`). A model
field is not finished until it reaches the renderer, the code generator, the
property panel and the assistant tools.

## Commands

```
pip install -e ".[dev]"                 # all extras, as CI installs them
python -m pytest -q                     # Qt runs offscreen, set in tests/conftest.py
python -m pytest -q -m "not slow"       # without the field test, while iterating
ruff check . && ruff format --check .   # CI fails on either
FIGSCRIBE_UPDATE_BASELINES=1 python -m pytest tests/render/test_images.py
                                        # after an intended rendering change;
                                        # look at the new images before committing
```

## Conventions

- Everything in the repository is English, commit messages included.
- Test first; for a bug, a failing test that reproduces it comes first.
- One task per branch, branched from `develop`; pull request into `develop`;
  CI must be green on Linux, Windows and macOS. `main` only gets releases.
- Commits use the repository's configured identity (f4ren); no
  Co-Authored-By trailer.
- No new dependency without a rationale in `docs/decisions.md`.
- Generated scripts must read as if a person wrote them: no figscribe
  helpers, named variables, comments where they help.
