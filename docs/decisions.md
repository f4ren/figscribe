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
