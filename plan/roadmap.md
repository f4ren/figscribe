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
- 0.1.0 is released (2026-10-26, R4): `main` at PR #78, on PyPI.

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
whenever the file is not plain ASCII. **Done** (2026-10-26): the script names
`"utf-8-sig"` for a file with a byte order mark, `"utf-8"` for one with any
other byte than ASCII, and nothing for plain ASCII.

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
   **Done** (2026-10-26): `tests/test_edge_data.py`, 55 column cases and 7
   images (slow; seconds on several cores). Nothing crashed; it found four
   things, all fixed: a file without rows said "column 'y' is out of range:
   has 1 columns" (now "has no rows of data"); the script of a histogram of
   one value failed (`ndmin=1`); an equal range was taken and widened by
   Matplotlib (now refused: "a range needs two different ends"); and a
   column of only NaN, or values at or below zero on a log axis or log color
   scale, vanished without a word (now in the problem list, given the data).
   *Learned:* fits with fewer points than parameters, and every other case,
   already refused or drew correctly.
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
   The same holds for an error bar plot's line width while its line style is
   "none" (issue #71), and for the grid's line width and style (F5.8).
   **Done** (2026-10-26): `gui/effect.py` holds the rules, each a set of
   fields, what they wait for, and when they do nothing. The panel greys
   such a field and its name out, and its tooltip starts with "Does nothing
   while …". The rules cover:
   - the grid's options while it is off;
   - the legend's while it is hidden, and its location while it was dragged
     into place;
   - a line's width without a line, and its marker size without a marker;
   - cap size and error bar width while no bars are drawn;
   - the left-out style while no points are left out;
   - a vertical reference line's y axis;
   - a hidden color bar's label;
   - a fit's curve and outside options without a fit range.

   `tests/gui/test_without_effect.py` holds every rule to the renderer.
   *Learned* from it: a vertical shaded range does depend on its y axis
   (on the right axis it lies in another layer), so it has no rule. Grid
   lines at minor ticks on axes without minor ticks are a combination, not
   a dead field: they are a problem in the list instead. A color mesh's x
   or y alone now does what its tooltip promised, numbering the cells along
   the other. That brought up two raw Matplotlib errors, now said in words:
   positions that do not fit the cells, and a single column chosen as an
   image or a mesh. The field test's project has positions and a second
   array for the mesh, and `KNOWN` is empty.
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

**Done** (2026-10-24, decision 0006), except the gaps between panels, now
U6. Marker size: the panel converts, the model keeps the area (answered).
*Learned:* *Drawing order* was already under *More*; the context menu now
has *Bring to front* / *Send to back*. There are no bundled styles yet, so
the list offers Matplotlib's (R1 adds its own). Eleven swatches in one row
made the whole form wider than the panel and clipped every field; they go
six to a row. Inset bounds stay a typed quad until U4 makes them draggable.

### U6 Gaps between panels in mm — M

`hspace`/`wspace` are fractions of the average panel size, and with the
automatic layout they come on top of the space for labels. Measured: 0.2
gives 18 mm at 60 mm figure height and 24 mm at 120 mm; 0 still leaves
14.5 mm for an x label. A gap in mm therefore needs model fields in mm and a
conversion in the renderer and the code generator (Matplotlib's constrained
layout has pads in inches, `h_pad`/`w_pad`, which may serve); a conversion
in the panel alone would be wrong as soon as the size or labels change.
`[decide]` the model change, with a schema bump, before building it.

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

**Done** (2026-10-26, decisions 0038 and 0039): the search above the
property panel (Ctrl+F) and the command palette (Ctrl+K); the basic
settings per kind of object first, the rest under *More*; several plots
chosen with Ctrl or Shift in the outline, changed together or deleted as
one undo step. *Follow-ups:* the preview marks only the last of several
plots chosen; a right-click on one of several chosen chooses it alone.

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

**Done** (2026-10-26, decision 0040): double-click editing of axis labels,
titles, legend entries and notes; dragging an inset's corner and the gaps of
the grid, one undo step on release; a right-click on a plot with *Style
like*, *Bring to front*, *Send to back*, *Fit…* and *Hide*. *Follow-ups:* a
title not set yet cannot be double-clicked, there is nothing drawn; a
column's share from a drag is approximate under constrained layout.

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
   **Typed: done** (2026-10-26, pulled forward at the user's request):
   `FitCurve.fit_range` and `extend_curve`; the dialog fits only the points
   in range ("17 of 41 points"), guesses untyped start values from them, and
   draws the curve over the range where there is data unless told to span
   all of it; residuals show the fitted points; the script uses a named mask
   `in_range`. *Open:* dragging the range in the preview.
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
   **As text: done** (2026-10-26, asked for by the user): the result card's
   values can be selected, "Copy the result" copies parameters, χ²ᵣ and the
   residuals, and the card now tells the points fitted, the residual RMS
   and the largest residual with its row (`fit.residuals`). *Open:* CSV and
   a LaTeX table row.
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

**Decided with the user (2026-10-26)**, pulled forward after F1.1:
- Left-out points are stored **on the plot**, so every fit of it skips them,
  and are drawn in **another color**, light grey by default; the color and,
  if wanted, a marker of their own can be set.
- **Finding outliers** in the fit dialog: points whose residual exceeds k·σ
  (k = 3; σ the point's error bar, or a robust scatter (MAD) without one),
  refitting until nothing changes. They are **proposed**, and only left out
  once the user confirms; they then join the same list, with a note on how
  they were found. Not a rule stored on the fit: a list stays the same when
  fitted again and reads plainly in the script.
- Order: leaving points out by hand (right-click a point in the preview),
  then finding outliers.

**By hand: done** (2026-10-26): `left_out`, `left_out_color` and
`left_out_marker` on line, scatter and error bar plots; right-click a point
in the preview, "Leave out row 13" or "Take row 13 back in" (rows counted
from 1 on screen, from 0 in the model), which fits every fit of the plot
again in the same undo step and is refused if a fit would lack points; the
assistant's `set_field` on `left_out` does the same. Residuals skip them
too; the script names the mask `kept`. *Learned:* the click must pick the
nearest point over all drawn parts, since the kept line also lies within
the pick radius of a left-out point. *Open:* ~~a row range per plot~~
(planned as F11, by x values); the panel shows which rows are left out
only in the preview.

**Finding outliers: done** (2026-10-26): "Find outliers" in the fit dialog
proposes the points beyond k·σ (`fit.outliers`, iterated until the set
settles); "Leave them out" shows the fit without them, and only "Add fit" or
"Update fit" leaves them out of the plot, with the fit as one undo step and
`left_out_note` ("rows 11, 31: more than 3σ off the Gaussian fit"), which
the panel lets the user edit and the script prints. Also fixed: the dialog
fitted the plot's left-out rows, which `refit` skipped.

**The look, as the user asked (2026-10-26):** markers are chosen from a list
of every Matplotlib marker, each drawn (`gui/markers.py`), instead of four
buttons and a text field. A left-out point's marker is "like the plot" by
default (`"same"`), and "no marker" means none, as for the plot. A line runs
on through the left-out rows in their color, with `left_out_linestyle` (like
the plot by default, "none" for a gap), instead of joining the kept points
across them. Also asked for: a fit can draw the plot's points outside its range
like left-out ones (`outside_as_left_out`, a switch in the fit dialog and the
panel; only drawn so, not left out), and a marker list ends in "Custom…",
which asks for any Matplotlib marker such as `$\alpha$`. *Follow-up after U2
is merged:* remove the old `MarkerEditor` and its four `MARKERS` from
`gui/properties.py`, no longer used, and move the `QInputDialog` import of
`ask_marker` up to the others; both wait because U2 changes those lines.
**Done** (2026-10-26), with the theme's marker icons, which only it used.

### F3 Panel labels for journals — S

(a), (b), (c) on each panel, automatically in reading order: style `(a)`,
`a)`, `a`, `A`, bold or not, position inside or outside the corner, font size.
A setting on `Figure`; insets get none by default.

**Done** (2026-10-26, decision 0033): `Figure.panel_labels`, switched on in
the figure's *Style* section; style `(a)`, `a)`, `a` or `A`, bold, outside
or inside the top left corner, font size, and insets on request. The script
letters the panels in one loop. *Learned:* `ax.annotate` with
`textcoords="offset fontsize"` keeps the gap in step with the letter's size,
and the constrained layout makes room for it outside. *Follow-ups:* a panel
of residuals usually shares the letter of the plot above it: a switch per
panel to leave it out of the lettering. An inset lettered outside its corner
sits in its parent's plot and may meet the parent's title when the inset is
at the top.

### F4 Plot types that are missing — M each

In order of demand:
1. **Reference lines and shaded spans**: horizontal/vertical line at a value,
   shaded x or y interval (`axhline`, `axvline`, `axvspan`), with label.
   **Done** (2026-10-26, decision 0034): `ReferenceLine` and `ShadedSpan`,
   vertical or horizontal, grey by default, the range light and behind the
   data. *Insert > Add Line or Range*, the same in a panel's context menu in
   the outline (in the middle of what the panel shows), and a right-click in
   the preview, which puts one where it was clicked; values are rounded to a
   hundredth of the shown range. The problem list reports one at or below
   zero on a log axis. *Follow-ups:* drag a line or a range's edges in the
   preview, like a note; ~~the panel offers "y axis" for a vertical line,
   where it does nothing~~ (greyed out since B8 item 4).
2. **Error band**: a line with a shaded ±error region (`fill_between`), for
   dense data where error bars clutter.
   **Done** (2026-10-26, decision 0035): `ErrorbarPlot.band`, a check box
   "Error band" in the plot's "Look", draws the y errors as a band in the
   plot's color (or its own) just behind the line, with a gap at left-out
   rows; x errors stay bars, fits are weighted as before. A band without y
   errors is reported in the problem list. Typing a refused color into any
   color field no longer breaks the panel the next time it is built (the
   color was remembered before it was checked). *Follow-ups:* the legend
   could show the band behind the line; ~~cap size and error bar width show
   but do nothing while a band has no x errors beside it~~ (greyed out since
   B8 item 4).
3. **Hollow markers** and marker edge width; separate error bar color and cap
   thickness; *error bar on every n-th point* for dense data.
4. **Step plot** (drawstyle) for spectra and histograms of counts.
5. **Points colored by a third column**, with a color bar.
6. **Series with offset** (waterfall) for spectra or curves at several
   temperatures, with a colormap across the series.
7. **Contour lines** and filled contours for 2-D data.
8. **Bar chart** for categories.
9. **Allan deviation** (asked for by the user, 2026-10-26; decision 0036):
   σ_y(τ) of a time series against τ, on log-log axes, the standard figure
   for the stability of clocks, lasers, gyroscopes and sensors. A plot type
   of its own, computed like a histogram is: the model stores what is
   computed, the renderer and the script compute it with the same NumPy.
   - **Input**: one column of fractional frequency values y, or of phase
     x in s; the sample interval τ0 as a number, or from a column of times
     (refused, with a message, when the times are not evenly spaced).
   - **Variant**: overlapping ADEV first. From phase x (for frequency data
     x = τ0 · cumsum(y), with a leading 0), N phase points and τ = m·τ0:
     σ²(τ) = Σ (x[i+2m] − 2x[i+m] + x[i])² / (2 τ² (N − 2m)). Modified
     ADEV, Hadamard deviation and time deviation later, as a choice.
   - **τ values**: octaves (m = 1, 2, 4, …) by default, or decades (1, 2,
     5, 10, …), or every m; up to m = (N − 1) // 2.
   - **Error bars**: σ / √(N − 2m) at first; χ² confidence intervals
     (equivalent degrees of freedom, `scipy.stats.chi2`) later.
   - **Adding one** sets both axes of the panel to log and labels them
     τ (s) and σ_y(τ), as adding residuals sets up their panel.
   - **The script** defines a short function `overlapping_adev(phase, tau0,
     m)` and calls it; no `allantools`.
   - **Not offered**: points left out (F2), which would cut the series;
     NaN in the column is a problem in the list, not silently skipped.
   - **Tests**: the reference values in NIST SP 1065 (section 12, the
     1000-point test set), white frequency noise falling as τ^(−1/2) with
     the known level, both inputs (frequency and phase) giving the same
     curve, and the pixel equivalence of the script.

   **Done** (2026-10-26), as planned:
   - `AllanDeviationPlot` ("allan"), computed in `figscribe/allan.py`;
     the script defines `overlapping_adev` and repeats the steps.
   - A tile in the plot dialog, with "Values" and an optional "Times".
   - Added to an empty panel, the axes become log-log, τ (s) against
     σ_y(τ).
   - "Sample interval" is greyed while a column of times gives it.
   - A series with gaps is not drawn, in figscribe and the script alike,
     and the problem list says so; uneven times are refused in words.

   Checked against `allantools` outside the repository: agreement to 10⁻¹⁴
   for every spacing and for phase input. The NIST test series gives
   0.2922319 at τ = 1 and 0.09159953 at τ = 10, as published, and its
   mean 0.4897745 (the series starts with the seed itself).
   *Learned:* `2 ** np.arange(64)` overflows to a negative number at 2⁶³,
   which then passes `m <= top`; 62 octaves are enough. In the edge-data
   matrix, values at or below zero on a log axis are no problem for an
   Allan deviation: the axis shows σ, not the values.
   *Follow-ups:* modified ADEV, Hadamard and time deviation as a choice;
   χ² confidence intervals; the plot dialog could pick a column named "t"
   or "time" as the times.

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
8. **Line widths of frame, ticks and grid.** Journals ask for a frame and
   ticks of a stated width (often 0.5 to 1 pt), and a fine or dotted grid.
   **Done** (2026-10-26): per figure, as the tick direction is, so that every
   panel matches: `frame_width`, `tick_width`, `tick_length`,
   `minor_tick_width` and `minor_tick_length`, in pt, each empty for the
   style's. They become rcParams (`axes.linewidth`, `xtick.major.width`,
   …), which the script sets in the one `plt.rcParams.update` it already
   writes for the ticks; the frame width also reaches the colour bar's
   outline, as in Matplotlib. Per panel, beside the grid color:
   `grid_linewidth` and `grid_linestyle` (solid, dashed, dotted,
   dash-dotted; "none" is not offered, it would be no grid).

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
(2026-10-25): a scientist's project typically has several plots. The toolbar
adds things in the order a figure is built (Data, Panel, Plot, Fit, Note,
since 2026-10-26); *Figure* joins it after *Data*, as the user proposed.

**Done** (2026-10-26, decision 0037): a tab bar above the preview while a
project has several figures (the user's choice: tabs and the outline), the
same menu in both (rename, duplicate, move, delete), *Insert > Add Figure*
and *Duplicate Figure*, *Figure* in the toolbar, *File > Export All
Figures…*, `figscribe script --figure NAME` and `--all`. A new figure takes
the shown one's look. *Follow-ups:* the assistant's preview and script tools
use the shown figure and cannot name another; a figure from a template.

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
  *Decided* (2026-10-26, decision 0041): a factor and a start at zero per
  plot and axis, on the data, with a range per plot; planned as F11.
  Baseline subtraction and normalising stay open.
- **Smoothing** (moving average, Savitzky–Golay) as a derived plot.
- **Peak finding** (`scipy.signal.find_peaks`) that adds notes at the peaks.

*Decided in part* (2026-10-26, decision 0036): an analysis is in scope when
it is a standard figure of a field, a few lines of NumPy or SciPy in the
script, and a plot with a few settings; the model stores what is computed,
never the result. The Allan deviation is the first (F4.9). The three above
are judged by the same points when they come up.

### F11 Units and a range per plot — M

Asked for by the user (2026-10-26): show times in min, h or days, counted
from the start, and draw a plot over part of its data only. Decided with
the user in decision 0041: the conversion acts on the data, it can start at
zero, and the range is given in x values.

1. **Model.** `Conversion(factor > 0, from_start: bool, unit: str | None)`;
   `x_conversion` and `y_conversion` (None by default) on line, points and
   error bars, `x_conversion` on a histogram (its values) and an Allan
   deviation (τ, factor only: `from_start` does nothing there and is greyed
   by a B8.4 rule). `x_range: tuple[float, float] | None` on the same five,
   ordered like `fit_range`, in shown values. Shown = (value − nanmin) ×
   factor; errors and bands × factor. Defaults leave every 0.1.0 file as it
   is, so no migration.
2. **One place for the arithmetic**, used by renderer and code generator,
   as `render/ticks.scaling` is for the prefix: the converted column, the
   kept rows of a plot (range, then left-out rows, then non-finite x), and
   how the script writes the factor (`/ 3600`, `* 1000`).
3. **Renderer.** Lines, points and error bars draw only the rows in range;
   left-out rows outside it are not drawn. A histogram counts the values in
   range, with the bins of a bin count spanning it (`np.histogram`'s
   `range`). An Allan deviation takes the samples whose time since the
   first lies in range, τ0 unchanged; its τ are then converted.
4. **Fits and residuals.** A fit and its residuals use the converted, kept
   rows; its `fit_range` must lie within `x_range` (else a problem in the
   list). A command for the conversion converts the plot's `x_range` and its
   fits' `fit_range` along and fits again in the same undo step, refused
   like leaving a point out when a fit then has too few points or fails;
   held values and bounds stay as typed.
5. **The axis follows**, in the same step: its unit text becomes the
   conversion's unit when it was the old one or empty; its fixed limits,
   ticks, step and the reference lines, ranges and notes on it are
   converted along when no other data plot is drawn against that axis.
6. **Code generator.** One line per converted column, named after column
   and unit (`t_h`, `t_scaled` without a unit, numbered on a clash), with a
   comment ("h since the start"); the range joins the plot's `kept` mask.
   Equivalence cases: error bars with both conversions, a band and a fit;
   a histogram with a range; an Allan deviation with a conversion and a
   range.
7. **Property panel.** In the plot's data section: "x in" with "as in the
   file", "min (÷ 60)", "h (÷ 3600)", "days (÷ 86 400)", "ms (× 1000)" and
   "another factor" (factor and unit fields); "Start at 0"; and "Use only x
   from … to …" (for a histogram "values", for an Allan deviation "times").
   Names, tooltips, a field-test object in `everything.py`.
8. **Problem list and edge data.** A range with no rows in it; a fit range
   outside the plot's range; an Allan range with a gap or too few samples;
   a conversion of a column that is all NaN. Cases in the edge matrix.
9. **Assistant.** `set_field` on the new fields goes through the same
   command as the panel, so the fits are run again; `tools/spec.py` names
   them.
10. **Docs.** CHANGELOG, README, the manual checklist in `docs/testing.md`.

**Done** (2026-10-27, decision 0041): `convert.py` holds the arithmetic,
`units.py` the commands `set_conversion` and `set_range`, which the panel
and the assistant's `set_field` both use; equivalence cases for error bars,
a histogram and an Allan deviation, a baseline image `converted`, edge cases
and a line in `everything.py` with a factor of its own and a range. Unlike
item 1, "Start at 0" is not offered for an Allan deviation rather than
greyed: no state would make it count, and a greying rule needs one.
*Learned:* the axis's unit can only follow when it is known what it showed
before, so a conversion without a unit counts the axis's own; the script
needs the range as a mask apart from `kept`, which also marks the rows drawn
apart.

*Follow-ups, only if asked:* the conversion in the plot dialog; dragging
the range in the preview; a row range; converted positions of a color
mesh; date axes (F5.5) for timestamps instead of hours since the start.

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
- **The plot dialog** (asked for by the user, 2026-10-26: "looks unloved").
  **Done**: in the import dialog's look. The kinds are tiles with icons,
  and a kind without data is disabled and says what it needs. The columns
  read as a sentence ("Plot U against t ± dU"), by name when there is one
  file. Only the fields of the chosen kind are shown. A column named as the
  error of y is taken, and starts error bars. A preview draws the plot with
  the data through the renderer. "to Panel A ▾" says where it goes, with "A
  new panel to the right" in the same undo step. An empty panel gets its
  axes named after the columns, as after the import. Enter adds the plot.
  *Learned:* a focused QPushButton in a dialog becomes the default button
  unless `autoDefault` is off, so Enter on a tile chose the tile; and a
  button box built from Cancel alone plus a custom Accept button made
  Cancel the default. *Follow-up:* the import dialog's "Choose columns
  myself…" opens this dialog after the import, a second step; it could be
  part of the import dialog instead.

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

*Pulled forward* (2026-10-26, asked for by the user): 0.1.0 goes out as an
alpha from the state of `develop`, before phases 1 to 3 are finished, so
that others can install it with `pipx install figscribe`. Items 1 and 3 are
done for it, without screenshots; 2 and 4 stay open for a later release.
The version is 0.1.0, the classifier "Alpha", the release notes are in
`CHANGELOG.md`, which each later release extends. A wheel built from this
state installs into a fresh environment, and `figscribe script` writes a
script from the bundled example that runs there. From now on, project files
of a release must open in later ones (rule 9 above).
**Released** the same day: PR #78 brought `develop` into `main`, the GitHub
release `v0.1.0` ran `release.yml`, and `pip install "figscribe[chat]"` from
PyPI into a fresh environment starts the window and writes a working script
from the example.

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

### R7 The assistant without paying per request — S

Asked for by the user (2026-10-26): can a subscription (Claude Pro/Max,
ChatGPT Plus) or a free model be used? A subscription cannot sign in to the
API from another application, but it can drive figscribe through MCP.
Offer Google Gemini, whose API has a free tier, as a server by name, and say
in the README which ways cost nothing or use a subscription.

**Done** (2026-10-26, decision 0032): "Google Gemini" in the assistant's
servers, with its key from `GEMINI_API_KEY` (an OpenAI key is no longer sent
to it); Gemini 3's thought signatures go back with its tool calls; a rate
limit says how long to wait; README "Without paying per request". Decision
0030 was taken twice by parallel branches; the later one, points left out,
is now 0031.

Learned against the real API (2026-10-26): the free tier allows 5 requests
a minute and 20 a day per model (one change takes two to four);
`gemini-2.5-flash` is "no longer available to new users";
`gemini-3.8-flash` and `gemini-flash-latest` did not answer within a minute;
`gemini-3.5-flash` worked and passed the one bench case run before the daily
limit was reached.

Follow-up: **wait out a rate limit** in the chat when the server says how
long (up to a minute), with the countdown shown, instead of stopping the
request halfway. `figscribe bench` could then run on a free tier too.

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
| U6 | Gaps between panels in mm: new model fields in mm (schema bump), converted by the renderer and the code generator? |
| F1.8 | Fit with x errors via `scipy.odr`, or document that x errors are ignored? |
| F5.5 | Date and time axes? |
| F5.7 | Axis side: left/right/both enough? An independent x axis on top as well as the converting one? Refuse a second y axis while the y axis is on the right, or move it back? |
| F7.3 | Read Excel `.xlsx` (needs `openpyxl`)? |
| F10 | Smoothing, peak finding, baseline and normalising: in scope or not? (Judged by decision 0036; unit conversion decided in 0041.) |
| R1 | Support `text.usetex` in addition to mathtext with Computer Modern? |
| R4.2 | PyInstaller or Briefcase; is an Apple developer account available? |
| Phase 5 | German user interface? |
