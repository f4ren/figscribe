# figscribe

A lean desktop GUI for scientific plots: build and fine-tune figures
interactively, and get **clean, standalone Python code** (Matplotlib) as the
result instead of a proprietary project file.

Intended for scientists and engineers who find Origin unwieldy but don't want to
hand-write every detail of a Matplotlib figure just to fine-tune it.

## Status

**Early development.** The plot model with its JSON project file, the renderer
for line, scatter and errorbar plots, fits and residuals with export to
PDF/SVG/PNG, CSV import, undoable commands, curve fitting and the code
generator exist and are tested. The GUI (`figscribe`) starts from a data file
or a layout, proposes a first plot, fits models with a residual panel, edits
every property with undo/redo, and saves and exports projects and Python
scripts.

## The generated code

*File > Export Python Script…* (or `figscribe script PROJECT.figscribe -o
plot.py`) writes a standalone script that needs only NumPy, Matplotlib and,
for fits, SciPy. It checks the data file's SHA-256, loads it with
`np.loadtxt`, fits with `scipy.optimize.curve_fit` from the same start values,
and draws exactly what figscribe shows: a test runs every example script and
compares its PNG pixel by pixel with figscribe's own export.

The full project plan lives in [`plan/`](plan/).

## Assistants (MCP)

figscribe can be driven by an assistant in any MCP client (Claude Desktop,
Claude Code, IDEs, front ends for local models): "two panels, residuals below,
shared x axis" becomes changes to the open project, live in the window and
undoable there. The assistant works through the same commands as the GUI and
sees the project's structure and column names, never the data, unless you let
it see the figure.

```
pip install "figscribe[mcp]"
claude mcp add figscribe -- figscribe mcp      # e.g. for Claude Code
```

Then enable *Assistant > Allow MCP access* in figscribe; *Assistant > How to
connect* shows the configuration for other clients.

## Design principle

The declarative plot model is the single source of truth:

```
Plot model (typed, JSON-serializable)
   ├──> Renderer:       model -> Matplotlib figure (GUI preview AND export)
   ├──> Code generator:  model -> standalone Python script
   └──> Persistence:    model <-> JSON project file
```

The GUI only ever reads and mutates the model, through commands with undo/redo —
it never manipulates Matplotlib objects directly. Preview and export share the
same renderer, so what you see is what you get. The generated code reproduces the
same figure and runs without figscribe installed.

## Scope

Planned for the MVP: data import (CSV, HDF5, NPY/NPZ), line/scatter/errorbar
plots, histograms, 2D images and color meshes, curve fitting via
`scipy.optimize.curve_fit`, multi-panel layouts with shared axes, LaTeX labels,
undo/redo, export to PDF/SVG/PNG at exact millimeter sizes, and Matplotlib style
templates for journal-column widths.

Deliberately out of scope: spreadsheet-style data editing, a statistics suite, a
custom scripting language, and reading generated or third-party Python code back
in.

## Stack

Python >= 3.11, PySide6, Matplotlib, NumPy, SciPy, h5py.

## License

MIT, see [LICENSE](LICENSE).
