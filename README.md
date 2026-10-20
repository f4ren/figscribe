# figscribe

A lean desktop GUI for scientific plots: build and fine-tune figures
interactively, and get **clean, standalone Python code** (Matplotlib) as the
result instead of a proprietary project file.

Intended for scientists and engineers who find Origin unwieldy but don't want to
hand-write every detail of a Matplotlib figure just to fine-tune it.

## Status

**Early development.** The plot model with its JSON project file, the renderer
for line, scatter, errorbar and histogram plots, notes, a right y axis, images
and color meshes with color bars, fits and residuals with export to
PDF/SVG/PNG, CSV and NumPy (.npy/.npz) import, undoable commands, curve
fitting and the code generator exist and are tested. The GUI (`figscribe`) starts from a data file
or a layout, proposes a first plot, fits models with a residual panel, edits
every property with undo/redo, and saves and exports projects and Python
scripts.

## The generated code

*File > Export Python Script…* (or `figscribe script PROJECT.figscribe -o
plot.py`) writes a standalone script that needs only NumPy, Matplotlib and,
for fits, SciPy. It checks the data file's SHA-256, loads it with
`np.loadtxt` (or `np.load` for NumPy files), fits with `scipy.optimize.curve_fit` from the same start values,
and draws exactly what figscribe shows: a test runs every example script and
compares its PNG pixel by pixel with figscribe's own export.

The full project plan lives in [`plan/`](plan/).

## Assistants (MCP)

figscribe can be driven by an assistant in any MCP client (Claude Desktop,
Claude Code, IDEs, front ends for local models): "two panels, residuals below,
shared x axis" becomes changes to the open project, live in the window and
undoable there. The assistant works through the same commands as the GUI and
sees the project's structure and column names, never the data, unless you let
it see the figure.

```
pip install "figscribe[mcp]"
claude mcp add figscribe -- figscribe mcp      # e.g. for Claude Code
```

Then enable *Assistant > Allow MCP access* in figscribe; *Assistant > How to
connect* shows the configuration for other clients.

Or use the built-in assistant (*Assistant > Chat*, Ctrl+Shift+A) with the
same tools. *Assistant > Choose Model…* picks what it talks to:

- **Claude** through the Anthropic API (`ANTHROPIC_API_KEY`, or `ant auth login`);
- **ChatGPT** or any other server with the OpenAI chat completions API
  (`OPENAI_API_KEY`);
- **a local model** in LM Studio (`http://localhost:1234/v1`), Ollama
  (`http://localhost:11434/v1`), vLLM or llama.cpp: nothing leaves your
  computer. *Load models* lists what the server offers; pick one that supports
  tool calling.

```
pip install "figscribe[chat]"
```

The model and server are remembered; an API key typed into figscribe is kept
for the session only.

Which model is good enough? `figscribe bench` asks a model 21 typical requests
(easy to hard: axis labels and ranges, fits, a right axis, insets, residual
panels) on the example project and checks each result automatically:

```
figscribe bench --base-url http://localhost:1234/v1 --model qwen3-30b --no-vision
figscribe bench --model claude-sonnet-5-5 --json sonnet.json
```

## Design principle

The declarative plot model is the single source of truth:

```
Plot model (typed, JSON-serializable)
   ├──> Renderer:       model -> Matplotlib figure (GUI preview AND export)
   ├──> Code generator:  model -> standalone Python script
   └──> Persistence:    model <-> JSON project file
```

The GUI only ever reads and mutates the model, through commands with undo/redo —
it never manipulates Matplotlib objects directly. Preview and export share the
same renderer, so what you see is what you get. The generated code reproduces the
same figure and runs without figscribe installed.

## Scope

Planned for the MVP: data import (CSV, HDF5, NPY/NPZ), line/scatter/errorbar
plots, histograms, 2D images and color meshes, curve fitting via
`scipy.optimize.curve_fit`, multi-panel layouts with shared axes, LaTeX labels,
undo/redo, export to PDF/SVG/PNG at exact millimeter sizes, and Matplotlib style
templates for journal-column widths.

Deliberately out of scope: spreadsheet-style data editing, a statistics suite, a
custom scripting language, and reading generated or third-party Python code back
in.

## Stack

Python >= 3.11, PySide6, Matplotlib, NumPy, SciPy, h5py.

## License

MIT, see [LICENSE](LICENSE).
