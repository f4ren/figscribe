# Roadmap: from the current state to a release

This plan picks up where the milestones in the [project brief](project-brief.md)
left off. The brief stays the vision; this file is the work list. It is written
so that a coding session can take the next open task and finish it without
asking what was meant.

**State as of 2026-10-23** (branch `develop`, commit `9063d71`):

- M1 to M6 of the brief are done: model, renderer, code generator with the
  pixel equivalence test, GUI with import, property panel, outline, undo/redo,
  zoom/pan, panels and insets, right y axis, histograms, notes, 2-D data, fits
  with residuals. Beyond the brief: the built-in assistant (Claude, ChatGPT,
  local models), the MCP server and `figscribe bench`.
- M7 is open: style templates, snapping and alignment guides, packaging.
- About 650 tests run in about 25 s; CI is green on Linux, Windows and macOS
  with Python 3.11 and 3.13. Decisions 0001 to 0026 are in
  [`docs/decisions.md`](../docs/decisions.md).
- `main` is behind `develop` (last merged: PR #31). PyPI still has the 0.0.2
  placeholder.

The findings below marked **(verified)** were reproduced on 2026-10-23; the
reproduction is given so a session can turn it into a failing test first.

---

## How to work on this plan

1. **Pick the first open task** of the lowest open phase, unless the user names
   another. Tasks within a phase are ordered by value.
2. **Tasks marked `[decide]` need the user's answer first.** Ask the question
   in the task, record the answer in `docs/decisions.md`, then implement. Do not
   guess; the working agreement in the brief says to ask.
3. **One task, one branch, one pull request** into `develop`. Branch from
   `develop`, name the branch after the task (`b1-tick-limit`). CI must be green
   on all three platforms before merging.
4. **Test first.** For a bug, the first commit is a failing test that
   reproduces it. Every model change gets a roundtrip test, every new command an
   undo test, every rendered feature an image baseline and a codegen
   equivalence case.
5. **Keep the four outputs in step.** A new model field must reach the
   renderer, the code generator (with an equivalence case), the property panel
   (with a plain name in `gui/names.py` and a tooltip) and the assistant tools
   (`tools/spec.py`). Task U1 turns this into a test.
6. **Record decisions** that are not obvious from the code in
   `docs/decisions.md` (context, decision, alternatives), numbered on from 0026.
7. **Update this file in the same pull request**: tick the task, add what was
   learned, add follow-up tasks you discovered.
8. Everything in the repository is written in English, commit messages
   included. Run `ruff check . && ruff format --check .` before pushing.
9. A schema change to the project file bumps `SCHEMA_VERSION` and adds a
   migration with a stored example file of the old version (see `_migrate` in
   `model/project.py`), unless the new field has a default and no released file
   predates it — say which in the pull request.
10. **Every GUI element is tested the way a person uses it.** A pull request
    that adds or changes a widget, dialog or action covers it in the field
    test or an operation test of task B8, and goes through the manual
    checklist in `docs/testing.md` if it changes what is seen. Tests click
    (`click()`, `activated`, `editingFinished`, `QTest` mouse events); they do
    not call `setChecked()` or `setCurrentIndex()` alone, which skips the code
    a real click runs.
11. **Others work on the same plan.** Before starting a task, look for a
    branch or pull request that already works on it (`git fetch`,
    `gh pr list`), and open a draft pull request as soon as the branch is
    pushed, so the next session sees it.

**Pulled forward** at the user's request (2026-10-25): F1.2 (held
parameters and bounds) now, since it touches nothing U2 changes; F8 (several
figures) right after U2 is merged and before U3 and U4, because it turns
"the first figure" into "the current one" in eight modules, and the GUI work
of U3 and U4 would otherwise be built on the old assumption. Nobody starts U3
or U4 while F8 is open.

Sizes: **S** is up to half a day, **M** a day or two, **L** more; split an L
into pull requests that each leave `develop` working.

---

## Phase 0 — Bugs and robustness

Nothing here adds features. The goal: no input, file or setting can freeze or
crash the application, and every error says in plain words what to do.

### B1 A small tick step freezes the application (verified) — S

*Repro:* x range 0 to 10 000, *Major tick every* 1. Rendering takes over 20 s
per redraw; time grows linearly at about 2.5 ms per tick (1 000 ticks: 2.4 s,
2 000: 5.2 s). The preview redraws on every change, so the window hangs.
Matplotlib only warns (`Locator.MAXTICKS`). Same with `minor_divisions` on top.

*Do:* refuse steps that would give more than a sane number of ticks (about 50
major ticks per axis; pick and justify the number). The axis form says so
inline ("every 1 gives 10 000 ticks; at most 50") and does not commit;
`validate_references` reports it for project files and assistant edits; the
renderer falls back to automatic ticks for a model that still has it, so a
loaded file never hangs. Code generator mirrors the fallback.

*Done when:* a test renders the repro under one second; the axis form and an
assistant edit both get a clear refusal.

**Done** (2026-10-24, decision 0027): at most 50 major and 250 minor ticks
per axis. *Learned:* the repro was worse than measured above, about 21 s for
2 000 major ticks, because the automatic minor ticks multiply the count by
five; so minor ticks are limited too. An automatic range is only known after
drawing, so the renderer now sets steps after all panels are drawn, and the
code generator draws the figure when it needs such a range. *Follow-up:*
`validate_references` cannot check an automatic range without data; give it
the data when B4 does.

### B2 A changed or moved data file is a dead end — M

*Now:* the preview shows "Cannot draw the figure … has changed since it was
imported", and nothing in the GUI fixes it. Same for a file that moved.

*Do:* a bar above the preview naming the file, with
- **Use the new version**: re-hash and re-read the columns, one undoable
  command; if columns used by plots are gone, list them;
- **Locate file…** for a missing file (relink, keep the options);
- **Show what changed**: rows and columns before and after.

Also for several files at once (one bar, a list). The assistant tools get the
same action. Record the decision (changes 0007).

*Done when:* GUI tests cover changed, missing, and changed-with-lost-columns.

**Done** (2026-10-24, decision 0007): `io/refresh.py` builds the commands,
`gui/databar.py` is the bar, `use_new_data_version` the tool. Sources record
`row_count` on import. *Learned:* `rows` as the field name collided with
`GridLayout.rows` in the property panel, which matches read-only fields by
name. Qt does not show widgets added to an already visible one, so the bar's
rows appeared empty in a shown window while tests of a hidden one passed;
the tests now show the window and only count visible labels and buttons.
*Follow-up:* the preview's own message still says "Cannot draw the figure";
it could point at the bar instead.

### B3 Text files from older instruments fail to import (verified) — S

*Repro:* a CSV in cp1252/Latin-1 with `µ` in the header: `csv_source` raises a
raw `UnicodeDecodeError` (not even a `DataError`), the import dialog has no way
around it. Lab software on Windows writes these often.

*Do:* add `CsvSource.encoding` (default `"utf-8-sig"`); the import dialog
detects it (UTF-8 if it decodes, else cp1252, else Latin-1) and shows it as an
option; the code generator passes `encoding=` to `np.loadtxt`. Any decode error
becomes a `DataError` that names the file and suggests the encoding option.

**Done** (2026-10-24, decision 0007): `CsvSource.encoding` is one of
`utf-8-sig`, `cp1252`, `latin-1`, detected in that order and chosen in the
import dialog (a chip says when it is not UTF-8) and the property panel.
*Follow-up:* for a UTF-8 file without byte order mark the script still writes
no `encoding=`, and NumPy 2 then uses the system's encoding: on Windows,
cp1252, which cannot decode some UTF-8 bytes (e.g. `0x81` in "Á"), so the
script may fail there on a header with such letters. Write `encoding="utf-8"`
whenever the file is not plain ASCII.

### B4 Raw library errors reach the user (verified) — S

*Repro:* x and y columns of different length give Matplotlib's "x and y must
have same first dimension, but have shapes (3,) and (4,)"; an invalid color
gives a long Matplotlib message. Both only appear at render time, after the
bad value is in the model.

*Do:*
- validate style strings when they are set, through a check shared by the
  property panel, the commands and the assistant tools: colors with
  `matplotlib.colors.is_color_like`, markers and line styles against what
  Matplotlib accepts (this settles the open point from decision 0002 to close
  these free strings);
- report columns of unequal length as a problem naming both columns and their
  lengths (in `validate_references` when data is available, otherwise in the
  renderer as a `DataError`);
- go through every `except Exception` in `gui/` and make sure the message shown
  is written for a scientist, not a developer.

**Done** (2026-10-24, decisions 0005 and 0006): the commands check style
strings through `model/styles.py`; `validate_references(project, data)`
reports bad styles from a file and columns of unequal length, which the
renderer refuses as a `DataError`; `gui/errors.explain` words every error the
GUI shows. *Learned:* three calls used a `ValueError` only to carry a message;
they pass text now. A broken project file reached the user as pydantic's
"1 validation error for Project"; it now says where the file is damaged.

### B5 Numbers typed the way people type them (verified) — S

*Repro:* the property panel refuses `1,5` (decimal comma) and `−3` (the
typographic minus that comes with text copied from a PDF), but accepts `inf`
and `nan`, which make no sense for a size or a range. `_pair("0,5; 1,5")` fails
with the confusing "'5; 1' is not a number".

*Do:* one number parser for every field in `gui/` (property panel, axis form,
fit dialog): accept `,` as decimal mark where unambiguous, `−` as minus, thin
and normal spaces as thousands separators; refuse non-finite values except
where a field means them; error messages quote what was typed. Pairs and lists
use `;` as the separator when the decimal mark is a comma. Also check whether
pydantic accepts `inf` for `gt=0` fields (`Figure(width_mm=inf)`) and close it
in the model.

**Done** (2026-10-24, decisions 0001 and 0006): `gui/numbers.py` reads every
number typed in the property panel, the axis form and the fit dialog. The
model refuses non-finite numbers except in fit results. *Learned:* pydantic
did accept `inf` for `gt=0` fields, and `nan` for any float. Spaces group
thousands only before three digits: otherwise "0.5 1", a list missing its
comma, would be read as 0.51. No field the GUI edits means an infinite value,
so the planned exception for such fields was not needed.

### B6 Optional parts break the test run without their extras (verified) — S

*Repro:* without the `mcp` extra, `tests/assistant/test_mcp.py` aborts the whole
collection; without `anthropic`/`openai`, four chat and bench tests fail.

*Do:* `pytest.importorskip` at the top of those modules or tests, so a plain
`pip install -e ".[dev]"`-less checkout still runs everything else. CI keeps
installing all extras so nothing is skipped there.

**Done** (2026-10-24): the three chat tests and the bench test skip without
`openai` or `anthropic`. In `test_mcp.py` only the seven tests that use the
`mcp` package skip; the endpoint file, the tool server and the window's
switches are tested without it. *Learned:* the module already had an
`importorskip("mcp")`, but below the import that failed first.

### B7 A systematic bug hunt — M, repeat before every release

Each item is its own pull request; write the failing tests first and fix what
they find.

1. **Edge-case data matrix**: for line, scatter, errorbar, histogram, image,
   fit: empty column, all NaN, one point, two points, constant values, values
   ≤ 0 on a log axis, 1e-30 and 1e30, integer columns, reversed and equal
   limits. Render, export, and run the generated script for each. Nothing may
   crash; a problem shows as a message.
2. **Undo stress**: random sequences of commands (add, change, delete, move
   panels, fit), then undo all: the project equals the start; redo all: equals
   the end. `[decide]` whether to add `hypothesis` as a dev dependency for this
   and for model roundtrips with generated projects.
3. **Fits that should fail politely**: fewer points than parameters, all NaN,
   exponential on negative data, start values that overflow. Each gives a
   message in the fit dialog, never a traceback.
4. **Files**: paths with spaces and non-ASCII characters (verified fine for
   the code generator), network paths on Windows, read-only directories, a data
   file deleted while the project is open, a project file saved by a newer
   figscribe.
5. **GUI**: small window (1024 × 700), high-DPI scaling 150 % and 200 %, dark
   mode on all three platforms, keyboard-only use of the import dialog, fit
   dialog and property panel.
6. **Code generator**: every project in `examples/` and every bench case
   through the equivalence test (some bench cases may not be covered yet).

### B8 Every GUI element is tested the way a person uses it (verified) — M

*Now:* GUI tests set widgets directly (`setChecked`, `setCurrentIndex`), so
code that only a real click runs is never tested. On 2026-10-25 a probe
operated each of the 56 editors of the property panel on the example project
like a user (click a box, pick an entry, type and press Enter) and checked:
the model changes, the figure still draws, the image changes, undo restores
the project. It found:

1. **Crash** (verified): clicking "Right y axis" on a panel kills the
   application with a segmentation fault, on `develop` too. The click adds an
   optional part, `PropertyPanel.rebuild` builds a new form, and `setWidget()`
   deletes the old one, with the box whose click Qt is still handling. "Color
   bar" goes the same way. Fix: `takeWidget()` and `deleteLater()` the old form,
   as `gui/databar.py` does. Look for the same pattern elsewhere (forms that
   rebuild from a signal of one of their own widgets).
   **Done** (2026-10-25): `rebuild` hides the old form and deletes it later;
   the right axis and color bar tests click their box. *Learned:* only
   `setWidget()` in the property panel replaced a form under its own widget;
   the import and fit dialogs, the data bar and the start page already delete
   later. Push buttons survive it anyway (Qt guards their click), check boxes
   do not. The outline clears its tree from its own clicks; the operation
   tests of item 2 below cover it.
2. **Values that break the figure are accepted** (verified): resolution `2`
   dpi (FreeType: "invalid ppem value"), style sheet `2` (unknown style), row
   or column `2` in a 1 × 1 grid (GridSpec IndexError). The command takes them
   and the preview shows the error afterwards. Refuse them in the command with
   a plain message, as B4 does for colors; give `dpi` a sensible lower bound.
   **Done** (2026-10-25, decisions 0003 and 0006): `dpi` is at least 72; a style sheet
   is a name Matplotlib has or a path ending in `.mplstyle`, checked like the
   other style strings; `History.push` refuses a command that puts a panel
   outside its grid, judged after a whole macro. *Learned:* three tests used
   a panel outside the grid as their example of a problem in the list; ratios
   that do not match the grid are that example now, since they stay allowed
   (no order of edits changes the number of rows without a mismatch on the
   way). *Follow-up:* such ratios still make the figure undrawable; the panel
   should adjust them when the number of rows or columns changes (after U2,
   which gives each ratio its own field). Font sizes far below 1 pt would hit
   the same FreeType limit as a tiny dpi; not checked yet.
3. **Format fields of a data source** (verified): a separator, decimal mark or
   comment mark that makes the file unreadable is taken, and the figure
   breaks. Read the file with the new setting first and refuse it with the
   reason, as B2's "Use the new version" does.
   **Done** (2026-10-25, decision 0007): `io/refresh.read_differently` reads
   the file with the new option and returns one undo step that also takes the
   columns and row count it then has, or a DataError that the panel and the
   assistant show; `reading_options` finds the options from the reader's
   parameters, as `reread` does. A file that changed since import is not read
   again that way, which would take its new version without saying so.
   *Learned:* the assistant's `apply_changes` builds its steps apart from
   `set_field`; both now go through one method. A header line that is fine
   for the reader but renames columns leaves plots of the old names, which
   `validate_references` reports (B2).
4. **Settings without effect, without a hint** (verified): while "Grid lines"
   is off, the grid's axes, tick choice and color do nothing; "Grid lines at:
   minor ticks" shows nothing while the axis has its minor ticks switched off.
   Disable such fields or say why they do nothing (relates to U2). The field
   test adds: a color mesh's x or y alone does nothing, the renderer uses
   them only as a pair. Do this after U2, which reworks the same panel code.
5. **Missing API key** (verified, by hand): "Load models" in the assistant
   settings with Claude and no key anywhere prints a traceback to the terminal
   and shows nothing in the dialog. The Anthropic SDK raises a `TypeError`
   ("Could not resolve authentication method") before any request, which
   `_Translate` in `assistant/chat.py` does not map. Say "No valid API key …"
   as for an invalid one. Check sending a chat message without a key too.
   **Done** (2026-10-25): `ClaudeModel._errors` turns that `TypeError` into
   the message for a missing key, for listing models and for a chat message;
   any other `TypeError` stays a bug. The test clears the `ANTHROPIC_*`
   variables and points the home directory away, so a profile from `ant auth
   login` on the machine does not hide the case. The OpenAI client sends
   "not-needed" as its key and gets the server's refusal instead.

*Do*, so that a GUI change is tested again on every pull request:

1. **A field test**, the probe as a pytest module: one test per editor of the
   property panel and per field of the axis form, over a fixture project that
   has every kind of object (each plot type, a 2 × 2 grid, an inset, a right
   axis, a color bar, a fit, a note, CSV and NumPy sources). It operates the
   editor like a user and checks: no crash, the model changes, undo restores,
   the figure draws, the image changes. Since the panel is generated from the
   model, a new field is in the test without anyone adding it. Fields that
   rightly change nothing visible in the fixture are listed with the reason,
   as U1 lists fields without an editor; that list shows the settings of item
   4. A crash takes the test run down: run each editor in a subprocess, or
   accept that a crash fails CI and say so.
   **Done** (2026-10-25): `tests/gui/test_every_field.py` over
   `tests/gui/everything.py`, one test per object (17), each going through all
   its fields and reporting every one that fails; a crash fails the run, and
   pytest-qt fails a test on any exception in Qt's event loop. `EXPECTED`
   lists fields whose right outcome is not a visible change, `KNOWN` the
   problems still open with their item. Marked `slow` (about a minute): CI
   runs it, `-m "not slow"` skips it while iterating. Fixed on the way: a
   separator of more than one character reached NumPy, which raised a
   `TypeError` nothing caught; `CsvSource.delimiter` is one character now.
   *Learned:* a widget in a folded section is not visible either, so the test
   opens every section first, or it skips them silently; a list is tried
   entry by entry until something visible changes, since its first entries
   are often what is drawn anyway ("outward" ticks, "stepfilled" bars).
   *Follow-ups:* choosing a column of another length for x breaks the figure
   until y follows, with a plain message; mark such columns in the list. A
   figure of 2 mm collapses its panels (Matplotlib warns); give the size a
   sensible lower bound. Width and height ratios: see item 2.
2. **Operation tests for what is not generated**: axis form, import, plot,
   fit and assistant dialogs, the outline's context menus, the data bar, the
   preview's zoom, pan and legend drag. Plus one test that triggers every
   `QAction` of the main window once on the fixture project: no exception, no
   raw message. A new action or dialog missing from the list fails the test,
   like U1.
   **Partly done** (2026-10-25): `tests/gui/test_every_action.py` triggers
   every menu action of the main window (found on the window, so a new one is
   tested without being listed) in a fresh window, and every entry of the
   outline's context menus for every object, undoing what each changed;
   dialogs are answered in the test, and no action may end in a message that
   figscribe calls a bug. Both tests are `slow`; CI runs the slow tests on
   Ubuntu with Python 3.13 only, which keeps the other jobs at their former
   two to three minutes (the field test alone added two to four to each).
   That job then took ten minutes; since decision 0028 every job runs the
   tests in parallel with pytest-xdist, and the sweeps are split to spread.
   *Open:* about twenty places in the dialog tests (import, images, fit,
   notes, chat) still set widgets with `setChecked` or `setCurrentText`;
   make them click, and add the preview's zoom, pan and legend drag with
   `QTest` mouse events.
3. **A manual checklist** in `docs/testing.md`, about 15 minutes, for what a
   test cannot judge: the result looks right; real mouse and trackpad on macOS
   and Windows; high DPI; dark mode; small window. Run before every release
   (part of B7) and for every pull request that changes what is seen.
   **Done** (2026-10-25): `docs/testing.md`, with what the automatic tests
   cover and eleven steps by hand.
   Found by hand the same day: check boxes were hard to see, a 1.45:1 edge
   from the Fusion style on white. They have their own look now (14 px, a
   4.3:1 edge, accent and a check mark when on, hover and focus), and the
   checklist asks for every control in each state.

*Done when:* items 1 to 5 above have failing tests and fixes; the field test
and the action test run in CI; `docs/testing.md` exists; how-to rule 10 holds.

---

## Phase 1 — The settings: complete, tidy, easy to find

The property panel is generated from the model (decision 0006), which keeps it
complete, but also shows the model's technical terms. This phase makes every
setting reachable, explained and phrased for a scientist, and moves rarely used
ones out of the way.

### U1 A test that no setting is forgotten — S

*Do:* a test that walks every field of every model class and asserts that it
- has a plain name in `gui/names.py` (`FIELD_NAMES`),
- has a tooltip in `TIPS` (today about 25 of about 90 fields have one),
- has an editor, or is listed in `SKIPPED` / `READ_ONLY` with a reason,
- has a placeholder if it is optional,
- is described for the assistant in `tools/spec.py`.

Then fill the gaps it reports. From now on a new field fails this test until it
is wired up everywhere.

**Done** (2026-10-24, decisions 0006 and 0008): `tests/test_field_coverage.py`
over 239 fields of 28 classes. Filled: 112 docstrings, 89 tooltips, 26 names,
14 texts for empty values. *Learned:* the assistant saw no field descriptions
at all, since pydantic only puts docstrings into the schema with
`use_attribute_docstrings`. Tooltips were keyed by field name and therefore
left out of nested fields, where names collide (`label`); they now go by
`"Class.field"` first. The "assistant description in `tools/spec.py`" became
the field's docstring, so it lives next to the field.

### U2 Plain terms instead of model terms — M

Concrete changes found in `gui/properties.py` and `gui/names.py`:

- **Counting from 1** on screen: *Row*, *Column* ("starting at 0") and *Header
  line (first = 0)* show 1-based numbers; the model stays 0-based.
- **Drawing order** as a number becomes *Bring to front* / *Send to back* in
  the context menu; the number moves to *More*.
- **Marker sizes**: lines say *Marker size (pt)*, points say *Marker area
  (pt²)*. One term, *Marker size (pt)*, everywhere; points convert to area for
  Matplotlib. `[decide]` whether the model field changes (schema bump) or only
  the panel converts.
- **Gaps between panels** (`hspace`, `wspace`) are Matplotlib fractions of the
  average axes size; show them in mm and convert.
- **Resolution (dpi)** only matters for PNG; move it from *Size* to an export
  section and say so.
- **Style sheet** as free text becomes a list of the bundled styles plus
  *Choose file…*.
- **Inset bounds**, **image extent**, **width/height ratios** as typed lists:
  inset bounds are set by dragging (see U4); extent gets four labelled fields;
  ratios get one field per row/column.
- **Colors**: four swatches today. Offer the ten of the current color cycle,
  recently used colors, and *same as …* another plot.

### U3 Find any setting quickly — M

- A **search field** on top of the property panel that filters fields by name
  and tooltip ("tick", "font", "legend").
- A **command palette** (Ctrl+K): every menu action and every setting of the
  selection, by typing.
- **Basic first**: per object type, the five most used settings open, the rest
  under *More*; decide the five from the bench cases and from what users ask
  the assistant.
- Settings that **apply to several objects**: select several plots in the
  outline and change color, marker size or line width for all at once (one
  undo step).

### U4 Change things where they are drawn — M

- Double-click an axis label, title, legend entry or note to edit its text in
  place.
- Drag the corners of an inset to resize it and the gap between grid panels
  to change the ratios (one undo step on release, like the legend).
- Right-click a plot: *Style like…*, *Bring to front*, *Fit…*, *Hide*.
- **Done** (2026-10-25, asked for by the user): in an axis' frame, the one
  drawn around it when selected, the wheel zooms and dragging pans that axis
  alone. Over the panel, Shift with the wheel still zooms x only and Ctrl or
  Alt y only. Clicking in the frame's gaps still selects nothing.

### U5 Missing everyday actions — S each

- **Duplicate** a plot, a panel, a figure (Ctrl+D).
- **Copy style / paste style** between plots (the format painter).
- **Same range in all panels** for x or y, from the panel's context menu.
- **Copy figure to clipboard** as PNG and SVG, for slides and documents.
- **Reveal data file** in the file manager.

---

## Phase 2 — What a scientist needs to analyse and publish

Ordered by how often the need comes up when evaluating measurements. Each new
artist or field goes through all four outputs (see "How to work", rule 5).

### F1 Fits that hold up in a paper — L

The fit core is sound (weighted `curve_fit`, 1σ, reduced χ², singular
covariance detected). Missing:
1. **Fit range**: fit only x in [a, b], typed or dragged in the preview; stored
   on `FitCurve`, applied in the script with a mask. Draw the curve over the
   fit range or the full range (option).
2. **Fixed parameters and bounds** per parameter in the fit dialog (bounds go
   to `curve_fit(bounds=...)`, fixed ones become constants of the model).
   Asked for by the user (2026-10-25): a start value that is kept as it is.
   **Done** (2026-10-25, decision 0029): `FitCurve.fixed` and
   `parameter_bounds`, in the fit dialog ("held", and a range per parameter),
   the assistant's fit tool, the script and the panel's result card.
   *Learned:* the field could not be called `bounds`, which an inset already
   has, since the panel's lists go by field name. A guessed start value
   outside a bound the user set is moved in; a typed one is refused.
   Changing a fit that is there: **done** the same day. "Change the fit…" on
   the panel's result card opens the dialog on the fit as it is (model, start
   values, held, bounds, label) and "Update fit" is one undo step
   (`fit.update_fit`); its residuals and its look stay as they are.
3. **Show the result in the figure**: a text box (a note bound to the fit)
   with chosen parameters as `value ± error unit`, rounded to two significant
   digits of the error as `names.with_error` already does; updates on refit.
4. **Export the result**: copy as text, CSV, or a LaTeX table row.
5. **Confidence band** (1σ) around the curve from the covariance, shaded.
6. **More models**: sine, power law, logistic, Voigt, sum of two Gaussians or
   Lorentzians, exponential with offset; templates for the custom expression.
7. **Weighting** choice: none, y errors (today's default), Poisson (√y).
8. `[decide]` **x errors**: orthogonal distance regression via `scipy.odr`
   when x errors exist, or document that they are ignored.

### F2 Leave points out, reproducibly — M

Click points in the preview to exclude them from a plot or a fit (outliers,
detector glitches). Stored as indices on the plot, shown hollow or grey,
emitted in the script as a mask with a comment. Also a row range per plot
("rows 100 to 2 000"). The data file stays untouched.

### F3 Panel labels for journals — S

(a), (b), (c) on each panel, automatically in reading order: style `(a)`,
`a)`, `a`, `A`, bold or not, position inside or outside the corner, font size.
A setting on `Figure`; insets get none by default.

### F4 Plot types that are missing — M each

In order of demand:
1. **Reference lines and shaded spans**: horizontal/vertical line at a value,
   shaded x or y interval (`axhline`, `axvline`, `axvspan`), with label.
2. **Error band**: a line with a shaded ±error region (`fill_between`), for
   dense data where error bars clutter.
3. **Hollow markers** and marker edge width; separate error bar color and cap
   thickness; *error bar on every n-th point* for dense data.
4. **Step plot** (drawstyle) for spectra and histograms of counts.
5. **Points colored by a third column**, with a color bar.
6. **Series with offset** (waterfall) for spectra or curves at several
   temperatures, with a colormap across the series.
7. **Contour lines** and filled contours for 2-D data.
8. **Bar chart** for categories.

### F5 Axes for publication — M

1. **Number format** of tick labels: automatic, fixed decimals, scientific
   (×10ⁿ at the axis end or per tick), and the **decimal comma** for German
   theses and journals. Per figure, overridable per axis.
2. **Invert** an axis (wavenumbers, binding energies).
3. **Second x axis on top** that converts the bottom one (wavelength ↔
   energy, temperature ↔ 1/T), from a small set of conversions or an
   expression, like the right y axis.
4. **Frame**: hide the top/right spines; offset spines.
5. `[decide]` **Date and time** axes for logged data.
6. `[later]` Broken axes.
7. `[decide]` **Which side an axis is on.** Matplotlib has four cases, and
   figscribe covers two:

   | Case | Matplotlib | figscribe |
   |---|---|---|
   | Tick marks on all sides, numbers only on one | `tick_params(top=True, right=True)` | `Figure.ticks_all_sides`, per figure |
   | The same axis, with numbers and label, on the other side | `yaxis.tick_right()`, `set_label_position("right")` | missing |
   | The same numbers on both sides | `tick_params(labelright=True)` | missing |
   | A second axis with its own scale and data | `twinx()` / `twiny()` | `Axes.y_right`; none on top |

   Proposal: keep placement and a second axis apart. `AxisSpec` gets `side`:
   `"left"`, `"right"` or `"both"` for y, `"bottom"`, `"top"` or `"both"` for
   x, set per panel, since in a grid with `share_y` the right column often
   wants its labels on the right. `y_right` stays the second axis with its own
   scale. While a panel has one, the right side is its: the command and
   `validate_references` refuse `side="right"` or `"both"` for y with a plain
   message, as B4 does. In the axis form a choice "Side: left / right / both",
   apart from the box "Second y axis with its own scale", whose tooltip says
   the difference. Nothing like it exists in the code yet (checked
   2026-10-25: no field, no `tick_right` or `set_label_position` in the
   renderer or the code generator). Questions:
   1. Are left/right/both enough, or also "label left, numbers right"?
      Proposed: enough; the split is rare.
   2. A second, independent x axis on top (`x_top`, `twiny`) along with it,
      like `y_right`? Not the same as item 3, which converts the bottom axis
      (`secondary_xaxis`); decide whether both are wanted.
   3. Adding a second y axis while `side="right"` is set: refuse and explain,
      or move the side back to the left? Proposed: refuse and explain.

### F6 Several files as one series — M

Import many files at once (a folder or a multi-selection) with the same
column choice, one plot per file, legend from the file name or a number in
it, colors from a colormap in file order. The everyday case of "the same
measurement at ten temperatures". The script loads them in a loop.

### F7 Data formats — M each

1. **HDF5** (in the brief's MVP, model class exists, reader missing): dataset
   browser in the import dialog, `h5py` as an optional extra.
2. **Tab/whitespace `.txt` and `.dat`** are already readable; make sure the
   import dialog's detection finds them, including several blanks.
3. `[decide]` **Excel `.xlsx`**: very common in labs, needs `openpyxl`;
   decide whether it is worth the dependency, or whether to say "save as CSV".

### F8 Several figures in one project — M

The model holds a list of figures, but the GUI and `figscribe script` only
use the first, and there is no *Add figure*. Add, duplicate, rename, reorder
and switch figures (tabs or the outline), *Export all*, and
`figscribe script --figure NAME` / `--all`. Asked for by the user
(2026-10-25): a scientist's project typically has several plots.

### F9 Reading values off the figure — S

A data cursor: hover shows the nearest point's x and y in the status bar; a
selected plot shows N, mean, standard deviation, min and max of its visible
data. Read-only, nothing stored: a quick look, not a statistics suite.

### F10 Questions of scope for analysis tools — `[decide]`

The brief excludes column formulas and a statistics suite. Some light analysis
is still asked for when plotting measurements. Decide each before building:
- **Scale and offset per plotted column** (unit conversion, baseline
  subtraction, normalise to maximum), stored on the column reference and
  written as one line in the script. Small, but touches the non-goal.
- **Smoothing** (moving average, Savitzky–Golay) as a derived plot.
- **Peak finding** (`scipy.signal.find_peaks`) that adds notes at the peaks.

---

## Phase 3 — Speed and working faster

### E1 The preview with large data (verified) — M

*Measured* (render plus draw, one panel, 150 dpi): line 1e6 points 86 ms,
points 1e6 389 ms, **error bars 1e5 616 ms, 1e6 5.8 s**. The preview renders
synchronously in the GUI thread on every change (`gui/preview.py`, `refresh`),
so each click in the property panel waits that long. The brief asks for fluid
interaction up to about 1e6 points, with downsampling in the preview only.

*Do:*
1. **Coalesce redraws**: changes within ~50 ms render once. *Done for zoom
   and pan* (2026-10-24, decision 0017): steps reuse the drawn figure, are
   drawn once per event loop pass and rendered again 300 ms after the last;
   150 → 49 ms per step on the example, 2.6 → 1.0 s with 1e5 error bars.
   Changes from the property panel still render at once.
2. **Render off the GUI thread**: show the previous image until the new one is
   ready; drop outdated renders.
3. **Downsample in the preview only**: per pixel column keep min and max for
   lines (looks identical), thin out points and error bars beyond what the
   pixels can show; export and script always use all data. Mark the preview
   while it is downsampled. Record the decision: it relaxes "the preview is the
   export" for large data only.
4. **A performance test** with budgets (marker `perf`, run in CI on Linux):
   1e6-point line and 1e5-point error bars stay under a stated time.

### E2 Never lose work — S

Autosave to a recovery file every minute while there are unsaved changes;
offer recovery on the next start after a crash. Keep the last saved version as
`.bak` when saving.

### E3 Start from your own figure — S

*Save as template*: a figure's size, fonts, ticks, colors and layout without
the data, offered on the start page next to the built-in layouts. Applying a
template to an existing figure is one undo step.

### E4 Fewer steps for the common path — S each

- The import dialog's proposed plot can be accepted with Enter, and *Fit…*
  is offered right after for error bar data.
- After *Add fit*, offer *Show result in figure* and *Add residuals*.
- Remember per file type the last import options and column choice.
- Keyboard shortcuts for every menu action and for switching panels.

---

## Phase 4 — M7: polish and release

### R1 Style templates for journals — M

Bundled `.mplstyle` files plus the figure settings that go with them (width,
fonts, tick direction, unit format, line widths): single and double column for
APS/AIP, Nature, Elsevier, ACS, IEEE, an A4 thesis page, and a 16:9 slide.
Include font choice: sans, serif, and math in Computer Modern or STIX
(`mathtext.fontset`), so figures match a LaTeX document; `[decide]` whether
to support full `text.usetex` (needs a LaTeX installation, breaks
"runs anywhere"). Colorblind-safe palettes (Okabe–Ito, Tol) as color cycles.
Applying a template is one undo step and shows what it changed.

### R2 Snapping and alignment guides — M

While dragging legends, notes and insets: snap to panel edges, centres and to
other objects, with guide lines; Alt disables snapping.

### R3 Export for every journal — S

TIFF (often required, with LZW compression) and EPS in addition to PDF, SVG
and PNG; transparent background option; *Export all figures*; a dpi override
at export time instead of a model field (see U2).

### R4 Release 0.1.0 — M

1. Merge `develop` into `main`, tag `v0.1.0`, publish to PyPI through the
   existing Trusted Publishing workflow (check it still builds with the new
   extras).
2. Installers: `[decide]` PyInstaller or Briefcase; one for each platform,
   built in CI; on macOS signing and notarisation need an Apple developer
   account — ask.
3. README: status "alpha", installation from PyPI, screenshots.
4. A small gallery in `examples/`: fit with residuals, 2-D map with color
   bar, histogram, multi-panel, series of spectra; each with its generated
   script, each in the codegen equivalence test.

### R5 The assistant: measure models (carried over from the brief) — M

Run `figscribe bench` against local models (7–8 B to 20–30 B, `--repeat 3`,
`--no-vision` where needed) and against ChatGPT and Claude Haiku 5.5, Sonnet 5.5,
Opus 5.5 as the reference; keep the `--json` files; improve tool descriptions
where local models fail; write down in the README which model size is good
enough for which request, and pick the default. New features from phases 1–3
get bench cases.

### R6 An application icon — S

One drawing as SVG, from which every size is made: the window and Dock icon
at run time, and `.icns` (macOS) and `.ico` (Windows) for the installers of
R4.2. It should take up the accent color and the start page's mark, and stay
legible at 16 px.

**Done** (2026-10-25, decision 0030): `gui/icons/figscribe.svg` and
`figscribe-small.svg` (up to 48 px); `theme.apply` sets the window icon;
`packaging/make_icons.py` writes `packaging/icons/figscribe.icns`, `.ico` and
a 1024 px PNG, which R4.2 can use as they are.

---

## Phase 5 — Later, optional

- Live data: watch a file and redraw when it grows (from the brief).
- Origin `.opj` import via liborigin (from the brief).
- `[decide]` A German user interface (Qt translations); number formats
  follow the figure setting from F5 regardless.
- Global fits sharing parameters across several data sets.
- Broken axes.

---

## Open decisions for the user

Collected from the tasks above, so they can be answered in one go. Record each
answer in `docs/decisions.md` when the task is started.

| Task | Question |
|---|---|
| B7.2 | Add `hypothesis` as a dev dependency for property-based tests? |
| U2 | Marker size: change the model field for points to a size in pt (schema bump), or convert only in the panel? |
| F1.8 | Fit with x errors via `scipy.odr`, or document that x errors are ignored? |
| F5.5 | Date and time axes? |
| F5.7 | Axis side: left/right/both enough? An independent x axis on top as well as the converting one? Refuse a second y axis while the y axis is on the right, or move it back? |
| F7.3 | Read Excel `.xlsx` (needs `openpyxl`)? |
| F10 | Scale/offset per column, smoothing, peak finding: in scope or not? |
| R1 | Support `text.usetex` in addition to mathtext with Computer Modern? |
| R4.2 | PyInstaller or Briefcase; is an Apple developer account available? |
| Phase 5 | German user interface? |
