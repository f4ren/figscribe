# Testing figscribe

## What runs by itself

`python -m pytest -q` runs everything, Qt offscreen. Two kinds of test cover
the GUI as a whole and need no upkeep when something is added:

- **`tests/gui/test_every_field.py`** operates every field of the property
  panel and the axis form, for each kind of object, on the project that
  `tests/gui/everything.py` builds: click, choose, type and press Enter. Each
  field must change the model, leave a figure that can be drawn, change what
  is drawn and come back with undo. A field whose right outcome is something
  else goes into `EXPECTED` with the reason; a known problem into `KNOWN`
  with its roadmap item, and the test says when it is fixed.
- **`tests/gui/test_every_action.py`** triggers every menu action of the main
  window and every entry of the outline's context menus. Dialogs are answered
  in the test; no action may end in an error that figscribe calls a bug.

Both are marked `slow`: `pytest -m "not slow"` skips them while iterating,
and CI runs them on one platform (Ubuntu, Python 3.13). Run the whole suite
with `-n auto --dist worksteal` (pytest-xdist, decision 0028): under a minute
instead of two and a half.
pytest-qt fails any test in which an exception reaches Qt's event loop.

Tests operate widgets as a person does: `click()`, `activated`,
`editingFinished`, `QTest` mouse events. `setChecked()` or `setCurrentIndex()`
alone skips the code a click runs; the crash of roadmap task B8.1 hid behind
exactly that.

## What a person checks

About 15 minutes, before every release and for every pull request that
changes what is seen. Use a real mouse or trackpad, on the platform at hand;
note the platform, the screen scaling and the theme in the pull request.

1. **Start**: open figscribe without a project. The start page shows; open
   `examples/gaussian-scan/scan.figscribe` from it.
2. **Look**: the preview equals an exported PDF of the same figure, by eye.
   Labels are not cut off; the property panel has no clipped text.
3. **Edit by hand**: change a color, a marker, the axis range and the title
   in the panel; each shows at once and undoes with Ctrl+Z (Cmd+Z on macOS).
4. **Zoom and pan**: scroll in the preview, drag, then adopt the view as the
   range; drag the legend. It feels fluid, and the view settles sharp.
5. **Import**: import a CSV with a semicolon and decimal commas, and one in
   cp1252 with µ in the header. The dialog proposes the right reading.
6. **Fit**: add a Gaussian fit with residuals; the result shows in the panel.
7. **A changed file**: edit the CSV in another program and come back; the
   bar offers the new version.
8. **Export**: PDF, PNG and the Python script; run the script, and its figure
   equals the export.
9. **Window**: shrink the window to 1024 × 700; everything stays reachable.
   With 150 % or 200 % screen scaling, icons and text are sharp.
10. **Theme**: switch the system to dark mode; text and lines stay readable.
11. **Keyboard**: go through the import dialog and the property panel with
    Tab and Enter only.

Anything wrong goes into the roadmap as a task with how to reproduce it, or,
if it can be tested, first into a failing test.
