# figscribe

A lean desktop application for scientific figures: build and fine-tune plots
interactively, and get **clean, standalone Python code** (Matplotlib) as the
result instead of a proprietary project file.

For scientists and engineers who find Origin unwieldy but don't want to
hand-write every detail of a Matplotlib figure just to fine-tune it.

- **What you see is what you get**: the preview, the exported PDF and the
  generated script draw the same figure, checked pixel by pixel in the tests.
- **Sizes as journals state them**: millimetres and points, with layouts for
  single and double columns.
- **Everything is undoable**, including changes made by an AI assistant.
- **Your data stays yours**: an assistant sees file and column names, never
  the values, and can run entirely on your own computer.

## Contents

- [Status](#status)
- [Installation](#installation)
- [Getting started](#getting-started)
- [Features](#features)
- [The generated code](#the-generated-code)
- [AI assistants](#ai-assistants)
- [Keyboard and mouse](#keyboard-and-mouse)
- [Command line](#command-line)
- [How it works](#how-it-works)
- [Scope](#scope)
- [Development](#development)

## Status

**Pre-alpha.** The features below are implemented and tested on Linux,
Windows and macOS with Python 3.11 and 3.13; file formats and behaviour may
still change. figscribe is not on PyPI yet. Still to come: style templates,
snapping and alignment guides, and packaged installers (see the
[roadmap](plan/roadmap.md)).

## Installation

figscribe needs Python 3.11 or newer.

```
git clone https://github.com/f4ren/figscribe.git
cd figscribe
pip install -e .
```

Optional parts:

| Extra | For |
|---|---|
| `pip install -e ".[chat]"` | the built-in AI assistant (Claude, ChatGPT, local models) |
| `pip install -e ".[mcp]"` | driving figscribe from an MCP client such as Claude Desktop |
| `pip install -e ".[dev]"` | running the tests and the linter |

## Getting started

Start `figscribe`. The start page offers three ways in:

- **Open a data file** (CSV, `.npy`, `.npz`). The import dialog detects
  delimiter, decimal comma, header and unit rows, shows a preview and suggests
  a first plot, e.g. *U against t with error bars dU*.
- **Pick a layout**: single column (85 × 60 mm), double column
  (175 × 70 mm), data with fit and residuals, two panels side by side, or a
  16:9 slide.
- **Open the example**, a Gaussian scan with error bars.

Then click anything in the figure or in the contents list to select it, and
change it in the property panel on the right. *Insert* adds data, plots,
fits, notes and panels; *File > Export* writes the figure or its Python
script.

## Features

**Data**
- CSV files with automatic detection of delimiter, decimal comma, header and
  unit rows, and of the text encoding (UTF-8, or cp1252 and Latin-1 as older
  Windows programs write them); NumPy `.npy` and `.npz` files (read without pickles, so a data
  file cannot run code).
- Each data file is recorded with its SHA-256. If it changes later,
  figscribe says so instead of silently plotting different data, shows
  what changed, and takes the new version on request, or lets you point it
  to where a moved file went.

**Plots**
- Line, scatter, error bars, histograms, images and color meshes with color
  bars (linear or logarithmic), notes with or without an arrow.
- Curve fits: linear, polynomial, Gaussian, Lorentzian, exponential, or your
  own expression such as `a*exp(-x/tau)+c`. Error bars weight the fit; the
  result shows each parameter with its 1σ uncertainty and the reduced χ².
  Residuals go into their own panel below.

**Layout and style**
- Several panels in a grid: add one to the right, left, above or below, or
  as an inset. Shared x and y axes, a second y axis on the right.
- Exact figure size in mm, font sizes in pt, linear, log and symlog axes,
  axis ranges, major ticks every *n* with minor ticks between them, tick
  marks inward or outward and on all four sides, grid, LaTeX in labels
  (`$\Delta U$`), units in labels as `U (V)`, `U / V` or `U [V]`.
- Values shown with an SI prefix: frequencies in Hz drawn as `0 … 225` with
  the label `f (kHz)`, while the data stay in Hz.

**Working with the figure**
- Click to select, edit in the property panel; every change is one undo
  step. Click an axis, its numbers or its label, to set its range, ticks and
  label in plain terms: *major ticks every 50*, *4 minor ticks between
  them*; with values shown in kHz you type the range in kHz too. Hovering
  over a field explains it.
- Colors come from the figure's color cycle, the colors used lately, or
  *Same as…* another plot; a plot's context menu brings it to the front or
  sends it to the back.
- Numbers can be typed with a decimal comma (`1,5`), a minus copied from a
  PDF (`−3`) and spaces between thousands (`10 000`); lists of them are then
  separated by semicolons (`0; 0,5; 1`).
- Drag the legend and notes into place. Zoom with the mouse wheel and pan by
  dragging to look closer; *Use as axis range* keeps that view.
- The **Python code** drawer under the figure shows the generated script,
  live, as you edit.

**Export**
- PDF, SVG and PNG at the exact size.
- A standalone Python script (see below).
- The project itself as a readable JSON file (`.figscribe`).

## The generated code

*File > Export Python Script…* (or `figscribe script PROJECT.figscribe -o
plot.py`) writes a script that needs only NumPy, Matplotlib and, for fits,
SciPy. It is written the way a person would write it: no figscribe helpers,
named variables, comments where they help. From the example project's script
(shortened):

```python
scan_path = HERE / "scan.csv"
# The figure was made from exactly this file; delete the check to plot a newer one.
if hashlib.sha256(scan_path.read_bytes()).hexdigest() != (
    "380a81c153b9c2f47f51c67b4478a251b9e98fd1ba0e533b010e9fb5eab92394"
):
    raise SystemExit(f"{scan_path} changed since the figure was made")
t, U, dU = np.loadtxt(scan_path, delimiter=",", skiprows=3, unpack=True)

fig = plt.figure(figsize=(85 / 25.4, 60 / 25.4), dpi=300, layout="constrained")
ax = fig.add_subplot()
ax.set_xlabel("$t$ (s)")
ax.set_ylabel("$U$ (V)")
ax.errorbar(t, U, yerr=dU, linestyle="none", marker="o", markersize=4,
            capsize=2, elinewidth=1, label="measurement")
ax.legend(fontsize=8, loc="best")
fig.savefig(HERE / "scan.pdf")
```

Fits are redone in the script with `scipy.optimize.curve_fit` from the same
start values. A test runs the generated scripts and compares their PNG pixel
by pixel with figscribe's own export.

## AI assistants

Describe a change in words, *"two panels, residuals below, shared x axis"*,
and an assistant makes it in the open project. It works through the same
commands as the GUI, so every change appears at once and can be undone.

What an assistant sees: the project's structure and the names of files and
columns, never the data values. It sees the rendered figure only if you
allow it (*Assistant > Let It See the Figure*).

### The built-in chat

*Assistant > Chat* (Ctrl+Shift+A) opens the chat under the figure;
*Assistant > Choose Model…* selects what it talks to:

- **Claude** through the Anthropic API: set `ANTHROPIC_API_KEY` or sign in
  with `ant auth login`.
- **ChatGPT**, or any server with the OpenAI chat completions API: set
  `OPENAI_API_KEY`.
- **Google Gemini**: a key from Google AI Studio, in `GEMINI_API_KEY`. The
  Gemini API has a free tier. *Load models* also lists models that a new key
  cannot use or that do not answer; `gemini-3.5-flash` works (October 2026).
- **A local model** in LM Studio (`http://localhost:1234/v1`), Ollama
  (`http://localhost:11434/v1`), vLLM or llama.cpp: nothing leaves your
  computer. *Load models* lists what the server offers; choose one that
  supports tool calling.

figscribe remembers the model and server. An API key typed into figscribe is
kept for the session only and never saved.

### Other assistants through MCP

figscribe is also an MCP server, for Claude Desktop, Claude Code, IDEs or
front ends for local models:

```
pip install -e ".[mcp]"
claude mcp add figscribe -- figscribe mcp      # e.g. for Claude Code
```

Then enable *Assistant > Allow MCP Access*; *Assistant > How to Connect…*
shows the configuration for other clients.

### Without paying per request

- **A local model** costs nothing and keeps everything on your computer;
  how well it works depends on its size (see below).
- **Gemini's free tier**: a key from Google AI Studio, without billing.
  It allows 5 requests a minute and 20 a day per model (October 2026), and
  one change takes the assistant two to four: enough to try the assistant,
  a handful of changes a day. figscribe says how long to wait; another
  model has its own limit. Outside the EU, EEA,
  Switzerland and the UK, Google may use free-tier requests to improve its
  products and have people read them; inside, its paid-service data terms
  apply. Either way the model sees names, not data values.
- **A subscription** (Claude Pro or Max, ChatGPT Plus) does not give API
  access, and Anthropic does not allow its sign-in in other applications.
  It can drive figscribe through MCP instead: in Claude Desktop or Claude
  Code with your Claude plan, or in Gemini CLI with a Google account.

### Which model is good enough?

`figscribe bench` measures it: it gives a model 21 typical requests, from
easy (an axis label, a range, a colour) to hard (an inset zoomed in, a fit
with residual panel), on the example project and checks each result
automatically.

```
figscribe bench --base-url http://localhost:1234/v1 --model qwen3-30b --no-vision
figscribe bench --model claude-sonnet-5-5 --json sonnet.json
```

`figscribe bench --list` shows the cases, `--level easy` runs only the easy
ones, `--repeat 3` evens out variation between runs.

## Keyboard and mouse

| Action | Keys |
|---|---|
| New, open, save, save as, quit | the system's usual keys (Ctrl+N, Ctrl+O, Ctrl+S, …) |
| Undo, redo, delete the selection | Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y, Del |
| Import data | Ctrl+I |
| Add plot, add fit | Ctrl+Shift+P, Ctrl+Shift+F |
| Export figure, export Python script | Ctrl+E, Ctrl+Shift+E |
| Show the Python code | Ctrl+Shift+Y |
| Show the assistant | Ctrl+Shift+A |
| Zoom a panel | mouse wheel; with Shift only x, with Ctrl or Alt only y |
| Pan a panel | drag its background |
| Back to the axis ranges of the model | Esc |

On macOS, Cmd takes the place of Ctrl.

## Command line

```
figscribe [PROJECT.figscribe]                 open the GUI, optionally with a project
figscribe script PROJECT.figscribe [-o FILE]  write the Python script for the first figure
figscribe mcp                                 serve the open project to an MCP client
figscribe bench [--help]                      measure a model on typical assistant requests
figscribe --version
```

## How it works

A typed, declarative plot model is the single source of truth:

```
Plot model (typed, JSON-serializable)
   ├──> Renderer:        model -> Matplotlib figure (preview AND export)
   ├──> Code generator:  model -> standalone Python script
   └──> Persistence:     model <-> JSON project file
```

The GUI and the assistants only ever change the model, through commands with
undo and redo; they never touch Matplotlib objects. Preview and export share
the renderer, and the code generator mirrors its calls, so all three show the
same figure.

Design decisions and their reasons are recorded in
[`docs/decisions.md`](docs/decisions.md); the project brief is in
[`plan/project-brief.md`](plan/project-brief.md) and the work list in
[`plan/roadmap.md`](plan/roadmap.md).

## Scope

Planned beyond what exists: HDF5 import, style templates for journals,
snapping and alignment guides, installers.

Deliberately out of scope: spreadsheet-style data editing, a statistics
suite, a scripting language of its own, and reading generated or other
Python code back in.

## Development

```
pip install -e ".[dev]"
pytest                    # all tests, the GUI ones without opening windows
ruff check . && ruff format --check .
```

The tests include image comparisons of the renderer, the pixel comparison
of generated scripts, undo for every command, and GUI tests with pytest-qt.
Work happens test-first on one branch per feature, merged by pull request
once CI is green on Linux, Windows and macOS.

Built with Python, PySide6 (Qt), Matplotlib, NumPy, SciPy and Pydantic.

## License

MIT, see [LICENSE](LICENSE).
