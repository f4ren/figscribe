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
