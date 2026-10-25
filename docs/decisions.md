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
