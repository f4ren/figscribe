# Changelog

What changed in each release of figscribe. Project files written by a
release open in every later one.

## Unreleased

**Figures**
- Error bands: an error bar plot draws its y errors as a shaded band around
  the line, for dense data.

**Fixed**
- A color the panel refused no longer breaks the panel the next time it is
  built.

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
