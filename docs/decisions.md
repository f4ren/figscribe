# Architecture decisions

Short records of decisions that are not obvious from the code: context, the
decision, and the alternatives that were weighed.

---

## 0001 — Pydantic v2 for the plot model

**Date:** 2026-10-12
**Status:** accepted

### Context

The plot model is the single source of truth: the renderer, the code generator
and the project file all read it, and the GUI mutates it exclusively through
commands. Three requirements from the project brief drive the choice of how to
express it:

- `Artist` is a union type (line, scatter, errorbar, histogram, image, mesh,
  fit, annotation) that must deserialize back to the correct concrete class.
- Model to JSON to model must be lossless and compare equal (test 1).
- The project file carries a schema version so that older files can be migrated.

Two non-arguments were ruled out first. **Performance is irrelevant**: the model
holds column references, not measurements, so it amounts to a few hundred small
objects regardless of how many data points a figure draws. **Dependency weight
is nearly irrelevant**: the application already ships PySide6, Matplotlib, SciPy
and h5py.

What remains is how much serialization code we write and maintain ourselves.

### Decision

Use **pydantic v2** for all model classes, with a shared `StrictModel` base:

```python
model_config = ConfigDict(
    strict=True,              # no silent coercion, e.g. "300" -> 300.0
    extra="forbid",           # unknown keys in a project file fail loudly
    validate_assignment=True, # commands that set fields are validated
    validate_default=True,
)
```

Unions are expressed as discriminated unions on a `kind` literal, which makes
deserialization a declaration rather than a hand-written registry:

```python
Artist = Annotated[LinePlot | ScatterPlot | ErrorbarPlot | ...,
                   Field(discriminator="kind")]
```

Two constraints come with this decision:

1. **The model stays dumb.** Validators check values; they do not compute
   anything and do not call into other subsystems. The renderer and the code
   generator read plain attributes and must not know that pydantic is involved,
   so that replacing it later stays possible.
2. **Load only via `model_validate_json()`**, never `json.loads()` followed by
   `model_validate()`. In strict mode a JSON array arrives as a `list` and is
   rejected by a `tuple` field, so the dict path breaks roundtripping. Reading
   the raw JSON to peek at `schema_version` before migration is fine.

### Consequences

- The roundtrip test is one line per example project.
- Field constraints (`alpha` in [0, 1], `dpi > 0`, figure size in mm positive)
  live on the field and can drive the widget ranges of the generic property
  panel, instead of being defined a second time in the GUI.
- `model_json_schema()` yields a machine-readable specification of the project
  file format, useful for documenting migrations.
- `extra="forbid"` means a file written by a newer figscribe fails with a clear
  error instead of silently losing fields.
- One new runtime dependency: `pydantic>=2.9`.

### Follow-on decisions made during review

**Cross-object checks live outside the model.** Pydantic validates one object at
a time, so it cannot know whether a `ColumnRef` names a source that exists or
whether an `Axes` fits in its grid. `validate_references(project)` returns a
list of issues instead of raising, so the GUI can show all of them at once and
a project file with a dangling reference can still be opened and repaired.
Deliberately not pydantic validators: that would break "the model stays dumb".
A conflict between two fields of one source, such as a CSV decimal separator
that equals the delimiter, is reported there as well, so the file still loads.

**A residual panel is an artist, not a flag.** The brief sketched
`FitCurve.show_residuals`, but a panel is an `Axes` in the grid. A flag would
make the renderer invent an axes, and the code generator would have to reproduce
that invention — the model would no longer be the single source of truth. There
is a `ResidualPlot` artist referring to a `FitCurve` by id instead, placed in an
explicit `Axes`. Turning residuals on is then a command that adds both, and
undo removes them again.

**Commands replace lists, they do not mutate them.** `validate_assignment` only
fires on assignment: `axes.artists.append(x)` bypasses validation entirely, and a
bad value surfaces only when the file is next loaded. Commands therefore assign a
new list (`axes.artists = [*axes.artists, x]`), which also gives undo the old
list to restore.

**Non-finite floats are written as `Infinity` and `NaN`.** Pydantic's default
writes them as `null`, which the strict loader then rejects, so a saved project
could not be reopened. They are realistic, not exotic: `curve_fit` reports `inf`
uncertainties when the covariance cannot be estimated. The cost is that project
files are not strict RFC 8259 JSON when they contain such values; Python's
`json` module and pydantic both read them.

### Alternatives considered

**Stdlib dataclasses.** Zero dependencies, no coercion, and the file format
would be fully visible in our own code — a real argument for a format meant to
be readable in ten years. Rejected because the union dispatch, the recursive
`to_dict`/`from_dict` layer and validation all have to be written by hand. That
layer grows to roughly the size of the model itself and is exactly where a newly
added artist type gets silently forgotten. For a project whose testability rests
on exact roundtrips, that is the wrong place to carry maintenance load.

**attrs + cattrs.** Technically the cleanest option: the model stays plain and
serialization is separated from structure, with discriminated unions supported.
Rejected because it costs two dependencies instead of one, has a smaller
community, and provides no JSON Schema generator — and the separation it buys is
not worth more to us than tooling support.

---

## 0002 — Renderer conventions

**Date:** 2026-10-12
**Status:** accepted

### Context

The renderer serves both the GUI preview and the export, and the code generator
must later reproduce its output exactly. A few choices are not dictated by the
model and have to be the same in both places.

### Decision

- **Data arrives through a `DataProvider`**, a callable from `ColumnRef` to a
  NumPy array. The renderer does not open files; `io/` will supply the provider.
  This keeps the renderer testable with in-memory arrays.
- **No pyplot.** The renderer builds a `matplotlib.figure.Figure` directly, so
  it holds no global state and needs no GUI backend.
- **Every Matplotlib artist carries its model id as `gid`**, so the GUI can map a
  click back to the model. For an errorbar, every part carries it.
- **Axis labels join the unit per `Figure.unit_format`**, default `"U (V)"`; the
  alternatives are `"U / V"` (ISO 80000) and `"U [V]"`. Per figure because
  journals disagree, and a style template will set it. The unit stays plain
  text so it renders upright next to an italic symbol; a compound unit after a
  slash is parenthesised (`v / (m/s)`). `axis_label()` is shared with the code
  generator, which writes the resulting string into the script.
- **Sharing follows `plt.subplots`**: `"col"` joins axes that start in the same
  column, `"row"` those starting in the same row. An axes hides its shared tick
  labels only when a partner below (x) or to its left (y) has exactly the same
  columns (x) or rows (y) and shows them instead; unlike `plt.subplots`, a grid
  with gaps or spans keeps its labels. The code generator writes the resulting
  `tick_params(labelbottom=False)` per axes instead of relying on
  `plt.subplots(sharex=...)`.
- **Exports are byte-stable**: no timestamps in PDF/SVG/PNG metadata, a fixed
  SVG hash salt. Never `bbox_inches="tight"`, which would change the size.

### Consequences

- PDF and SVG have the exact size in mm. PNG is truncated to whole pixels by
  Matplotlib: 85 mm at 300 dpi is 1003 px, not 1003.94. Accepted; the error is
  under one pixel.
- `unit_format` was added to the model with a default, so it needed no schema
  version bump: no project file of version 1 predates it in the wild.
- New runtime dependencies: `matplotlib>=3.8` and `numpy>=1.26`, both named in
  the brief's stack. Pillow, used by the export tests, comes with Matplotlib.

---

## 0003 — Commands and undo/redo

**Date:** 2026-10-16
**Status:** accepted

### Context

The GUI changes the model only through commands, and every change must be
exactly reversible (test 4). Three things make that harder than a list of
closures: undo restores removed objects, so a command recorded earlier may meet
a different Python object with the same id; pydantic validates only on
assignment; and some user actions consist of several changes that must undo as
one.

### Decision

- **Commands address objects by id and a field path**, never by reference. The
  project itself is `None`. `SetField(axes_id, ("x", "label"), "t")`.
- **Four primitives** do all the work: `SetField`, `InsertItem`, `RemoveItem`,
  `MoveItem`. The lists of identified objects (`sources`, `figures`, `axes`,
  `artists`) change only through the last three, which keep ids unique;
  `SetField` refuses them, and `id` itself cannot be set.
- **Assign, never mutate**, as already decided for the model: every primitive
  assigns a new value or a new list, so `validate_assignment` checks it and a
  refused value leaves the model untouched. Values and items are deep-copied on
  the way in, so the model never shares an object with its caller.
- **`Macro` is all or nothing**: if a step fails, the steps already applied are
  reverted before the error propagates. A failed command is not recorded.
- **One exception type**, `CommandError`, also for pydantic's validation
  errors, so the GUI has one thing to catch and show.
- **User-level actions are functions building a `Macro`**, e.g.
  `remove_artist()`. Removing a data artist removes its fits and their
  residuals in the same undo step. An axes left empty stays, and removing an
  axes leaves the grid as it is: changing the layout as a side effect would be
  hard to predict.
- **`History` is plain Python, not `QUndoStack`**, so it is testable without Qt
  and usable by a later non-GUI front end. It tracks the saved state for an
  "unsaved changes" marker.
- **No merging of consecutive commands.** A drag moves the Matplotlib artist
  only temporarily and pushes one `SetField` on release.

### Alternatives considered

**Snapshots** (store `dumps(project)` before every change, undo restores it).
Trivially correct, but memory grows with the project times the history depth,
undo texts need a separate mechanism, and restoring replaces every object, so a
GUI selection held by reference would go stale on every undo.

**`QUndoStack`.** Would give menu integration for free, but ties the model layer
to Qt and makes command tests need a QApplication.

---

## 0004 — Fit models as expressions

**Date:** 2026-10-18
**Status:** accepted

### Context

Fits come in two kinds: predefined models (linear, polynomial, Gaussian,
Lorentzian, exponential) and a user's own expression. Both have to be evaluated
for the fit and the drawn curve, shown in the GUI, and written into the
generated script as readable code without figscribe helpers. A user expression
is untrusted text that ends up being executed.

### Decision

- **Every model is an expression** in one small language, the predefined ones
  included: `gaussian` is `a * exp(-(x - mu)**2 / (2 * sigma**2)) + c`. One
  evaluator serves both kinds, and `numpy_source()` turns any model into the
  NumPy expression the code generator writes into a plain `def`.
- **The language is an allow-list over `ast`**, never `eval`: the operators
  `+ - * / **`, numbers, `x`, the declared parameters, `pi`, and the NumPy
  functions `exp log log10 sqrt sin cos tan arcsin arccos arctan sinh cosh tanh
  abs`, each with exactly one argument. Anything else is refused with its
  position in the text. Numbers are floats, so `9**9**9` overflows to `inf`
  instead of computing a huge integer. Every declared parameter must appear:
  an absent one has no defined uncertainty.
- **Peaks and the exponential carry a constant background `c`**, as real
  measurements almost always do. The Gaussian's width is `sigma`, the
  Lorentzian's `gamma` is its half width at half maximum, and the exponential
  `a * exp(-x / tau) + c` decays for `tau > 0` and grows for `tau < 0`.
- **Start values are stored with the result.** `refit()` guesses them from the
  data for predefined models (1.0 for expressions), lets stored values for the
  model's parameters win, and writes the values actually used into
  `FitCurve.initial_values`. The generated script can then call `curve_fit`
  with the same input and reach the same result, without a guessing routine.
- **Statistics follow `curve_fit`.** With y errors, they weight the points as
  absolute 1-sigma (`absolute_sigma=True`) and the reduced chi-square is
  reported; without, the uncertainties are scaled by the residual scatter and
  there is no chi-square. x errors are ignored: `curve_fit` cannot use them
  (orthogonal distance regression would be a later addition). Non-finite points
  are dropped.
- **Failure is data, misuse is an error.** A fit that does not converge is
  stored with `converged=False` and the start values, and an inestimable
  covariance gives `inf` uncertainties, so the GUI can show both. Too few
  points, non-positive errors, a model not finite at the start values or
  start values that do not match the model raise `FitError`.
- New runtime dependency: `scipy>=1.11`, named in the brief's stack.

### Alternatives considered

**Python functions for the predefined models.** Natural to write, but the code
generator would need a second, textual copy of each, and the two could drift.

**A math parser library** (e.g. `sympy.sympify`). Far more than needed, and
`sympify` itself uses `eval`, which is the risk this decision avoids.

---

## 0005 — GUI structure and the preview

**Date:** 2026-10-18
**Status:** accepted

### Context

The brief requires that the GUI changes the model only through commands and
that the preview is exactly what gets exported. Matplotlib's Qt canvas
(`FigureCanvasQTAgg`) resizes the figure to its widget on every resize, which
changes the figure size and with it the layout: the preview would no longer be
the export.

### Decision

- **A `Document` is the GUI's only path to the model.** It holds the project,
  its file, the `History`, the data provider and the selection. Views push
  commands to it and redraw on its `changed` signal; none of them mutates the
  model. The data provider is rebuilt when the project's sources change.
- **The preview is an image rendered by Agg, not a Qt canvas.** The figure
  keeps its size in millimetres; only the resolution is chosen so that it fits
  the widget, and Agg draws it inside the figure's style context exactly as
  `export` writes a PNG. A test checks that at the export's resolution the
  preview image equals the exported PNG pixel for pixel.
- **Clicks are hit-tested by Matplotlib** (`Artist.contains`) on the rendered
  figure and mapped to the model through the `gid` the renderer sets. Artists
  win over their axes; nothing in the renderer had to change.
- **Errors while drawing are shown in the preview**, never raised: a missing or
  changed data file must not take the window down.
- **PySide6 is a regular dependency**, not an extra: figscribe is a desktop
  application, and `pip install figscribe` gives the `figscribe` command.
- **GUI tests run offscreen** with pytest-qt. Keyboard shortcuts are checked by
  their bindings, not by key presses: the offscreen platform does not reliably
  activate windows, and shortcuts only fire in an active one.

### Alternatives considered

**`FigureCanvasQTAgg` with a fixed widget size.** Rounding the figure to whole
pixels at every zoom level still changes its size in inches slightly, and the
canvas also rescales for the screen's pixel ratio on its own. Fighting the
canvas costs more code than drawing an image.
