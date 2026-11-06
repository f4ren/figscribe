# Changelog

What changed in each release of figscribe. Project files written by a
release open in every later one.

## Unreleased

- **Fixed: a double click on a project in Finder opens the project.** The macOS
  app started but showed the start page, because macOS sends the file to a
  running program as an event instead of an argument. The app also says now that
  it opens `.figscribe` files, so Finder offers it for them (decision 0066).
- Fixed: the first release of the installers (0.3.0) carried a fourth file, the
  tool that builds the AppImage, next to the three installers. It is removed from
  that release and no longer kept where the workflow collects installers.

## 0.3.0 — 2026-11-05

- **Installers for macOS, Windows and Linux.** Each release carries a disk image
  for Apple silicon Macs, an installer for Windows and an AppImage for Linux, so
  figscribe runs without Python or `pip`. They are not signed: macOS asks once to
  confirm opening the app (right-click, *Open*), and Windows SmartScreen shows
  "More info", then "Run anyway". The AppImage needs `libxcb-cursor0`. Intel Macs,
  ARM Linux and `.deb`/Flatpak are not built; `pip install` works everywhere
  (decision 0066).
- **The installers carry the licenses of what is in them.** A
  `THIRD-PARTY-NOTICES.txt` lists the packages in each installer, with their
  license texts, the LGPL for Qt with where its source is, and Python's license;
  `LICENSE.txt` is figscribe's own. They are in the program's `licenses` folder,
  beside the app in the macOS disk image, in the install folder on Windows (whose
  installer shows the license first) and in the AppImage. An installer is not
  built when a package it contains has no license file.
- *Help > About figscribe* says which licenses figscribe is under: MIT, Qt (through
  PySide6) under the LGPL-3.0, and where the licenses of the rest are.

- **Fixed: a script written into a folder behind a link could not find its
  data.** The script works out its folder with every link followed, but the
  path to the data was worked out from the folder as it was named, so on macOS
  (where `/tmp` and the temporary folders are links) it was off by a level.

- **Export as TIFF and EPS, and with a transparent background.** *Export
  Figure…* and *Export All Figures…* offer TIFF (LZW compressed, at the figure's
  dpi) and EPS; *File > Export with a Transparent Background* leaves out the white
  background of PNG, TIFF and SVG.
- **An Allan deviation can be fitted.** *Fit…* is offered on it, with
  the error bars as weights, a fit range in τ, a smooth curve along the log axis
  and residuals; the generated script fits the same points. A new *Power law*
  model (a·x^b) fits the slope of white noise, −1/2.
- **Unsaved work survives a crash.** Every minute figscribe writes the changes
  not yet saved to `<project>.figscribe.autosave` next to the project (for an
  untitled project, to its data folder); the next time the project is opened it
  offers to recover them. A save or a close removes the file.
- **Histogram, Allan deviation, image and color mesh have their settings
  arranged: *Label and data* says what is plotted, *Look* how; the
  color bar is one box with its settings under it (it was a box and a section),
  and an image's extent, first row and pixel shape are in the folded *Pixel grid*.
- **A fit and its residuals have their settings arranged: the fit's
  result card sits under *Label and data*, *Look* has how the curve is drawn,
  and the residuals' zero line is a section of its own, a box with its settings
  under it.
- **A note, a reference line and a shaded range have their settings in sections
  by what they are for: a note has *Text* and
  *Place* (with *Position in*, which its position is read in), lines and ranges
  *Label and data* with *Legend entry* first, then *Look*.
- **Fixed: the script of a fit whose range keeps no row.** After narrowing the
  range of a fitted plot (or of the fit) to one without a point, the exported
  script stopped with "`ydata` must not be empty". It now draws no fit, as the
  figure does, and says why in a comment; the problem list says so too, at the fit.
- **The settings of an axis are found with Ctrl+K.** *log*, *symlog*, *limits*,
  *range*, *ticks*, *prefix* and more find the axis's scale, range, ticks and
  label, also when only the panel or a plot is selected: choosing one opens that
  axis on the setting. A setting that waits for another, such as *Linear within ±*
  on a linear axis, is no longer offered.
- **A note's arrow is made in the figure.** Right-click a note and choose *Add an
  arrow*; select the note and right-click where the arrow should point:
  *Point the note's arrow here*. *Remove the note's arrow* takes it away. The
  numbers in the property panel still work, and their tip says how to do it by
  clicking.
- **Finding by what a thing is known as.** *Find Setting or Action* (Ctrl+K)
  now also knows other words: *band*, *region*, *highlight* or *threshold* find
  the shaded range and the reference lines, *arrow* and *callout* the note,
  *heatmap* the color mesh, *residuals* the fit, *downsample* the setting
  *Fewer points*, and so on. An entry found by its name comes before one found by
  another word. The empty property panel says where to look.
- **The toolbar's adding buttons show what they make.** *Data*, *Figure*,
  *Panel*, *Plot*, *Fit*, *Note* and a new *Reference* each have a picture of
  their own instead of the same plus, in two groups (what holds, and what goes
  into a panel). *Plot*, like *Panel* and *Reference*, opens a menu with *Add Plot…*
  and the kinds (*Histogram*, *Allan deviation*, *Color mesh* …), which opens
  the dialog on the one chosen; the entries of these menus have pictures;
  *Reference* adds a vertical or horizontal line or a shaded range. *Insert >
  Add Line or Range* is now *Insert > Add Reference*, and *Insert > Add Plot
  As* lists the kinds. In a narrow window the toolbar shows the icons alone
  instead of hiding buttons behind the » menu.
- **A gallery of twelve examples on the start page**, with a picture each: a
  Gaussian scan, a noisy sensor (the means of a minute over the raw line), an
  RC discharge, a freezing plateau (°C by a formula, a second axis), a
  resonance, a diode's current on a symmetric log axis, a growth curve, a
  calibration, a distribution, the stability of a clock, a beam profile (a color
  map) and a paper figure. A click asks for a folder and opens a copy of the
  example there. The data are generated, not measured. On the start page, the recent
  projects now come before the layouts and the examples, *New to figscribe?*
  has *Try an example* (scrolls to the gallery) and *How it works* (the README's
  *Getting started*) next to *Describe it instead*, and the date of a recent
  project is written in English whatever the system language.
- **New figures have inward tick marks on all four sides**, as many journals
  want, and the figure's settings are arranged by what they are for: *Format*
  (name, size, PNG resolution, style sheet), *Text* (font size, units in
  labels, panel letters), *Ticks and frame* with the two tick settings in view,
  their widths and lengths and the panel layout (folded). Saved projects keep
  their own ticks. A thin line now separates the sections of the property
  panel, as the design had always meant, and every section folds with a click
  on its title; the panel remembers it for each kind of object while you work. The
  section titles are larger (14 px, as large as the figure's name in the outline;
  the object's title 17 px), to be read at a glance.
- **A panel's settings are arranged by what they are for:** *Title and axes*
  (the title, then the cards of the axes, the right y axis with its card right
  after its box), *Grid* (the box with all its settings under it, no longer
  hidden under *More*), *Legend*, and the folded *Place in layout*. The legend's
  *Columns* is *Columns of entries*, and its *Position* is *Position (dragged)*.
- **The axis form has three sections:** *Label* (with the label's size and
  distance), *Scale* (type, range, the linear zone of a symmetric log axis and
  the size of the numbers) and *Ticks* (major and minor, the row under the major
  ticks says *Distance* or *Values*). A section folded on an axis stays folded.
- **The settings of a line, points or error bar plot are arranged by what they
  are for:** *Label and data* (the legend entry is *Legend entry*), *Units and
  rows* (with *Fewer points* right under its box), *Look* (marker size and line
  width next to their marker and line), *Error bars* (the band under its box) and
  the folded *Left-out points* and *More*.
- **A formula for a plot's units.** *x in* and *y in* offer "a formula" next to
  "another factor": `x / 60 - 273.15`, `(x - 32) / 1.8`. It is written in `x`
  and numbers and must be linear and rise with x, so that error bars, axis,
  marks, ranges and fits follow as they do for a factor; the start (*Start at
  0*) is taken off first. The script shows the formula in Python's spacing. For
  the τ of an Allan deviation it may scale but not shift, e.g. cycles of 2.88 s
  in hours as `x * 2.88 / 3600`. Saved files are drawn as before.
- **Fewer points drawn.** A line, points or error bar plot can show the mean
  or median of every *n* rows, every *n*-th row, or the mean over intervals
  of x (*Fewer points*, under *Data*). The data file stays as it is; the
  figure, the export and the script show the reduced points and fits use
  them. An averaged point has its standard error as error bar (propagated
  when the plot has y errors); the median has none. Rows left out count as
  before and can be replaced by the mean of their neighbours. While a plot is
  reduced, leaving rows out and finding outliers are off. Saved files are
  drawn as before.
- Fixed: *Save As* into another folder no longer loses the data (every file was
  "missing" there). A data file outside the project's folder, or imported before
  the first save, is now stored relative to the project (`../data/scan.csv`),
  where it used to be stored by its whole path, so a project and its data can be
  moved or shared together; a file on another volume or drive keeps its whole path.
- Fixed: the script of a plot with fewer points drawn stopped with an error
  when its range of x kept no row; it now draws no point, as figscribe does.
- **Saving cannot destroy the saved project.** The project is written to a
  temporary file and put in place when that is complete, so a full disk or a
  lost share leaves the last saved version; that version also stays next to it
  as `NAME.figscribe.bak`. A project made read-only is still refused. Project
  files are written with the same line ends on every platform.
- **Export remembers its format and folder.** *Export Figure…* and *Export All
  Figures…* open in the folder last used with the format last chosen, and
  suggest the figure's name as the file name; a name typed without a suffix gets
  the chosen format's.
- Fixed: `figscribe script` showed a Python traceback when it could not write
  the script (a folder that is not there, a read-only one); it now says so
  in one line.
- Fixed: *Add Panel* and *Duplicate* on a panel of a grid whose column
  widths or row heights do not match its columns or rows (after the number
  of columns was changed while widths were set, say) stopped with an error;
  they now say what to put right.
- Fixed: the fit dialog no longer fails on data near the limits of floating
  point (about 1e-300 or 1e300), says in words when a fit stops because the
  model is not finite for values it tried, and says which uncertainties
  cannot be estimated when the data does not determine a parameter.
- Fixed: the residuals, and the count of points fitted, no longer include
  points whose y error is missing (NaN); the fit never used them.
- Fixed: with PySide6 before 6.12, running a command from a submenu in the
  command palette (Ctrl+K), such as *Add Panel*, did nothing and printed an
  error.
- **Requirements:** Matplotlib 3.10, NumPy 2.0, SciPy 1.13 and PySide6 6.7 at
  least. Older Matplotlib (3.8) did not run at all and older NumPy read some
  text files wrongly; the minimum versions are now installed and tested on
  every change.
- **Axis labels are lined up across panels**, by default and also in files
  saved before: in a column of panels the y labels stand on one line instead
  of following the width of their numbers (and x labels in a row).
  Saved figures with several panels therefore look a little different once
  opened. *Line up axis labels* in the figure's settings turns it off. Each
  axis has a *Distance (pt)* for its label.
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
- **The Insert menu has pictures all the way down.** *Add Plot As*, *Add
  Reference*, *Add Panel* and *Duplicate Figure* have one now, and the menu lists
  its entries in the toolbar's order. In the toolbar *Reference* comes before
  *Note*, and the note's picture is a T.

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
