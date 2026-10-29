# Changelog

What changed in each release of figscribe. Project files written by a
release open in every later one.

## Unreleased

- Residuals have a *Line width* (the joining line and the error bars) and
  the zero line is set apart: switch it off, or change its color, width and
  style. Saved files are drawn as before.
- A note can have a *Background*, white or any color, so it reads over a grid.
  Notes without one are drawn as before.
- Where am I: above the settings a path, such as *Scan › Panel A › X axis*,
  whose parts lead back to the figure or the panel with a click. The axes
  are rows in the outline, under their panel, and the axis chosen in the
  figure is the row selected there; a right-click offers the same range for
  all panels.
- *Help > About figscribe* shows the version of figscribe and of Python,
  Matplotlib and Qt, for bug reports. On macOS it stays under *Help*.

## 0.2.0 — 2026-10-29

**Figures**
- Several figures in one project: tabs above the figure, *Insert > Add
  Figure* (with the look of the shown one), duplicate, rename, reorder and
  delete from a tab or the outline; *File > Export All Figures…*;
  `figscribe script --figure NAME` and `--all`.
- Error bands: an error bar plot draws its y errors as a shaded band around
  the line, for dense data.
- The Allan deviation: σ_y(τ) of an evenly sampled series, frequency or
  phase, on log-log axes, for the stability of clocks, lasers and sensors.
  The script computes it with a few lines of NumPy, no extra package.
- The plot dialog shows the kinds as tiles, the columns as a sentence, a
  preview with the data, and which panel the plot goes to.
- Settings that do nothing in the current state are greyed out, and their
  tooltip says why.
- Units and a range per plot: show values in min, h, days, ms or by any
  factor, counted from the start if wanted, and draw, count and fit only the
  rows within a range of x. The axis, its marks and the plot's fits follow;
  the script converts with one line of NumPy per column.

**Finding things**
- A search above the property panel (Ctrl+F) keeps the settings whose name
  or explanation has the typed words.
- A command palette (Ctrl+K) finds any menu action or setting by typing.
- The property panel shows the settings used most first; the rest are
  under *More*.
- Several plots chosen with Ctrl or Shift in the outline: change their
  color, marker or line for all at once, or delete them together.

**Editing where it is drawn**
- Double-click an axis label, title, legend entry or note to edit it in
  place.
- Drag an inset's corner to resize it, or the gap between two panels.
- Right-click a plot: *Style like…*, *Bring to front*, *Send to back*,
  *Fit…*, *Hide*.

**Everyday actions**
- *Edit > Duplicate* (Ctrl+D) copies the selected plots, panel or figure.
  A panel comes with its plots, fits and insets, beside the original.
- *Copy Style* and *Paste Style* (Ctrl+Alt+C, Ctrl+Alt+V) give one or
  several plots the look of another, as one undo step.
- *Same x range in all panels* and *Same y range in all panels*, from a
  panel's menu in the outline or the preview.
- *Edit > Copy Figure* (Ctrl+Shift+C) puts the figure on the clipboard as
  PNG and SVG, for slides and documents. When figscribe closes, only the
  bitmap stays on the clipboard.
- *Show in Finder* (Explorer, file manager) on a data file in the outline.

**Fixed**
- With openai 3.38 or later, the assistant again says why Gemini refused a
  request and how long to wait at a rate limit.
- A color the panel refused no longer breaks the panel the next time it is
  built.
- The script names the encoding of a UTF-8 data file with letters beyond
  ASCII, so that it also reads the file on Windows.

## 0.1.0 — 2026-10-26

The first release to use: 0.0.1 and 0.0.2 only held the name on PyPI.

**Figures**
- Line, scatter and error bar plots, histograms, images and color meshes
  with color bars, notes of one or several lines with or without an arrow,
  reference lines and shaded ranges.
- Exact sizes in mm and pt; several panels in a grid, insets, shared axes,
  a second y axis on the right; panel letters for journals.
- Axes in plain terms: range, linear, log or symlog, major ticks every *n*
  with minor ticks between them, values shown with an SI prefix (Hz drawn
  as kHz), tick marks inward or outward and on all sides.
- Line widths of the frame, the ticks and the grid, and the grid's color and
  line style; an error bar plot's line has a width apart from its bars.
- Export as PDF, SVG and PNG.

**Data**
- CSV with automatic detection of delimiter, decimal comma, header and unit
  rows and text encoding; NumPy `.npy` and `.npz`.
- Each file is recorded with its SHA-256: a changed or moved file is
  reported, and its new version or new place taken on request.
- A data file can be removed with the plots that draw from it.

**Fits**
- Linear, polynomial, Gaussian, Lorentzian, exponential, or an expression of
  your own, weighted by the error bars, with residuals in a panel below.
- Fit only a range of x; hold parameters fixed or within bounds; change a
  fit that is already there; copy the result.
- Leave points out by right-clicking them, or have outliers found and left
  out on confirmation. The data file stays as it is.

**The generated script**
- Every figure as a standalone Python script that needs only NumPy,
  Matplotlib and, for fits, SciPy, and reads as if a person wrote it. A test
  compares its output with figscribe's own pixel by pixel.

**Working with it**
- Select in the figure or the contents list, edit in the property panel,
  undo every step. Zoom and pan with the mouse, one axis at a time over its
  frame; *Use as axis range* keeps the view.
- An assistant that makes changes described in words: Claude, ChatGPT,
  Google Gemini or a local model, built in (`figscribe[chat]`) or through
  MCP (`figscribe[mcp]`). It sees names, never the data values.
  `figscribe bench` measures how well a model does.
