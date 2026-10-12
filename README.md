# figscribe

A lean desktop GUI for scientific plots: build and fine-tune figures
interactively, and get **clean, standalone Python code** (Matplotlib) as the
result instead of a proprietary project file.

Intended for scientists and engineers who find Origin unwieldy but don't want to
hand-write every detail of a Matplotlib figure just to fine-tune it.

## Status

**Very early — planning stage.** Nothing usable has been implemented yet; the
PyPI entry is a placeholder release that reserves the name.

The full project plan lives in [`plan/`](plan/).

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
