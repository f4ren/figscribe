# Project brief: figscribe

## Goal

Build a lean desktop GUI for scientific plots that lets you create and fine-tune
figures interactively and produces **clean, standalone Python code**
(Matplotlib) as its output, rather than a proprietary project file.

Audience: scientists and engineers who find Origin unwieldy but don't want to
hand-write every detail in Matplotlib just to fine-tune a figure.

## Architectural principle (binding)

**The declarative plot model is the single source of truth.**

```
Plot model (dataclasses, JSON-serializable)
   │
   ├──> Renderer:        model -> Matplotlib figure (for GUI preview AND export)
   ├──> Code generator:  model -> standalone Python script
   └──> Persistence:     model <-> JSON project file
GUI: reads and mutates the model exclusively, via commands (see undo/redo)
```

Rules:
- The GUI never manipulates Matplotlib objects directly in a persistent way.
  Every change runs as a command against the model, followed by a re-render.
- Preview and export use the same renderer. What you see is exactly what gets
  exported (at the same figure size and DPI).
- The generated code must run without figscribe installed and must produce the
  same figure as the renderer.
- Reading generated code back in is **not** a goal. Users are free to edit the
  code further; from that point it is theirs.

## Plot model (first draft, may be refined)

- `Project`: list of `Figure`, list of `DataSource`, metadata (version, creation
  date)
- `DataSource`: path, format (CSV, HDF5, NPY/NPZ), import options (delimiter,
  header row, HDF5 dataset path), SHA-256 of the file
- `Figure`: size in mm, DPI, stylesheet, layout (grid of rows and columns,
  shared axes)
- `Axes`: position in the grid, x/y label (LaTeX allowed), units, scale
  (linear/log/symlog), limits (auto or fixed), ticks, optional secondary y-axis,
  legend (position, visibility, frame)
- `Artist` (union type):
  - `LinePlot`, `ScatterPlot`, `ErrorbarPlot` (x, y, xerr, yerr as column
    references)
  - `Histogram` (bins, normalization)
  - `ImagePlot` / `ColorMesh` (2D data, colormap, colorbar, normalization)
  - `FitCurve` (reference to a data artist, model function, initial values,
    resulting parameters with uncertainties, optional residual panel)
  - `Annotation` (text, position in data or axes coordinates, optional arrow)
- Style properties per artist: color, line style, marker, line width, alpha,
  label, z-order

All model classes: typed, validatable, losslessly JSON-serializable with a
schema version for later migrations.

## MVP feature set

1. **Data import**: CSV, HDF5, NPY/NPZ. Column preview, selection of columns for
   x, y and errors. No spreadsheet, no column formulas.
2. **Plotting**: the artist types from the model.
3. **Canvas interaction**:
   - Click an element: it gets selected, its properties appear in the property
     panel
   - Drag the legend, annotations and labels to move them
   - Zoom and pan, and adopt the current view as fixed limits
4. **Property panel**: generated generically from the model fields, with
   specialized editors where it makes sense (color picker, marker selection).
5. **Axes**: log/linear, secondary y-axis, LaTeX labels, units.
6. **Layouts**: multi-panel grid with shared axes.
7. **Fits**: `scipy.optimize.curve_fit`, predefined models (linear, polynomial,
   Gaussian, Lorentzian, exponential) plus a custom expression. Output:
   parameters with 1-sigma uncertainties, reduced chi-square, optional residual
   plot.
8. **Undo/redo**: command pattern across all model changes.
9. **Export**: PDF, SVG and PNG at exact sizes in mm.
10. **Code generation**: a single Python script with
    - header: date, figscribe version, package versions, data paths with SHA-256
    - data loading, plotting and saving in clearly commented sections
    - only standard dependencies (numpy, matplotlib, optionally scipy, h5py)
11. **Style templates**: Matplotlib stylesheets (`.mplstyle`), shipping with a
    neutral default and a journal-style template (single column approx. 85 mm,
    double column approx. 175 mm).

## Deliberate non-goals

- No spreadsheet or data editing
- No statistics suite
- No custom scripting language
- No reading back generated or third-party Python code
- No Origin import in the MVP (possibly later for .opj via liborigin)

## Non-functional requirements

- Pixel-identical agreement between preview and export
- Fluid interaction up to approx. 10^6 data points (downsampling in the preview
  only; export always uses the full data)
- Platforms: Linux, Windows, macOS
- Reproducibility: project file and generated code contain data hashes and
  versions

## Technical stack

- Python >= 3.11
- PySide6 (Qt) for the GUI, Matplotlib canvas via `FigureCanvasQTAgg`
- Matplotlib as the only renderer
- NumPy, SciPy, h5py
- Model: dataclasses or pydantic (make a reasoned decision and document it)
- Tests: pytest, pytest-qt
- Packaging: `pyproject.toml`, later PyInstaller or Briefcase for installers
- License: MIT

## Proposed project structure

```
figscribe/
  model/        # dataclasses, validation, JSON (de)serialization, schema versions
  render/       # model -> Matplotlib
  codegen/      # model -> Python script
  io/           # data import (CSV, HDF5, NPY)
  fit/          # fit models and execution
  commands/     # command pattern, undo/redo
  gui/          # main window, canvas, property panel, dialogs
  styles/       # bundled .mplstyle files
tests/
examples/       # example data and example projects
```

## Test strategy (important)

1. **Model roundtrip**: model -> JSON -> model yields equality.
2. **Codegen equivalence** (core test): for each example project
   - the renderer produces PNG A
   - the generated script is run in a subprocess and produces PNG B
   - A and B must be pixel-identical (or within a very small, justified
     tolerance)
3. **Image regression tests** for the renderer against reference images.
4. **Command tests**: every change must be exactly reversible via undo.
5. **GUI smoke tests** with pytest-qt.

## Milestones

1. **M1 model and renderer**: model, JSON persistence, renderer for line,
   scatter and errorbar, export. No GUI yet. Tests 1 and 3.
2. **M2 code generator**: codegen for all M1 features, equivalence test (test 2)
   green.
3. **M3 GUI skeleton**: main window, data import dialog, canvas, click to
   select, generic property panel, undo/redo.
4. **M4 interaction**: drag for legend, labels and annotations, adopt zoom as
   limits.
5. **M5 extensions**: multi-panel layouts, secondary y-axis, histogram, 2D
   plots, colorbar.
6. **M6 fits**: fit dialog, result display, residual panel, codegen including
   the fit.
7. **M7 polish**: style templates, snapping and alignment guides, packaging.

Every milestone ends with green tests and a runnable state.

## Open tasks

- **Measure which models the assistant needs** (`figscribe bench`, decision
  0024). The tool exists; what is missing are measurements with real models,
  which have to run where the models are:
  1. Run the 21 cases against several local models in LM Studio or Ollama,
     from small (7–8 B) to mid-sized (20–30 B), with `--no-vision` where the
     model cannot read images, and `--repeat 3` because answers vary.
  2. Run the same against ChatGPT and Claude (Haiku 5.5, Sonnet 5.5,
     Opus 5.5) as the reference.
  3. Keep each run's `--json` file and compare passes per level, time and
     refused tool calls.
  4. For the cases local models fail: improve tool descriptions, the
     prompt's field list or the tools themselves (as `fit` with
     `residuals`), then measure again; add cases for requests users really
     make.
  5. Write down in the README which model sizes are good enough for which
     kind of request, and choose the default model accordingly.

## Working agreement for the coding agent

- Before M1: present the plot model as a code draft with a rationale, and only
  then implement.
- Work in small, test-driven steps: test first, then implementation.
- Record architectural decisions briefly in `docs/decisions.md` (context,
  decision, alternatives).
- No new dependencies without a rationale.
- When the model is unclear, ask rather than guess.
- Generated code should look the way an experienced human would write it:
  readable, commented, free of figscribe-internal helper functions.

## Optional, after the MVP

- ~~Natural-language input via an LLM that produces **commands against the
  model**~~ – done: the built-in chat and the MCP server change the project
  through undoable commands, with Claude, ChatGPT or a local model.
- Import of older Origin projects (.opj) via liborigin.
- Live data mode (watch a file, update the plot).
