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
`json` module and pydantic both read them. Only fit results may hold them
(`AnyFloat`, since 2026-10-24); every other float refuses them
(`allow_inf_nan=False`), so an infinite width or range cannot get in.

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
- **The history refuses a command that puts a panel outside its grid**
  (since 2026-10-25): `History.push` compares the panels beyond their grid
  before and after the whole command and reverts it if one was added, so a
  macro may grow the grid before moving a panel there, and a panel already
  outside in a project file blocks nothing else. Matplotlib cannot draw such a
  figure at all. Ratios that do not match the grid are only reported: changing
  the number of rows with ratios set has no order of single edits without a
  mismatch in between.
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
- **Every error the GUI shows goes through `gui/errors.explain`** (since
  2026-10-24): figscribe's own errors are written for the user and pass
  unchanged, a file error gives its reason and path, a damaged project file
  where it is damaged; anything else is called a bug, with its type and
  message for a report. Problems figscribe can foresee are caught before
  Matplotlib sees them, such as columns of unequal length, which the renderer
  refuses with both names and lengths and `validate_references` reports when
  given the data.
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

---

## 0006 — The property panel is generated from the model

**Date:** 2026-10-18
**Status:** accepted

### Context

The brief asks for a property panel "generated generically from the model
fields, with specialized editors where it makes sense". Hand-written forms per
class would have to be kept in step with every field added to the model.

### Decision

- **Editors come from the field annotations** at run time: `bool` is a check
  box, a `Literal` a choice, `int` and `float` a line of text parsed on
  `editingFinished`, `X | None` the same editor where empty text means None,
  pairs and lists of numbers comma-separated text, a nested model a group box,
  a `ColumnRef` a choice of the sources' columns, and the fields `color` and
  `edgecolor` text plus a color picker. Text, not spin boxes, for numbers:
  scientific values such as `1e-9` and exact decimals edit without rounding.
- **Numbers are read as people type them** (`gui/numbers.py`, since
  2026-10-24, also in the axis form and the fit dialog): a comma is a decimal
  mark, the minus sign − from text copied out of a PDF is a minus, and spaces
  group thousands, but only before three digits, so that "0.5 1" is refused
  instead of read as 0.51. A comma never groups thousands: "1,500" would mean
  1.5 or 1500 depending on the reader. Lists are separated by ";" when one is
  typed, so their numbers can have decimal commas, else by ",". Infinite
  values are refused; no field the GUI edits means them. Messages quote what
  was typed.
- **The panel speaks the plot's terms, the model keeps Matplotlib's**
  (since 2026-10-24, roadmap U2). `SHOWN` lists fields shown in other numbers
  than stored: rows, columns and header lines count from 1 on screen; a
  scatter plot's marker area (pt², as `scatter` takes it) is shown as its
  size in pt like a line's, so the model and the script need no change.
  Numbers that belong together get a field each (`FieldsEditor`: an image's
  extent as left, right, bottom, top; one ratio per grid column or row). The
  style sheet is chosen from Matplotlib's styles or an `.mplstyle` file;
  colors offer the figure's whole color cycle under its style sheet, the
  colors set lately, and *Same as…* another plot's drawn color. The
  resolution sits in an *Export* section, since only PNG uses it.
- **Each edit is one `SetField`.** Constraints live on the model only; a
  refused value shows pydantic's message above the form and the editor shows
  the model's value again. An unchanged value pushes nothing. The exception
  are style strings (colors, markers, line styles, color maps, legend
  locations, since 2026-10-24; style sheets, since 2026-10-25, where a name
  must be one Matplotlib has and a file must end in `.mplstyle`): the model keeps them as text because
  Matplotlib accepts many forms, and the commands ask Matplotlib whether it
  can draw them (`model/styles.py`), so the property panel, the dialogs and
  the assistant all refuse "blu" with the same plain message. A model
  validator would have made a project file with such a value impossible to
  open and repair, and the model would depend on Matplotlib; a file's own bad
  values are reported by `validate_references` instead.
- **Some fields are deliberately left out**: ids, kinds, item lists (edited in
  the outline), `y_right` (not rendered yet), and fit models, start values,
  results and histogram bins, which get dedicated editors with their features.
  `path`, `sha256` and a fit's `target` are shown read-only. Each of these
  lists says why per field (`SKIPPED`, `READ_ONLY`, `SHOWN_WHEN_SET`), and
  `EDITED_ELSEWHERE` names the classes edited in a place of their own (the
  axis form, the fit dialog, the column choices).
- **No field is forgotten** (since 2026-10-24, `tests/test_field_coverage.py`):
  every field of every model class has a plain name, a docstring the
  assistant reads in the JSON schema (`use_attribute_docstrings`; a constant
  such as a plot's kind is explained by its value), and either an editor
  with a tooltip and, if it can be empty, a text for empty, or one of the
  reasons above. A new field fails the test until it is wired up everywhere.
  Tooltips are looked up by `"Class.field"` before the field name, because a
  name can mean different things (a plot's `label` is its legend entry, a
  color bar's the text beside it), and nested fields get them too.
- **Editors are bound to their object.** An editor torn down by a selection
  change can still report its last input; it is ignored instead of being
  applied to the newly selected object. Undo and redo refresh the values in
  place, so editing does not lose focus.

---

## 0007 — Importing data in the GUI

**Date:** 2026-10-18
**Status:** accepted

### Decision

- **The import dialog proposes how to read a file** and previews the result
  live: the delimiter is the candidate found in the most lines (tab, then
  semicolon, then comma on a tie), a decimal comma is assumed next to a
  semicolon or tab when digits are split by commas, the header is the first
  line after the comment block, and lines between it and the first line of
  numbers (typically units) are skipped. `csv.Sniffer` was tried and dropped:
  it gives up as soon as the header and the data differ in width. A header
  wider than the data, or options that do not parse, disable OK.
- **Files of an unsaved project are stored with their absolute path.** A
  relative path needs the project's directory, which does not exist before
  the first save. Once saved, newly imported files below the project's
  directory are stored relative to it.
- **A data file that changed or moved is fixed from a bar above the preview**
  (added 2026-10-24), one row per file: *Use the new version* hashes it again
  and reads its columns and rows the way it is read now; *Locate file…* does
  the same from where a missing file went, stored relative to the project
  when below it; *Show what changed* compares rows and columns. Each is one
  undo step. A version that does not parse is refused before anything
  changes. The document hashes a file again only when its size or time stamp
  changed, so the check runs after every edit and when the window comes to
  the front. Plots of columns the new version lacks are listed in the bar and
  in the problem list (`validate_references` checks named columns against
  `columns`); the change is made anyway, since it can be undone and the plots
  can be pointed at other columns. The number of data rows is recorded on
  import (`row_count`) so that a change can be told in rows; projects from
  before have none. The assistant gets *Use the new version* as a tool, not
  *Locate*: it must not point a source at other files on the machine.
- **Changing how a file is read reads it at once** (added 2026-10-25): a new
  separator, decimal mark, header line, number of skipped lines, comment mark,
  encoding or array, from the property panel or the assistant, is one undo
  step that also takes the columns and rows the file then has, or is refused
  with the reader's reason if the file cannot be read that way. A file that
  changed since import is refused too: reading it again would take the new
  version without the bar's question.
- **Adding the first plot to a figure without axes adds the axes too**, in the
  same undo step. Later plots go into the selected axes, the axes of the
  selected plot, or the figure's first axes.
- **Columns without names are offered by number**; the file is read once to
  count them.
- **The text encoding is part of the source** (`CsvSource.encoding`, added
  2026-10-24): UTF-8 (with or without Excel's byte order mark), cp1252 or
  Latin-1. The dialog takes the first that decodes the whole file, in that
  order, and offers the others. The two differ only in bytes 0x80–0x9F,
  where cp1252 has €, quotes and dashes and Latin-1 control characters;
  cp1252 comes first because Windows lab software writes it. A guesser such
  as `chardet` was not added: a dependency for three candidates. The script
  passes `encoding=` to `np.loadtxt` for anything but UTF-8. A file that does
  not decode gives a `DataError` naming the file and the option. No schema
  version bump: the field has a default, and no released file predates it.

---

## 0008 — Assistant tools, served over MCP

**Date:** 2026-10-19
**Status:** accepted

### Context

The brief lists natural-language input as optional after the MVP: an LLM
that produces commands against the model, not code, so that everything stays
traceable and undoable. Which model to use is the user's choice, and figscribe
should not need an API key or carry the cost of one.

### Decision

- **One tool layer, `figscribe.tools`, independent of Qt and of any LLM
  provider.** It reads the project (`get_project`, `get_schema`, whose fields
  carry their docstrings as descriptions,
  `list_columns`, `render_preview`) and changes it only through commands
  (`set_field`, `insert`, `remove`, `move`, `fit`, `undo`), each one undo step;
  `apply_changes` runs several operations as one step, all or nothing.
- **Inputs are validated strictly from JSON** against the model's field types,
  as a project file is loaded: `"300"` is not a number, lists become tuples,
  unknown fields are refused. A refusal returns the model's message, so the
  assistant can correct itself; nothing is changed.
- **No data leaves through the tools by default.** `get_project` drops file
  locations (only file names remain) and hashes; the project holds no
  measurements. `render_preview` shows the data, so it works only when the
  user allows it in the workspace.
- **Data files are not imported by tools.** That would let an assistant open
  any path on the machine; importing stays a user action. For the same reason
  a source's `path`, `sha256` and `columns` cannot be set by a tool; how the
  file is read (delimiter, header, comment) can.
- **Tool arguments are validated by the tool's signature** before anything
  runs, in single calls and in each operation of `apply_changes` alike: a
  path given as a string or an index as text is refused with a message, not
  half-interpreted. A missing or changed data file is a refusal too, never an
  internal error.
- **MCP is the first front end** (the next change): any MCP client and model
  can drive figscribe, with no key or cost inside the application. A built-in
  chat may follow, using the same tool definitions (`figscribe.tools.TOOLS`).

### Alternatives considered

**A built-in chat on one provider's API first.** Ties figscribe to that
provider, its key handling and its cost; MCP leaves the choice to the user.

---

## 0009 — How MCP clients reach the running application

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **`figscribe mcp` is a small MCP server on stdio**, started by the client:
  every MCP client supports stdio, and setting it up is one line naming the
  command. It holds no project state and imports no Qt; it lists the tools
  from `figscribe.tools.TOOLS` and forwards each call to the application.
- **The application listens on 127.0.0.1 at a free port** and writes the port
  and a random token to `mcp-endpoint.json` in the user's state directory,
  readable by the user only. Requests without the token are refused. TCP on
  localhost behaves the same on every platform; a `QLocalServer` would be a
  named pipe on Windows, which a Qt-free process reaches only with
  platform-specific code.
- **Requests run on the GUI thread**, through the Toolbox of the open
  Document: changes are commands on its history, appear at once and are
  undone like any other. A failing tool or a bug returns an error to the
  client and never takes the window down.
- **Off by default.** "Assistant > Allow MCP access" starts listening, and so
  does "Let it see the figure" for `render_preview`; both are remembered.
  Closing the window or switching access off removes the endpoint file.
- **One line of JSON per request and per answer.** Binary data (the preview)
  travels as base64 and leaves `figscribe mcp` as MCP image content.
- **`figscribe mcp` never fails a call by raising.** No endpoint file, a stale
  one, a refused or dropped connection, a malformed answer, or no answer
  within 120 s all become an error result the client shows to the model.
- **`figscribe mcp` starts light.** It needs only the tool list, so
  `figscribe.tools` loads the parts that pull in matplotlib and SciPy on first
  use; a test keeps it that way.

## 0010 — The look of the workspace

**Date:** 2026-10-19
**Status:** accepted

### Context

The first GUI used Qt's default widgets: docks with title bars, a plain tree,
a long form of model field names. It worked, but looked dated and asked the
user to know the model ("zorder", "elinewidth", "Axes (row 0, col 0)").

### Decision

- **Qt Widgets with one style sheet, not QML.** Everything visual lives in
  `gui/theme.py`: a light ground, white panels, one blue accent, line icons as
  inline SVG. The views keep their structure and tests.
- **IBM Plex Sans and Mono are bundled** (SIL Open Font License, the licence
  next to the files) as TrueType, so the application looks the same on every
  platform; WOFF2 is not loaded by every Qt build.
- **Plain words on screen.** `gui/names.py` maps fields and kinds to names
  ("Marker size (pt)", "Error bar plot", "Panel A · top"); the model keeps its
  names. Values with an error are rounded to the error's two significant digits.
- **The contents panel reads like the figure**: panels with their plots, each
  plot in the color it is drawn in, an eye to hide it, χ²ᵣ next to fits, and
  the data files with their columns.
- **The property panel groups fields** into Data, Look, Legend and the like,
  with "More" folded. Colors get swatches of the color cycle, markers get
  buttons, line styles and legend locations get named choices; text entry
  stays for anything else.
- **The preview is a sheet of paper** on the ground, captioned with its size
  and resolution, and it says what to do when the figure is empty.
- **Panels are fixed**, without title bars; the problem list appears only
  when there are problems. Files dropped on the window are opened or added.

## 0011 — The start page

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **figscribe starts on a start page when no file is given**: drop a data
  file (or a project), pick a layout, open the example, or go back to a
  recent project. "File > Start Page" and the mark in the toolbar return to
  it; the open project stays until something replaces it.
- **Layouts are templates in `figscribe.templates`**, independent of the GUI:
  each builds a Figure with its size in millimetres and empty panels (single
  and double column, data with residuals, side by side, a 16:9 slide).
- **The example opens as a copy** in "Documents/figscribe examples", so it
  can be changed and saved; the wheel carries it inside the package.
- **Recent projects** are those opened or saved in the window, kept in the
  user's settings, at most six; files that are gone are not shown.

## 0012 — Adding data proposes a first plot

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **The import dialog says what it detected** as a row of chips (separator,
  decimal mark, line of names, line of units, comments); a click on one opens
  the settings. Lines are counted from 1 on screen, from 0 in the model.
- **Guesses live in `figscribe.suggest`**, without Qt: a column named "dU",
  "U_err", "sigma_U" or "ΔU" next to "U" is U's error; a non-numeric line
  right below the header is a line of units; the first column that is nobody's
  error is x, the next one y.
- **"Add and plot" is the default**: the data, the chosen plot (error bars
  first when y has an error column) and, for an empty panel, axis labels and
  units from the columns, all as one undo step. "Only add the data" and
  "Choose columns myself…" remain.
- Units are read only to name the axes; the model keeps them on the axes, not
  on the data source.

## 0013 — Fits in the figure and the fit dialog

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **The renderer draws fits and residuals.** A fit is its model evaluated at
  400 points across the range of its data's x, drawn only once it has a
  result; residuals are data minus fit at every data point, with the data's
  y errors, around a dashed zero line. Both find the plots they refer to
  anywhere in the figure; a missing one is an error, not a silent gap.
- **The fit dialog fits at once** on every change of model or start value,
  without touching the project, and shows the result the way the property
  panel does. Own formulas take their parameters from the names in them
  (`free_names`): everything but x, the functions and pi.
- **`add_fit` adds the fit and, if asked, its residuals in one step.** The
  residuals use an empty panel right below the data if there is one;
  otherwise a row is added, the figure grows by 20 mm and shares x by
  column. The x label moves to the residual panel, which now shows the x
  tick labels.
- **"Fit again with the current data"** in the property panel reruns a fit
  with its stored start values, e.g. after the data file changed.

## 0014 — The code generator

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **One script per figure, written with pyplot**, as a person would: a
  docstring with size, versions and the data's SHA-256; imports; data; fit
  models; fits; the figure with one block per panel (`ax_a`, `ax_b` like the
  GUI's "Panel A", "Panel B"); saving. No figscribe helpers, no figscribe
  import.
- **The same Matplotlib calls as the renderer.** Arguments that only repeat
  Matplotlib's default are left out; those the renderer sets explicitly and a
  style sheet could change (line widths, marker sizes, legend location) are
  kept. Decisions both need, such as axis labels with units and which shared
  axes hide their tick labels, live in shared functions
  (`render.labels`, `render.layout`) and are computed at generation time.
- **Data paths are relative to the script** (`HERE / "scan.csv"`), and the
  script refuses a data file whose hash changed, with a comment saying how to
  drop the check. Only the columns the figure uses are loaded
  (`np.loadtxt(..., usecols=..., unpack=True)`).
- **Fits are recomputed** with `curve_fit` from the stored start values, with
  the same weighting, and their parameters are printed; non-finite points are
  filtered only where the data has them.
- **The equivalence test is the contract**: the renderer's PNG and the PNG of
  the script, run in a separate process, must be identical pixel for pixel,
  for the examples and for projects that exercise every supported setting.
  Every new model feature needs its code here and a case there.
- Available from *File > Export Python Script…*, `figscribe script`, and the
  `get_python_script` tool for assistants.

## 0015 — Adding panels, insets and the context menu

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **`add_panel(project, axes_id, side)`** puts an empty panel to the right,
  left, above or below a panel: into free cells of the grid if there are,
  otherwise a column or row is inserted there, the panels behind it move along
  and those spanning across it grow; width or height ratios get the
  neighbour's value. The figure keeps its size: a journal's column width is
  fixed, and the user decides about the height.
- **An inset is an Axes with `inset = {parent, bounds}`**: placed inside its
  parent panel at (left, bottom, width, height) in the parent's fractions,
  outside the grid, never sharing axes. The renderer and the generated script
  make grid panels first and insets after (`parent.inset_axes(bounds)`).
  Removing a panel removes its insets.
- **The contents panel has a context menu**: panels get "Add panel to the
  right / left / above / below", "Add inset" and "Delete panel"; plots "Hide"
  or "Show" and "Delete"; an empty figure "Add a panel". The same choices are
  under Insert > Add Panel and the toolbar's "Panel" button, acting on the
  selected panel or that of the selected plot.
- **The position is visible**: a "Position" section (row, column, spans) for
  grid panels, an "Inset" section (inside which panel, bounds) for insets.
- Assistants get an `add_panel` tool with the same rules.

## 0016 — Font sizes, tick spacing and grid options

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **One base font size per figure** (`Figure.font_size`, pt), applied like a
  style sheet while the figure is drawn; journals ask for one size, and
  Matplotlib's relative sizes (a larger title) follow it. The script sets
  `plt.rcParams["font.size"]`.
- **Overrides where people actually change them**: `Axes.title_size`,
  `AxisSpec.label_size` and `AxisSpec.tick_size`. Unset sizes are not passed
  to Matplotlib at all: `fontsize=None` would reset a title to the base size.
- **Ticks by spacing**: `AxisSpec.major_step` (a MultipleLocator; explicit
  `ticks` win) and `AxisSpec.minor_divisions` (AutoMinorLocator, at least 2).
- **Grid options**: `Axes.grid_axis` (both, x, y) and `Axes.grid_which`
  (major, minor, both), used when `grid` is on; `grid` stays a switch so old
  files load unchanged.

## 0017 — Zoom, pan and dragging the legend

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **The wheel zooms the panel under the cursor** (Shift: x only, Ctrl or Alt:
  y only), keeping the point under the cursor in place; **dragging a panel's
  background pans it**. Both work in display coordinates through the axes'
  own transform, so log and symlog axes zoom in their own scale.
- **That view is the preview's, not the model's.** The export keeps the set
  ranges; a bar over the preview says so and offers "Use as axis range"
  (writes x and y limits of every zoomed panel as one undo step) and "Reset"
  (also Escape). The caption changes while zoomed, so the promise "exactly as
  exported" is never silently broken.
- **Dragging a legend moves it**: on release its lower-left corner gets a
  fixed place in the panel (`Legend.position`, Matplotlib's
  `bbox_to_anchor` with `loc="lower left"`, minus `borderaxespad`), one undo
  step. The legend carries its panel's id, so a click on it selects the panel
  whose legend settings it has.
- A press selects only on release without movement, so a drag never changes
  the selection.
- **Zooming and panning reuse the drawn figure** (since 2026-10-24): each
  step sets the new range on it at once and draws it with the panels where
  they are, merged with the steps queued behind it into one draw; 300 ms
  after the last step the view is rendered again from the model. Measured on
  the example: 150 ms per step before, 49 ms now. Rendering at rest is needed
  because Matplotlib's layout moves a figure with a color bar by a few pixels
  when it lays it out a second time, so only a new render matches the export;
  a test checks that. A tick step that no longer fits the new range, or fits
  again, renders at once. `render()` takes the view, so ticks are fitted to
  the range shown, not the model's.

## 0018 — The Python code drawer

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **View > Python Code** (and the toolbar's "Python code") opens a drawer
  under the preview with the script *Export Python Script…* would write,
  highlighted, with "Copy" and "Save as .py…". It follows every change after
  a short pause and costs nothing while closed. A project the generator
  cannot handle yet shows the reason as a comment instead of code.
- Whether the drawer is open is remembered, like the assistant switches.

## 0019 — The built-in assistant

**Date:** 2026-10-19
**Status:** accepted

### Decision

- **The same tools as for MCP clients** (`figscribe.tools`), run through the
  open Document's Toolbox: every change is a command, shown at once and
  undoable. `figscribe.assistant.chat` holds the conversation and the tool
  loop without Qt; the GUI runs model requests in a worker thread and the
  tools on its own thread, one request round at a time.
- **Claude through the official Anthropic SDK** (optional extra
  `figscribe[chat]`), model `claude-opus-5-5` with effort `medium`, streamed,
  tool inputs streamed eagerly and validated by the Toolbox; the stable system
  prompt and tool list are cached. A safety decline is answered by a fallback
  model (`fallbacks: "default"`), so the user gets an answer instead of
  nothing. Thinking blocks and every other block of a response go back
  unchanged on the next request.
- **Credentials are the SDK's**: `ANTHROPIC_API_KEY` or an `ant auth login`
  profile. When neither works, the chat asks for a key and keeps it for the
  session only; it is never written to the settings.
- **Bounded**: at most 25 tool rounds per request; a refusal, a cut-off answer
  or an API error ends the request with a message, never an exception in the
  window. The model sees column names, not data, unless the user lets tools
  return the preview image.
- Tests drive the loop with a scripted model, and the real SDK path against a
  local server, so they need neither network nor key.

## 0020 — Histograms and notes

**Date:** 2026-10-20
**Status:** accepted

### Decision

- **Histograms** draw the finite values of their column (NaN and inf are
  left out, as in a fit; the script filters only where the data has them),
  with a bin count or explicit edges, density and style. A file with a single
  column suggests a histogram on import, with "Count" on the y axis; the plot
  dialog offers "Histogram"; the property panel takes "20" or "0, 1, 2.5" as
  bins.
- **Notes** are `Annotation`s drawn with `ax.annotate`: text at a position in
  data or axes coordinates, and with `arrow_to` an arrow from the text to
  that point. Unset font size and colour are not passed, like other text.
  *Insert > Add Note…* and the panel's context menu put a note in the middle
  of the panel; dragging it in the preview moves its text (the arrow keeps
  its tip), one undo step, in the coordinates it is placed in.
- The script sets z-orders only where they differ from Matplotlib's own per
  kind (1 for scatter and histogram patches, 3 for text, 2 otherwise).

## 0021 — The right y axis

**Date:** 2026-10-20
**Status:** accepted

### Decision

- **`Axes.y_right` is drawn with `ax.twinx()`**, with all the settings of an
  axis; plots with `axis="right"` are drawn against it, the others against
  the left one. Without a right axis, a plot meant for it is drawn against
  the left one and validate_references reports it.
- **One legend for both axes**: the panel's legend lists the plots of both,
  left first; the script collects the handles the same way.
- **Each axis has its own colour cycle**, as in Matplotlib: the first plot on
  the right is blue again. The contents panel shows it that way.
- **In the GUI**, a panel's "Right y axis" switch adds the axis or removes it
  (its plots go back to the left, one undo step); choosing "right" for a plot
  creates the axis if the panel has none. A fit is drawn against the axis of
  its data.

## 0022 — 2-D data: NumPy files, images, color meshes, color bars

**Date:** 2026-10-20
**Status:** accepted

### Decision

- **NumPy files** (`.npy`, `.npz`) are sources like CSV files: hashed on
  import and checked before every read. They are read with
  `np.load(..., allow_pickle=False)`, so a data file can never run code, and
  converted to floats; arrays with more than two dimensions are refused. An
  `.npz` source names one array; an `ArrayRef.key` may pick another from the
  same file. A 1-D array is one column, a 2-D array's columns are columns, so
  every plot kind can use them.
- **An `ArrayRef` is the whole 2-D data**: a NumPy array, or a CSV file's
  whole table. Images use `ax.imshow` (`origin` and `aspect` settable,
  `extent` optional), color meshes `ax.pcolormesh(shading="auto")` with
  optional cell coordinates from columns. Both scale linearly (with optional
  `vmin`/`vmax`) or logarithmically with `LogNorm`.
- **A color bar** is an optional part of the plot, drawn with
  `fig.colorbar(mappable, ax=ax)`. Its Matplotlib axes carries the plot's id,
  so clicking it selects the plot; zoom and pan never act on it.
- **In the GUI**, importing a file with a 2-D array (in an `.npz` file the
  first 2-D one) draws it at once as an image with a color bar, one undo
  step; a 1-D file is only added. The plot dialog offers "Image" and "Color
  mesh" once there is 2-D data. The property panel picks the data from a
  list, switches the color bar on and off like the right y axis, and offers
  common color maps while keeping any other Matplotlib name.
- The script loads NumPy data with `np.load(path)[key].astype(float)`
  (without the key for `.npy`), names its variables after the arrays, and
  mirrors `imshow`/`pcolormesh`/`colorbar`; the equivalence test covers
  images, meshes, log scaling and color bars.

## 0023 — The chat talks to Claude, ChatGPT or a local model

**Date:** 2026-10-20
**Status:** accepted

### Context

The built-in chat was tied to Claude. Its task is narrow (calling ~13 tools
whose every input figscribe validates), so smaller and local models may do,
and a local model keeps even file and column names on the computer.

### Decision

- **The conversation is provider-neutral**: user text, `Reply` (text, tool
  calls, a stop reason, the provider's own record) and lists of `ToolResult`.
  Each `Model` translates it to its API; the tool loop, limits and error
  handling are shared.
- **Two kinds of provider**: Claude through the Anthropic SDK (as before:
  streaming, eager tool input, the server-side refusal fallback where the
  model takes it), and **everything else through the OpenAI-compatible chat
  completions API** with the `openai` SDK: ChatGPT, LM Studio, Ollama, vLLM,
  llama.cpp. One adapter covers them all; the Responses API and provider
  specifics (reasoning effort, token limits) are left out because local
  servers do not share them.
- **Robust to weaker models**: tool arguments that are not a JSON object are
  answered with an error result instead of failing the request; streamed tool
  calls are assembled from their pieces, with ids made up where a server sends
  none. A model marked as not reading images is not offered `render_preview`;
  one that does gets the picture as a user message after the tool result,
  since tool messages carry text only.
- **Settings**: *Assistant > Choose Model…* (or the model button in the chat)
  picks provider, server (presets for ChatGPT, LM Studio, Ollama, or any URL)
  and model, which can be listed from the server. The window remembers them;
  API keys are never stored. Claude stays the default with Claude Opus 5.5;
  Sonnet and Haiku are offered.
- The `chat` extra installs both SDKs.

### Alternatives

- LiteLLM or a similar abstraction: one more large dependency for two
  adapters.
- Only MCP: LM Studio and others can already use `figscribe mcp`, but a chat
  inside the window needs no second application.

## 0024 — Measuring models: `figscribe bench`

**Date:** 2026-10-20
**Status:** accepted

### Context

Whether a local model is good enough for the chat cannot be argued, only
measured, and only on figscribe's own tasks.

### Decision

- **21 cases** in `assistant/bench.py`, from easy (one field: a label, a
  range, a colour) through medium (two changes, a new plot, a fit, a note, a
  right axis, a histogram panel) to hard (a shared-x panel below, a journal
  layout, an inset zoomed in, a fit with residuals). One request is German.
- Each case starts from the bundled example project in a `ProjectWorkspace`
  (no window, files only read), runs the chat's own tool loop, and is judged
  by a **check of the resulting project** that tolerates equivalent answers
  (any red colour, a dragged or a named legend corner, either kind of
  Gaussian model). A chat error counts as a failure.
- **Every check is tested**: it must fail on the untouched project and pass
  after the case's reference solution, a function that calls the tools.
- The table shows passes per level, time, tool rounds and refused tool calls;
  `--json` keeps the results for comparing models.
- **Help for smaller models** where it costs nothing: the system prompt lists
  the common field paths (a test keeps them valid), and the `fit` tool takes
  `residuals: true` to add the residual panel as the GUI does, instead of
  four separate steps.

## 0025 — Tick style, log minor ticks and SI prefixes

**Date:** 2026-10-20
**Status:** accepted

### Context

A spectrum as journals print it could not be made: ticks inward on all four
sides were missing, minor ticks vanished on log axes, and a frequency axis in
Hz could not be shown in kHz.

### Decision

- **Tick style per figure** (`tick_direction`: in, out, inout or the style's
  default; `ticks_all_sides`), because it is a house style rather than a
  property of one panel. It goes into the rcParams while the figure is
  built, so insets and right axes follow; the script sets the same rcParams
  at its top.
- **Log axes with a fixed major step** get their minor ticks from
  `MultipleLocator(step / divisions)`, since AutoMinorLocator refuses log
  scales, and plain numbers (`1350`, not `1.35×10³`); minor tick labels are
  switched off there.
- **`AxisSpec.prefix`** (p … T) divides the shown numbers by the power of
  ten and puts the prefix before the unit (`Hz` → `kHz`; without a unit the
  label gets `×10³`). Data, limits, ticks and steps stay in the data's unit,
  so fits and files are untouched. The script uses a `FuncFormatter` with
  the same arithmetic, written as `v / 1e3` or `v * 1e3`.
- The decisions live in `render/ticks.py`, used by renderer and generator
  alike; the equivalence test covers them.

### Alternatives

- `EngFormatter` (a prefix at every tick, "50 kHz"): for data sheets more
  than for journals; may come later as an option.
- Scaling the data instead: would change fit parameters and residuals.

## 0026 — An axis has its own form

**Date:** 2026-10-20
**Status:** accepted

### Context

A panel's form listed every field of the panel and of both axes, named as in
the model (`major_step`, `minor_divisions`, `limits` as one pair). Setting up
an axis meant knowing the model: four minor ticks had to be entered as five
divisions, and a range in kHz in Hz.

### Decision

- **An axis is selectable** with the id `<panel id>/x`, `/y` or `/y_right`:
  by clicking its numbers, its label or the strip along its edge in the
  preview, or from the panel's form, which now shows one line per axis
  ("t (s) · linear · automatic range ›") instead of their fields. The outline
  shows the panel's row; Delete does nothing for an axis.
- **The axis form** (`gui/axisform.py`) is written by hand, not generated:
  Label (text, unit, *show values in* with the resulting units), Range (scale,
  from … to with the current range in grey, the symlog threshold only for
  symlog), Major ticks (automatically / every … / at these values, with
  labels), Minor ticks (none / automatically / *n* between majors, stored as
  n + 1 divisions), Text size. Each change is one undo step, "Change the x
  axis".
- **Numbers are typed in the shown unit**: with values shown in kHz, ranges,
  steps and tick values are entered in kHz and stored in Hz. An empty end of a
  range keeps the one drawn now.
- Fields in the generated forms get explanations as tooltips, and LaTeX in
  summaries is shown as plain text (`$\Delta t$` as Δ t).

### Alternatives

- Better names in the generated form only: would keep pairs like `limits`
  and the divisions-versus-ticks confusion, which need a different input.

---

## 0027 — A limit on tick counts

**Date:** 2026-10-24
**Status:** accepted

### Context

A tick step that is small for the range, such as every 1 from 0 to 10 000,
makes Matplotlib place every one of those ticks: it only warns about counts
above `Locator.MAXTICKS`. Each tick costs about 3 ms per redraw (minor ticks
about 1.4 ms), and the automatic minor ticks multiply the count by five, so
that example took minutes. The preview redraws on every change, so the window
froze, and a project file with such a step could not be opened usefully.

### Decision

- **At most 50 major and 250 minor ticks per axis**, counted within the range
  the axis shows (`render/ticks.py`, `too_many_ticks`). 50 ticks on a 175 mm
  double-column axis are 3.5 mm apart, closer than tick numbers fit; 250 minor
  ticks are 0.7 mm apart, beyond which they merge into a grey band. Together
  they cost about half a second per axis. Only the step and the divisions set
  in the model are counted: Matplotlib's own choices stay few, and explicit
  tick values are taken as given.
- **The renderer falls back to automatic ticks** for whatever exceeds the
  limit: first the step, then the divisions (`ticks_that_fit`). This needs the
  range, and an automatic range is only known once the data are drawn, so the
  step and minor ticks are now set after all panels are drawn. With a style
  that rounds automatic ranges to the ticks (`axes.autolimit_mode:
  round_numbers`, e.g. `classic`), the range is worked out again afterwards,
  as the script does when it draws.
- **The code generator leaves out the same settings.** For an automatic range
  it draws the figure to learn the range (`tick_ranges`), only when an axis
  has a step or divisions and no fixed range, and only when it has the data.
  `figscribe script` and the assistant's script tool now pass the data; when
  the data cannot be read, the command line writes the script without them,
  steps included as set.
- **Where the change is made, it is refused**: the axis form shows the reason
  and keeps what was typed; the assistant tools refuse a change that would add
  such a problem, with the reason, and change nothing. A problem already in
  the project does not block other changes.
- **`validate_references` reports it** for a fixed range. It has no data, so
  an automatic range is not checked there; the renderer falls back anyway.

### Consequences

- A project file with a too small step opens and draws at normal speed; the
  problem list says why its ticks are automatic.
- The script and the preview agree, except at the edge of the limit under a
  `round_numbers` style, where the range the code generator reads after
  drawing can be one step wider than the one the renderer counted over.

### Alternatives

- **Limit the model fields** (e.g. `minor_divisions <= 20`): cannot express a
  limit that depends on the range, and would refuse to load older files.
- **Only refuse in the GUI**: a loaded file or an assistant edit would still
  freeze the window.
- **Count major ticks only**, as first planned: the default minor ticks alone
  made the repro five times slower than the major ones.

---

## 0028 — Tests run in parallel with pytest-xdist

**Date:** 2026-10-25
**Status:** accepted

### Context

The tests that operate every field and action of the GUI (roadmap task B8)
draw the whole figure after each change: about two and a half minutes on a
laptop, nine on a CI runner, against half a minute for everything else. Run
on one job only, they still made every pull request wait about ten minutes.

### Decision

- **`pytest-xdist` is a dev dependency**, and CI runs the tests with
  `-n auto --dist worksteal`: idle workers take tests from busy ones, which
  matters because a few tests take far longer than the rest. Locally the
  whole suite drops from about 2.5 minutes to under one.
- **The slow tests are split so they can spread**: one test per object for
  the fields, per menu for the actions, per panel for the outline's menus.
  A list is tried for at most six other entries, as a person would.
- **The slow tests still run on one CI job** (Ubuntu, Python 3.13); they test
  figscribe's logic, which does not differ by platform, while crashes such as
  that of B8.1 have their own fast tests that run everywhere.

### Alternatives considered

**Rendering less in the tests**, such as without the layout engine: saves
about a third, and the layout settings could then no longer be tested.
**Fewer objects in the test project**: the point of the project is to have
every kind. **Running the slow tests nightly** instead of per pull request:
a problem would then reach `develop` before anyone sees it.

---

## 0029 — Fit parameters held fixed or kept within bounds

**Date:** 2026-10-25
**Status:** accepted

### Context

A fit could only vary every parameter of its model. Scientists hold some at
a known value (a background, a line width from the instrument) and keep
others physical (a width above zero), and the generated script has to give
the same result.

### Decision

- **`FitCurve.fixed`** lists parameters held at their start value, and
  **`FitCurve.parameter_bounds`** gives others a (lower, upper) range with
  None for an open end. Not `bounds`: the property panel lists fields by name,
  and an inset already has `bounds`.
- **A held parameter is not fitted at all**: curve_fit sees a function of
  the free parameters only. Its uncertainty is 0, it is shown as "held", and
  it does not count as a degree of freedom in χ²ᵣ. The script defines that
  function by name (`gaussian_held`), with a comment saying what is held.
- **Bounds go to `curve_fit(bounds=...)`**, which then uses its bounded
  method ("trf") instead of Levenberg–Marquardt; without bounds nothing
  changes, so existing fits give the same numbers.
- **A fit range** (`fit_range`, added 2026-10-26) fits only the points with
  x within it; the curve is drawn over the range where there is data, or
  across all the data with `extend_curve`, and the residuals show the
  fitted points only. A range is a property of the fit, not of the plot:
  another fit of the same data may need another range.
- **A start value outside its bounds is refused** if the user gave it, and
  moved in if it was guessed from the data: the user never saw that guess.
  So are every parameter held, a lower bound not below the upper, and names
  the model does not have; `validate_references` reports such names in a
  project file.

### Alternatives considered

**Equal lower and upper bounds for a held parameter**: curve_fit refuses
them, and nearly equal ones distort the covariance. **A held parameter as a
literal in the model's expression**: the script would no longer show the
model as it is named, and freeing the parameter again would need a new
expression.

---

## 0030 — The application icon

**Date:** 2026-10-25
**Status:** accepted

### Context

figscribe had no icon: the window showed the platform's default and the macOS
Dock Python's rocket. The installers of roadmap task R4.2 will need `.icns`
for macOS and `.ico` for Windows.

### Decision

- **A pen writing a figure**: a gold nib drawing the Gaussian of the start
  page's mark in white, on the accent blue, with faint axes. The name is
  figure and scribe, and the icon shows both without letters: figscribe
  writes the figure down, as a script.
- **Two SVG drawings in `gui/icons`, every size made from them.** The full one
  follows the macOS grid (824 of 1024 px with a margin). Up to 48 px
  `figscribe-small.svg` is used instead: the whole square, no axes, a bolder
  curve and a larger pen, which stays recognisable down to 32 px.
- **`theme.apply` sets the window icon**, rendered once per size from 16 to
  1024 px, so the Dock and taskbar show it also when figscribe runs from a
  Python environment rather than an installer.
- **`packaging/make_icons.py` writes `.icns`, `.ico` and a 1024 px PNG** to
  `packaging/icons`, with Qt's SVG renderer and Pillow, which Matplotlib
  already depends on; no new dependency. The files are committed so R4.2 can
  use them as they are; the script is rerun after a change to the drawing.
  The `.icns` uses the full drawing at every size, as macOS icons keep their
  margin even in lists; the `.ico` uses the small one up to 48 px, as the
  window icon does. Pillow writes no 16 and 32 px entries without Retina
  scale into `.icns`; macOS scales them from 32 and 64 px.

### Alternatives considered

**Data points with the fit through them** (the first draft): a scientific
figure, but nothing of the "scribe". **A speech bubble** at the plot: reads
as a chat application and puts the assistant first, which is an extra; the
toolbar already uses it for the chat. **A plot over lines of code**: says
exactly what figscribe does, but looks like a document and is hard to read
at 16 px. **Letters ("fs")**: need a font in the drawing and say less.
**One drawing for every size**: at 16 px the margin leaves a blue speck. **Making the platform files at
release time only**: the installers would then depend on Qt being able to
render in CI before anyone has seen the result.

---

## 0031 — Points left out of a plot

**Date:** 2026-10-26
**Status:** accepted

### Context

Outliers and detector glitches must stay out of a fit, but a paper must not
hide that they were there, and the data file must stay as measured.

### Decision

- **Rows left out are stored on the plot** (`left_out`, counted from 0), so
  every fit of it skips them; a fit range stays a property of the fit.
- **They are drawn apart, in light grey by default**, with their error bars
  and without a legend entry; color and marker can be set
  (`left_out_color`, `left_out_marker`: "same" as the plot by default, None
  for no marker). An explicit color leaves the color cycle alone, so the
  other plots keep their colors.
- **A line runs on through them** (asked for by the user): the kept rows are
  drawn with NaN at the left-out ones, so the line breaks there, and the
  steps to and from each left-out row are drawn in its color and
  `left_out_linestyle` ("same" as the plot, "none" for a gap). Joining the
  kept points across them, as at first, hid where the line was measured.
- **Leaving out or taking back fits the plot's fits again** in the same undo
  step, and is refused if a fit would have too few points; a row the data
  lacks is reported by `validate_references`.
- **The script keeps the file as it is** and names a mask, `kept`, with a
  comment listing the rows as they are counted on screen.
- **Outliers found automatically are proposed, not applied** (decided with
  the user): points beyond k·σ of the fit without them, σ being the error
  bar or 1.4826 × the median absolute deviation, fitted again until the set
  settles. Once confirmed they join the same list, and `left_out_note` says
  how they were found; the note is the user's to edit.

---

## 0032 — Gemini as a server by name, and its own key

**Date:** 2026-10-26
**Status:** accepted

### Context

The user asked whether the assistant works with a subscription or a free
model. A Claude or ChatGPT subscription gives no API access, and Anthropic's
terms limit its sign-in to Claude.ai and Claude Code. Free models were
already possible locally (LM Studio, Ollama); of the hosted APIs, Google's
Gemini API has a free tier and an OpenAI-compatible endpoint
(`https://generativelanguage.googleapis.com/v1beta/openai/`, still marked
beta by Google), with tools, streaming, images and a model list.

### Decision

- **"Google Gemini" is offered by name** next to ChatGPT, through the
  existing OpenAI-compatible path; no new dependency. Its models see
  images, so choosing it ticks that box as ChatGPT does.
- **Its key comes from `GEMINI_API_KEY`** when none is typed in, the name
  Google's documentation uses. An `OPENAI_API_KEY` from the environment is
  no longer sent to Google; any other server still takes it, as before.
- **Model names lose Google's `models/` prefix** when listed, since the
  chat endpoint is asked for the bare name.
- **A tool call keeps what the server attached to it** (`extra_content`) and
  sends it back unchanged. Gemini 3 signs the first call of a turn
  (`extra_content.google.thought_signature`) and refuses the next round
  without the signature; other servers attach nothing.
- **A rate limit says how long to wait**, when the server tells
  ("Please retry in 30.9s" in Gemini's text; it sends no `Retry-After`
  header; "retry in 21h21m28s" for a daily limit), and that a free tier is
  the reason; for a daily limit it suggests another model, whose limit is
  separate. The free tier allowed 5 requests a minute and 20 a day per
  model when tried (2026-10-26): enough to try the assistant, not to work
  with it all day.
- **A subscription is pointed to MCP**, not built in: Claude Desktop, Claude
  Code or Gemini CLI drive figscribe through `figscribe mcp` with the user's
  own plan. The README says which ways cost nothing.
- **Each user brings their own key.** Google allows only paid services in
  applications made available to users in the EU, EEA, Switzerland and the
  UK; figscribe calls the API with no key of its own, on the user's behalf
  and with the user's project. For those regions Google applies its
  paid-service data terms also to free use; elsewhere free-tier requests may
  be used to improve its products. The README says so.

### Alternatives considered

**Signing in with a Claude subscription** (OAuth): against Anthropic's
terms for third-party applications. **A separate Gemini client** with
Google's SDK: a new dependency for what the OpenAI-compatible endpoint
already does. **OpenRouter, Groq or Mistral by name**: they work through
"Other server" already; naming them adds entries to keep current, for
providers nobody has asked for yet.

---

## 0033 — Panel labels

**Date:** 2026-10-26
**Status:** accepted

### Context

Journals ask for a letter on each panel of a multi-panel figure, in a style
of their own: "(a)" in physics journals, a bold "a" in Nature, a bold "A" in
Science (roadmap F3).

### Decision

- **One setting per figure**, `Figure.panel_labels` (`PanelLabels`, None for
  none), switched on with a box in the figure's *Style* section like a color
  bar: the letters' style (`(a)`, `a)`, `a`, `A`), bold, placement, font size,
  and whether insets get a letter. No letter of its own per panel: a figure
  follows one journal's rule.
- **Reading order by the cell a panel starts in**, row by row, left to right
  (`render.labels.panel_labels`, shared by the renderer and the code
  generator); a panel spanning two rows comes before those beside it. Insets
  get none unless asked for, then each right after the panel it sits in.
  After z the letters go on with aa, ab, as spreadsheet columns do.
- **Drawn with `ax.annotate` at the panel's top left corner**, offset by half
  the label's font size (`textcoords="offset fontsize"`, Matplotlib 3.8, the
  version figscribe needs anyway): outside, above and left of the corner;
  inside, just within it. The offset in font sizes keeps the look when the
  size changes, and the constrained layout makes room for an outside label,
  as it does for a title. The script writes them in one loop over the panels
  and their letters.
- **A label carries no gid**: it is not a model object, and the preview takes
  any text with a gid for a note to drag. Clicking it selects nothing, or
  the panel when it lies inside.
- No schema bump: the field has a default and no released file predates it.

### Alternatives considered

**`ax.set_title(loc="left")`**, the other way Matplotlib's gallery shows:
the layout handles it as well, but it only works outside, takes the title's
size and weight from the style sheet, and would need another call inside.
**`fig.text` at a computed position**: the position would be worked out
before the layout places the panels, and the script would carry numbers
nobody could read. **The letter left of the y label**, as some journals
print it: it needs the width of the tick labels, known only after drawing;
the placement can get a third choice if asked for.

---

## 0034 — Reference lines and shaded ranges

**Date:** 2026-10-26
**Status:** accepted

### Context

Measured data is often read against a value that is not in the data: a
threshold, a literature value, the time a field was switched on, a region
of interest (roadmap F4.1). Matplotlib has `axvline`/`axhline` and
`axvspan`/`axhspan` for it, which span the whole panel whatever its range.

### Decision

- **Two artist kinds**, `ReferenceLine` (`"refline"`, at one value) and
  `ShadedSpan` (`"span"`, between `start` and `end`), each with
  `orientation` "vertical" (an x value or range) or "horizontal" (a y
  value or range). Two kinds rather than one with an optional second end:
  each has only the fields that mean something for it, and the assistant
  writes `{"kind": "refline", "at": 5}` without guessing.
- **Grey by default, not from the color cycle**: a reference is not data and
  should not take the next data color. The line is dashed and 1 pt; the
  range has an opacity of 0.2 and a drawing order of 0.5, below the grid
  lines (1.5) and every plot, so that it stays behind the data whatever
  order things were added in. Its edge is not drawn (`linewidth=0`): in the
  band's own color it would show as a darker outline.
- **Against the left or right y axis** like any plot (`axis`); a horizontal
  line or range then uses that axis' values.
- **Added from three places**: *Insert > Add Line or Range* and a panel's
  context menu in the outline put one in the middle of what the panel shows
  (a range over a fifth of it); a right-click in a panel of the preview
  offers one at the clicked spot ("Vertical line at x = 4.2"). Values are
  rounded to a hundredth of the shown range, or to two significant digits on
  a log axis, where the middle and the width are taken in decades
  (`gui/markings.py`). The exact value is then typed in the property panel.
- **A value a log axis cannot show** (at or below zero) is a problem in the
  list, as data at or below zero is (B7.1); it needs no data to tell.

### Alternatives considered

**`ax.plot` over the current range**: the line would end where the data
ends, and a later change of range would leave it short. **Asking for the
value in a dialog** when adding: the preview's right-click already knows
where the user means, and the menu's middle is a start that the panel
corrects in one field. **Dragging in the preview** is left for later, like
the notes' dragging was added after notes.

## 0035 — Error bands

**Date:** 2026-10-26
**Status:** accepted

### Context

Dense data with y errors, a spectrum or a long time series, turns into a
wall of error bars. Papers draw the errors as a shaded band around the line
instead (roadmap F4.2); Matplotlib has `fill_between` for it.

### Decision

- **A way of drawing an error bar plot's y errors, not a plot of its own**:
  `ErrorbarPlot.band`, an optional `ErrorBand` with `color` (None takes the
  plot's) and `alpha` (0.25, times the plot's own). The data, the left-out
  rows and the fits stay as they are, a fit is still weighted by the y
  errors, and bars and band are one check box apart. A separate kind would
  have needed its own columns, its own left-out rows and its own place among
  the plots a fit can target.
- **Only the y errors**: x errors stay bars, drawn by `errorbar` as before.
  Without x errors the points and their line are drawn by `plot`, which is
  what a person would write; capsize and error bar width then do nothing.
- **Just behind the plot**: the band is drawn after the line, since a
  color from the color cycle is known only then (`line, = ax.plot(...)`,
  `color=line.get_color()` in the script), with a drawing order 0.1 below
  the plot's, so that the line stays on top. Without an edge, as a shaded
  range has none (0034).
- **Left-out rows leave a gap** in the band (`where=` the shown rows), as
  they break the line; their points are drawn apart, without an error, since
  a band of one point has no width.
- **No legend entry of its own**: the plot's entry stands for both.
- **A band without y errors** is a problem in the list rather than refused,
  so that the band can be switched on before the column is chosen.
- An added field with a default: files of 0.1.0 read unchanged, so no schema
  version and no migration.

### Alternatives considered

**`errors_as: "bars" | "band"` with the band's settings beside it**: they
would show, and do nothing, while bars are drawn; the optional part shows
them only when there is a band. **Drawing the band first**: it would need
the color before the line takes one from the cycle, which only Matplotlib's
private API gives. **A band in the legend** (a patch behind the line, as
`(line, patch)` handles): left for later.

## 0036 — Analysis as derived plots, not a statistics suite

**Date:** 2026-10-26
**Status:** accepted

### Context

The brief rules out a statistics suite, and roadmap F10 asks for every
analysis tool to be decided on its own. The first one asked for is the
Allan deviation, the standard figure for the stability of clocks, lasers,
gyroscopes and other sensors. figscribe already computes two plots from
the data: a histogram counts a column into bins, and a fit runs
`curve_fit` in the renderer and in the script alike.

### Decision

An analysis belongs in figscribe when all three hold:

1. It is a **standard figure** of some field, not a number or a test result.
2. It is computed from a few columns in **a few lines of NumPy or SciPy**,
   which the generated script writes out as a readable function, so the
   script stays standalone and needs no new dependency.
3. It is described as **a plot with a few settings**. The model stores what
   is computed (columns, rates, the variant), never the result; the
   renderer and the script compute it alike, and the pixel equivalence test
   holds them together.

The Allan deviation meets all three and becomes a plot type (roadmap
F4.9). Hypothesis tests, ANOVA, regression tables and the like do not:
they produce numbers rather than figures, and stay out. Smoothing, peak
finding and scale/offset per column (F10) are judged by the same three
points when they come up.

### Alternatives considered

**`allantools` as a dependency**: complete, but the script would need it
too, and overlapping ADEV is about ten lines with `cumsum`; the tests can
check against published reference values instead. **A general transform
step** (any column through any function before plotting): that is the
column-formula language the brief excludes. **Computing outside**: works
today (import τ, σ and its error as a CSV and draw error bars on log axes),
but the figure then no longer says how it came from the measurement.

## 0037 — Several figures in one project

**Date:** 2026-10-26
**Status:** accepted

### Context

The model held a list of figures from the start, but the GUI and `figscribe
script` used only the first, and there was no way to add one (roadmap F8).
A scientist's project typically has several plots of the same data: the
measurement, a detail, the fit's residuals for the supplement.

### Decision

- **Tabs above the preview, and the outline**, as the user chose: the tabs
  show only while there is more than one figure, so that a project of one
  looks as before. Choosing a tab, or anything of a figure in the outline,
  shows that figure; `Document.figure_changed` tells the preview and the code
  drawer, which until then redrew only when the model changed.
- **A new figure takes the look of the shown one**, size, fonts, ticks and
  panel letters, since a project's figures go into the same paper; it gets
  one empty panel and the name "Figure N" after its place. *Figure* sits in
  the toolbar after *Data*, in the order a figure is built, as the user
  proposed.
- **A duplicate has ids of its own**: its fits, residuals and insets point at
  its own plots and panels, its plots at the same data files.
- **One menu for a figure**, in the tabs and the outline: rename, duplicate,
  move, delete. Dragging a tab moves the figure once the button is released,
  as one undo step, not one per tab passed.
- **A project keeps at least one figure**: deleting the last is refused with
  a message, in the GUI and in the assistant's remove.
- **Export all** writes every figure, as PDF, SVG, PNG or its script, into a
  folder, named after the figures; `figscribe script --all` does the same for
  scripts, `--figure NAME` picks one. Two figures whose names give the same
  file name get a number (`scan`, `scan-2`), so no file overwrites another.

### Alternatives considered

**Tabs only, or the outline only**: the outline already listed the figures,
but which one is shown could then be seen only from the selection; tabs
alone would hide the other figures' contents. **A new figure from the
defaults**: every journal setting would have to be made again. **Moving a
figure with each tab passed while dragging**: one undo step per tab, for one
intended move.

## 0038 — Finding a setting: a search and a command palette

**Date:** 2026-10-26
**Status:** accepted

### Context

The property panel shows every field of the model, which is the point of
it, and a plot has some thirty; a figure as many again. Finding "the one
for the tick length" means knowing which section it is in (roadmap U3).

### Decision

- **A search field above the property panel** (Ctrl+F), fixed while the
  form scrolls. Every typed word must occur in a field's caption, in its
  tooltip, or in its section's title; the rest of the rows and the sections
  left empty are hidden, and a folded section with a match opens. The
  field's value is not searched: "tick" should not find a label that says
  "ticks". The search stays when another object is selected, so that the
  same setting can be found on the next plot, and Esc clears it. A section
  the search opened is not remembered as opened by the user.
- **The form is built anew for each search**, 150 ms after the last key,
  and the rows are hidden after building. Showing them again would have to
  know which rows the forms hide themselves (the axis form shows the step
  only with "every"), and building takes a few milliseconds.
- **A command palette** (Ctrl+K): every enabled menu action, with the menus
  it is in, and every field of the selection, as "Setting · section".
  Words are matched as in the search; entries starting with the first word
  come first. Up and Down move, Enter chooses. A setting is shown: the
  search cleared, its section opened, scrolled to and focused. The chosen
  action runs after the palette closed, so that a dialog it opens (Add
  Plot…) is not inside the palette's.

### Alternatives considered

**Fuzzy matching** (letters in order, "lnw" for line width): unexpected
results for short queries, and the words people type are the ones in the
captions and tooltips. **The palette also listing the objects of the
project** ("go to the residuals"): the outline already does that.

## 0039 — Basic settings first, and several plots at once

**Date:** 2026-10-26
**Status:** accepted

### Context

The rest of roadmap U3: a plot's "Look" had thirteen fields, a figure's
"Style" eleven, most of them rarely changed; and a change meant for every
plot of a panel had to be made once per plot.

### Decision

- **Per kind of object, the basic settings stay in their sections, the rest
  goes to the folded "More"** (`BASIC` in `gui/properties.py`). They were
  chosen from the assistant's benchmark, which holds the requests users
  make most (color, marker, error bar caps, legend, size, font size, title,
  grid), and by judgement where it has none: a plot's color, marker, line
  and legend entry; a figure's name, size, font size and panel letters; a
  panel's title, grid and right axis. Mostly five, as the roadmap asked,
  fewer where there are not five worth it. Sections that say what is
  plotted and where (data, position, the axes, the file and how it is read)
  stay whole, and so does the PNG resolution, kept apart from the size
  (0006). The search and the palette (0038) find what is folded away.
- **Several plots are chosen together** in the outline with Ctrl or Shift
  and a click; with a panel or a figure among them, only the row clicked
  last is chosen. `Document.selection` holds them, `selected` stays the
  last, so that everything that acts on one object goes on working.
- **The panel shows the settings they share** (`SHARED`: color, marker,
  marker size, edge color, line, width, caps, opacity, visible), where each
  of the chosen plots has the field with an editor of the same kind. A value
  they agree on is shown; otherwise the field says "several" (a partly
  checked box, an empty line). A change sets it on all of them as one undo
  step, "Change 2 plots". Delete removes them all, each with its fits and
  residuals, once.
- Check boxes in the panel commit on `clicked`, not `toggled`: a partly
  checked box becomes checked on a click without toggling.

### Alternatives considered

**"More" by usage counts gathered from the user's own work**: nothing is
recorded, and a panel that rearranges itself is harder to learn. **Several
objects of any kind together**: what a figure and a plot share is a name at
most. **Several selected in the preview**: a click there picks one thing;
the outline lists everything, so it is the place to pick many.

## 0040 — Changing things where they are drawn

**Date:** 2026-10-26
**Status:** accepted

### Context

Roadmap U4: a label, a title, the size of an inset or of a column were
changed in the property panel, away from where they are seen; the plot
under the mouse had no menu of its own.

### Decision

- **A double-click edits a text in place**: an axis label, a panel's title,
  a legend entry or a note. A field opens over it, holding what the model
  holds, all selected: an axis label without the unit it is drawn with, a
  note with its lines (Ctrl+Enter ends it, as in the panel). Enter or
  leaving the field sets it as one undo step, Esc leaves it. An emptied
  legend entry takes the plot out of the legend; an emptied note stays as it
  was, since a note without text would vanish, and Delete does that.
  A legend entry is mapped to its plot through the handles the legend was
  built from, not by its text, which two plots may share.
- **Dragging resizes**, one undo step on release like the legend and notes:
  an inset's corner (the opposite one stays; at least a twentieth of the
  panel each way), and the gap between two columns or rows, which shares
  their room differently: the two keep the sum of their ratios, each at
  least a tenth of it, rounded to two digits. The cursor shows what a drag
  would resize; a click there still selects. The grab zone of a gap is a
  few pixels around its middle, so that dragging the numbers of an axis
  next to it still pans.
- **A right-click on a plot** offers *Style like* (each other plot of the
  figure that looks different; what both have and the target can take:
  "no marker" of a line is not a marker for error bars), *Bring to front*,
  *Send to back*, *Fit…* and *Hide*, before what the point under the mouse
  and the panel offer.

### Alternatives considered

**Dragging an inset to move it**: a drag inside it pans it, which is used
more. **Ratios from exact panel widths**: constrained layout puts the labels
into the gaps, so what a column gets from a ratio is not proportional to
it; the release shows the result at once, and a second drag corrects it.

## 0041 — Unit conversion and a range per plot

**Date:** 2026-10-26
**Status:** accepted

### Context

Times are measured in s but shown in min, h or days, and often counted from
the start of the measurement rather than from a timestamp. "Show values in"
(decision 0025) only relabels the ticks with a power of ten: the ticks are
still placed in the data's unit, so a factor of 3600 would put them at 0,
5000, 10 000 s and label them 1.39, 2.78 h, and limits and steps would still
have to be typed in s. Separately, a plot sometimes should use only part of
its data, e.g. the stable hours of a measurement. Axis limits do not do
that: they crop the view, while histogram bins, an Allan deviation, fits and
autoscaling still see every row. Roadmap F10 asked whether scale and offset
per column are in scope; F2 left a range per plot open.

### Decision

Asked and answered by the user: the conversion acts on the data, not on the
labels; it can start the values at zero; the range is given in x values.

- **A conversion per plot and axis**, `x_conversion` and `y_conversion`, of
  a factor, an optional start at zero and the unit the result is in:
  shown = (value − start) × factor, where the start is the smallest value of
  the column (`np.nanmin`), so "hours since the start of the measurement"
  works with timestamps and with unsorted data. Errors and error bands are
  scaled with their axis, never shifted. The axis knows nothing of it: it
  is an axis in h, and everything typed on it is in h, so limits, ticks,
  steps, reference lines, notes, fit ranges and the plot's range need no
  second unit. This fits the judgement of decision 0036: one line of NumPy
  in the script, a setting of a plot, no formula language.
- **Fits fit the converted data**, so their parameters are in the shown
  units (a decay time in h), as a person who converted first would get.
  Changing a conversion fits the plot's fits again in the same undo step,
  as leaving a point out does, and converts the plot's range and its fits'
  ranges along, so the same rows stay selected.
- **A range per plot**, `x_range`, in shown x values, both ends included:
  only those rows are drawn, fitted and counted. Rows outside are not
  drawn at all, unlike left-out rows, which stay visible; a fit range lies
  within it. For a histogram it is the range of the values, and the bins
  of a bin count span it; for an Allan deviation it is the time since the
  first sample (the time column, or i·τ0), and the part within must be
  unbroken.
- **The script** converts once and names the result after the column and
  the unit: `t_h = (t - np.nanmin(t)) / 3600  # h since the start`, and
  folds the range into the plot's mask: `kept = (t_h >= 2) & (t_h <= 10)`.
  A factor whose inverse is a whole number is written as a division, as
  the prefix formatter does, and renderer and script share that choice.

### Alternatives considered

**A factor on the axis**, like the SI prefix: every coordinate typed on the
axis (limits, steps, lines, notes, ranges, fits) would need converting in
the renderer, the script and the problem list, and the ticks would not be
round. **On the column reference**, as F10 first suggested: x errors and y
errors would each need the same factor set again, which is easy to forget.
**A derived column on the data source** (`t_h = t / 3600`, used by any
plot): shares a conversion between plots, but is the first step towards
column formulas, which the brief excludes. **A row range** ("rows 100 to
2000"): exact, but not how a figure is read; it can follow if asked for.
**Keeping fits in the file's units** and only drawing them converted: the
parameters would not match the axis they are read against.

### Settled while building it

- `figscribe/convert.py` holds the arithmetic and `figscribe/units.py` the
  commands; the panel and the assistant both call `set_conversion` and
  `set_range`, so neither can change a conversion without its axis and fits.
- **Start values** of a fit that are not held are dropped on a conversion:
  in the old units they would mislead the fit. Held values stay as typed.
- **The unit text** follows when the axis showed the old conversion's unit,
  or the axis's own unit when the old setting gave none; taking a
  conversion with a unit back empties the axis's unit, since figscribe does
  not know the file's unit.
- A symlog axis's linear range is scaled with its step, like a width.
- **"Start at 0" is not offered for an Allan deviation** rather than greyed
  out: τ starts at τ0 whatever, so no state of the plot would make the box
  count, and a greying rule needs one (`tests/gui/test_without_effect.py`).
- The script keeps the range as its own mask, `used = (t_h >= 2) & (t_h
  <= 10)`, instead of folding it into `kept`: `kept` also says which rows
  are drawn apart as left out, and those outside the range are not drawn
  at all. The two are joined where the plot is drawn and fitted.

## 0042 — Everyday actions: duplicate, paste a style, one range, copy, show

**Date:** 2026-10-29
**Status:** accepted

### Context

Roadmap U5: five small actions that a scientist reaches for all the time and
that took many clicks or a trip to the file manager. No model field changes,
so the project file stays as it is (no schema bump).

### Decision

- **Duplicate (Ctrl+D) is one action that acts on the selection.** A figure
  is copied as before (F8); a panel is copied with its plots, its fits and
  its insets into the cell to its right, making a column if none is free
  (`add_panel`'s rule, now `_make_room`); plots are copied right after their
  originals, so they are drawn above them. Several chosen plots are one
  undo step. The copy is selected.
  - Every copy gets new ids, and what refers to a copied object follows it:
    an inset its panel, a fit its data, residuals their fit. A reference to
    something that was not copied stays: a fit copied alone fits the same
    data, a panel's fit residuals (in another panel) stay with the original.
  - A copied plot with a label is labelled "… (copy)", or the legend would
    show two entries alike.
  - **Not duplicated:** residuals (add them again from the fit, which keeps
    them tied to one fit), an inset alone (a copy at the same bounds would
    lie exactly on the original and show nothing; the panel's copy takes its
    insets along), a data file, an axis.
- **Copy Style / Paste Style (Ctrl+Alt+C, Ctrl+Alt+V)** keep a *snapshot* of
  the plot, not its id: the source may be changed or deleted before the
  paste, and what was copied is what is pasted. Paste goes to every chosen
  plot as one step, takes what each plot can have (as *Style like* does,
  which is the same code), and does not make an undo step when nothing
  would change. The system clipboard is not used; it has no format for this.
  Plain Ctrl+C and Ctrl+V are left alone: they belong to text fields.
- **Same range in all panels** (the panel's menu in the outline and in the
  preview, x or y) writes the range the panel *shows* into every panel of
  the grid, as fixed limits, also into the panel itself, so that they stay
  equal when the data changes. The range is read from the drawn axis, so an
  automatic or zoomed range works, and a turned axis (first end the higher)
  stays turned. Left out, and named in the status bar: insets, which have a
  range of their own, and panels whose axis has another scale or another
  unit text, where the same numbers would mean something else (since F11,
  panels may show the same column in h and s).
- **Copy Figure (Ctrl+Shift+C)** puts the shown figure on the clipboard as
  PNG and SVG, and as a bitmap for programs that read neither (Office on
  Windows). Both are the bytes *Export* writes: `render.export_bytes`, one
  code path with `export`, so size, resolution and metadata are the same and
  the clipboard cannot show another picture than the file. PDF is not put
  there; no common program reads it from the clipboard on Windows or Linux.
  Which of the formats another program takes depends on the system and the
  program; the tests only read them back from Qt's own clipboard, so
  step 12 of the manual checklist is what shows it.
  **At the end of the program** the clipboard keeps only the bitmap: a
  `QMimeData` made in Python is deleted by Qt after Python has shut down,
  which crashed every process on exit (found when Python crash reports piled
  up during the test runs). `gui/clipboard.release` swaps it for Qt's own
  image data on `aboutToQuit`; the tests do the same after each test. The
  SVG therefore does not outlive the program.
- **Show in Finder / Explorer / file manager** on a data file in the outline
  selects the file where the system can: `open -R` on macOS, `explorer
  /select,` on Windows, with the standard library's `subprocess`; elsewhere
  the folder is opened through Qt. A file that is not there says so and
  points to *Locate file…* in the data bar. No new dependency.

### Alternatives considered

**A separate Duplicate for each kind of object**: three menu entries and
three shortcuts for one idea. **Storing the copied style's plot id**: breaks
when the plot is deleted, and pastes a later style than the one copied.
**The same range taken from the model's limits**: an automatic range is
only known after drawing, and a zoom that was not adopted is what the user
sees. **Copying the range into panels of another unit as well**: silently
wrong numbers. **A PDF on the clipboard**: right for Keynote and Pages, but
not for the rest; PNG and SVG cover slides and documents everywhere.


## 0043 — Axis labels in line across panels, and their distance

**Date:** 2026-10-29
**Status:** accepted

### Context

Roadmap F5.9, asked for by the user. In a column of panels the y labels
stagger: each stands as far left as the numbers of its own panel are wide.
Matplotlib has `fig.align_labels()` for it, and `labelpad` for the distance
of a label from the axis.

### Decision

- **`Figure.align_labels`, on by default, also for files saved before.** No
  schema bump and no migration: a saved figure with several panels looks
  different once it is opened (the labels line up), and the CHANGELOG says
  so. The user chose this over "on for new figures only" (2026-10-29); the
  figure's setting turns it off. A figure with one panel is drawn the same
  either way, so its script has no call.
- **Which axes are lined up** is the same set in the renderer and the script
  (`render.figure.aligned_axes`): the panels in the grid, and their right y
  axes with them, so right labels of several rows line up too. Never an
  inset, which is no part of the grid, and never a colour bar's own axes. And,
  without the constrained layout, not a panel that draws a colour bar:
  Matplotlib then splits the panel's grid cell for the bar, the alignment
  counts its rows and columns from zero again and takes the panel for one in
  the first row or column, which pulled its label out of the figure (found by
  a test, with the bar in the second column). With the constrained layout the
  panel keeps its place and is lined up. The renderer always passes the
  list; the script writes plain `fig.align_labels()` when `fig.axes` are
  exactly these (no inset, no colour bar, no panel left out), as a person
  would, and names them otherwise. The plain call itself also ran without
  error with insets, twin axes and colour bars on Matplotlib 3.8.4 and
  3.11; the list is for what gets grouped, not for old versions.
- **`AxisSpec.labelpad`** in pt, at least 0, empty follows the style; on the
  right y axis too. A panel's own distance moves its label alone, also where
  labels are lined up: Matplotlib puts a label at the group's edge minus its
  own distance. The axis form's *Label* section has *Distance (pt)*; it
  cannot be greyed without a label, as the form has no such mechanism, so
  its tooltip says it needs a label, and the script writes the distance only
  with a label.
- The switch is greyed while there are fewer than two panels to line up (a
  rule in `gui/effect.py`, checked against the renderer).

### Alternatives considered

**On only for new figures, off for saved ones** through a schema bump: files
keep their look, but most figures figscribe has made would stay staggered
until someone found the switch. **Dragging a label in the preview**: not
wanted for now. **Aligning insets and colour bars too**: a colour bar's
label would be lined up with a panel's, which is wrong. **Always the
explicit list in the script**: correct, but `fig.align_labels()` is what a
person writes.


## 0044 — Minimum versions that are tested, and a lighter CI

**Date:** 2026-10-29
**Status:** accepted

### Context

`pyproject.toml` said `matplotlib>=3.8`, `numpy>=1.26`, `scipy>=1.11`, but the
CI always installed the newest versions, so no floor had ever been run. Trying
them (a scratch environment with Python 3.11 and `uv pip install
--resolution lowest-direct`, then each version on its own) showed:

- **Matplotlib 3.8** does not run: the renderer calls `axis.minorticks_on()`,
  which exists from 3.9. 3.9.4 runs, but five tests of shared tick labels
  fail there. 3.10.0 has no functional failure; only the pixels of the image
  baselines differ, as they are made with the newest version.
- **NumPy 1.26** fails two tests that read decimal-comma and Windows-encoded
  text files (the `converters` of `np.loadtxt` get bytes there); the same
  call is in the generated script. 2.0 passes.
- **SciPy 1.13** is the first with NumPy 2 support. **PySide6 6.6** is built
  against NumPy 1 and warns that it may crash with NumPy 2; 6.7 does not.

### Decision

- **Floors: `matplotlib>=3.10`, `numpy>=2.0`, `scipy>=1.13`,
  `PySide6>=6.7`.** The first three are what the tests passed at, apart from
  the image baselines. pydantic stays at 2.9, which passed.
- **A CI job `minimum-versions`** installs the lowest allowed version of each
  direct dependency (`uv pip install --resolution lowest-direct`) on Linux
  with Python 3.11 and runs the fast tests, without the image baselines and
  without the GUI tests. It is not among the checks the branch protection
  requires, so a new release of a dependency cannot block a merge.
- **The GUI tests were seen to pass only on PySide6 6.12.** With the other
  floors at their lowest and PySide6 6.7 to 6.11, the same four tests and one
  error fail (the help menu, the arrow keys in the search, two outline menus;
  "Internal C++ object (QMenu) already deleted" and a key that is not taken).
  With 6.12.0 and the other floors still at their lowest, all 448 pass. It is
  open whether those are the tests holding Qt objects too loosely or the
  program; `PySide6>=6.7` is therefore only the floor for what loads and runs
  without the window, and the roadmap has a task to settle it (E5).
- **The CI is lighter for small changes:** a newer push to a pull request
  cancels the older run (not on develop and main); `setup-python` caches pip;
  a pull request that only changes `plan/`, `docs/` or Markdown files runs the
  required jobs without installing or testing. The jobs still start, because
  the branch protection requires them by name and a workflow skipped as a
  whole would leave them pending.

### Alternatives considered

**`paths-ignore` on the workflow**: simplest, but a pull request that only
changes the plan could then not be merged without bypassing the protection.
**Fixing NumPy 1.26 in the reader and the script** to keep the old floor: more
code, and the script would carry a workaround for a version two years old.
**Floor PySide6 at 6.12**: the only version the GUI tests pass on, which is
also the newest; users would have to upgrade for no reason known yet.
**A second Python version in the minimum job**: 3.11 is the floor of
`requires-python`; 3.13 runs in the main matrix.
