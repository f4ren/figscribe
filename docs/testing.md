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
  with its roadmap item, and the test says when it is fixed. A field greyed
  out because it does nothing in that state is skipped there.
- **`tests/gui/test_without_effect.py`** checks each rule of
  `gui/effect.py`, which greys such fields out, against the renderer: while
  the rule holds, a change of the field leaves the figure as it was; once
  the setting it waits for is made, the same change shows. A new rule needs
  a case there, or the test fails.
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
   `examples/gaussian-scan/scan.figscribe` from it. The Dock or taskbar
   shows figscribe's icon, not Python's.
2. **Look**: the preview equals an exported PDF of the same figure, by eye.
   Labels are not cut off; the property panel has no clipped text. Every
   control is easy to find at a glance: check boxes, fields, lists, buttons,
   in each state (off, on, hovered, focused, disabled).
3. **Edit by hand**: change a color, a marker, the axis range and the title
   in the panel; each shows at once and undoes with Ctrl+Z (Cmd+Z on macOS).
4. **Zoom and pan**: scroll and drag in the preview, and in an axis' frame
   (the outline of the selected axis), which zooms and pans that axis alone;
   adopt the view as the range; drag the legend. It feels fluid, and the view
   settles sharp.
5. **Import**: import a CSV with a semicolon and decimal commas, and one in
   cp1252 with µ in the header. The dialog proposes the right reading.
6. **Fit**: add a Gaussian fit with residuals; the result shows in the panel.
   Show x in h with "Start at 0" and use only part of x: the axis, its range
   and the fit follow, and the fit's parameters are in h.
7. **A changed file**: edit the CSV in another program and come back; the
   bar offers the new version.
8. **Export**: PDF, PNG and the Python script; run the script, and its figure
   equals the export.
9. **Window**: shrink the window to 1024 × 700; everything stays reachable.
   With 150 % or 200 % screen scaling, icons and text are sharp.
10. **Theme**: switch the system to dark mode; text and lines stay readable.
11. **Keyboard**: go through the import dialog and the property panel with
    Tab and Enter only.
12. **Clipboard and file manager** (what no test can see): *Edit > Copy
    Figure*, then paste into a slide (PowerPoint or Keynote) and a Word or
    LibreOffice document; the picture has the figure's size and is sharp.
    Paste into Inkscape or a vector program too: the SVG stays vector. In the
    outline, right-click a data file and choose *Show in Finder* (Explorer,
    file manager): it opens with the file selected, also when the path has
    spaces and non-ASCII letters.
13. **About**: *Help > About figscribe* shows the version. On macOS the
    entry is in the *Help* menu, not in the application menu.
14. **Where am I**: select an axis in the figure and in the outline; the
    path above the settings leads back to its panel and the figure. With a
    right y axis and a long label, the outline rows stay readable.

Anything wrong goes into the roadmap as a task with how to reproduce it, or,
if it can be tested, first into a failing test.
