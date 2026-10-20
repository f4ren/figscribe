"""Writing the script: header, data, fits, figure, panels, saving.

Every Matplotlib call here mirrors one in `figscribe.render.figure`, with the
same arguments where they change the drawing; arguments that only repeat
Matplotlib's own default are left out, so the script reads like one written
by hand. The renderer passes some values explicitly that a style sheet could
otherwise change (line widths, marker sizes, legend location); those are kept.
"""

from __future__ import annotations

import keyword
import os
import re
from datetime import date
from pathlib import Path
from string import ascii_lowercase

import numpy as np

from figscribe import __version__
from figscribe.fit import numpy_source, parameter_names
from figscribe.io.files import resolve_path
from figscribe.model import (
    Annotation,
    ArrayRef,
    Axes,
    AxisSpec,
    ColorMesh,
    ColumnRef,
    CsvSource,
    ErrorbarPlot,
    ExpressionFit,
    Figure,
    FitCurve,
    Histogram,
    ImagePlot,
    Legend,
    LinePlot,
    NumpySource,
    Project,
    ResidualPlot,
    ScatterPlot,
)
from figscribe.render.figure import COORDS, CURVE_POINTS, MM_PER_INCH, DataProvider
from figscribe.render.labels import axis_label, unit_shown
from figscribe.render.layout import (
    creation_order,
    hidden_tick_labels,
    inset_parent,
    share_partner,
)
from figscribe.render.ticks import (
    minor_ticks,
    scaling,
    silent_minor_labels,
    tick_style,
)

WIDTH = 88
DEFAULT_ZORDER = {
    "scatter": 1.0,
    "histogram": 1.0,
    "annotation": 3.0,
    "image": 0.0,
    "colormesh": 1.0,
}
"""Matplotlib's own z-order per kind; 2 (lines) for the rest."""
RESERVED = {
    "np",
    "plt",
    "fig",
    "grid",
    "ax",
    "x",
    "HERE",
    "Path",
    "hashlib",
    "curve_fit",
    "popt",
    "pcov",
    "perr",
    "name",
    "value",
    "error",
    "valid",
    "image",
    "mesh",
    "handles",
    "labels",
    "right_handles",
    "right_labels",
}


def script_name(figure: Figure) -> str:
    """A file name for the figure's script: its name, made safe."""
    return f"{_slug(figure.name) or 'figure'}.py"


def generate(
    project: Project,
    figure: Figure | None = None,
    *,
    base_dir: str | Path,
    script_dir: str | Path | None = None,
    output: str | None = None,
    data: DataProvider | None = None,
) -> str:
    """The Python script that draws `figure` (the project's first by default).

    `base_dir` is where the project's relative data paths start, `script_dir`
    where the script will be saved (default: the same); data paths in the
    script are relative to it. `output` is the file the script saves, next to
    it. With `data`, the script leaves out what the data does not need, such
    as filtering out non-finite values before a fit.
    """
    figure = figure or project.figures[0]
    writer = _Writer(project, figure, Path(base_dir), data)
    return writer.write(
        Path(script_dir) if script_dir is not None else Path(base_dir),
        output or f"{_slug(figure.name) or 'figure'}.pdf",
    )


class _Writer:
    def __init__(
        self,
        project: Project,
        figure: Figure,
        base_dir: Path,
        data: DataProvider | None,
    ):
        self.project = project
        self.figure = figure
        self.base_dir = base_dir
        self.data = data
        self.lines: list[str] = []
        self._mappables = 0
        self.artists = {a.id: a for axes in figure.axes for a in axes.artists}
        self.sources = {s.id: s for s in project.sources}
        self.columns = self._name_columns()
        self.arrays = self._name_arrays()
        self.fits = self._name_fits()
        self.axes_names = self._name_axes()

    # --- naming -----------------------------------------------------------------

    def _refs(self) -> list[ColumnRef]:
        """Every column the figure plots, in order of first use."""
        refs: list[ColumnRef] = []
        for axes in self.figure.axes:
            for artist in axes.artists:
                for field in ("x", "y", "xerr", "yerr", "values"):
                    ref = getattr(artist, field, None)
                    if isinstance(ref, ColumnRef) and ref not in refs:
                        refs.append(ref)
        return refs

    def _name_columns(self) -> dict[tuple[str, str | int], str]:
        names: dict[tuple[str, str | int], str] = {}
        taken = set(RESERVED)
        for ref in self._refs():
            source = self.sources.get(ref.source)
            if source is None:
                raise ValueError(f"no data source {ref.source!r} in the project")
            if isinstance(ref.column, str):
                plain = _identifier(ref.column)
            elif isinstance(source, NumpySource) and source.array:
                # Columns of an .npz array are named after it: x, x1, x2, ...
                plain = _identifier(source.array) + (
                    str(ref.column) if ref.column else ""
                )
            else:
                plain = f"col{ref.column}"
            name = plain
            if name in taken:
                name = f"{_slug(Path(source.path).stem) or 'data'}_{plain}"
            while name in taken:
                name += "_"
            taken.add(name)
            names[(ref.source, ref.column)] = name
        return names

    def _name_arrays(self) -> dict[tuple[str, str | None], str]:
        """{(source id, key): variable} for every 2-D array the figure plots."""
        names: dict[tuple[str, str | None], str] = {}
        taken = set(RESERVED) | set(self.columns.values())
        for axes in self.figure.axes:
            for artist in axes.artists:
                for field in ("data", "c"):
                    ref = getattr(artist, field, None)
                    if not isinstance(ref, ArrayRef):
                        continue
                    source = self.sources.get(ref.source)
                    if source is None:
                        raise ValueError(
                            f"no data source {ref.source!r} in the project"
                        )
                    key = (ref.source, ref.key)
                    if key in names:
                        continue
                    stem = _slug(Path(source.path).stem) or "data"
                    name = f"{stem}_{_slug(ref.key)}" if ref.key else stem
                    if isinstance(source, CsvSource):
                        name = f"{stem}_table"
                    if name[0].isdigit():
                        name = f"data_{name}"
                    while name in taken:
                        name += "_"
                    taken.add(name)
                    names[key] = name
        return names

    def _name_fits(self) -> dict[str, tuple[str, str]]:
        """{fit id: (model function name, parameter variable)} for drawn fits."""
        fits = [
            a for a in self.artists.values() if isinstance(a, FitCurve) and a.result
        ]
        taken = set(RESERVED) | set(self.columns.values())
        found = {}
        for fit in fits:
            base = (
                "model"
                if isinstance(fit.model, ExpressionFit)
                else fit.model.name
                if fit.model.degree is None
                else f"poly{fit.model.degree}"
            )
            function = base
            n = 2
            while function in taken:
                function, n = f"{base}{n}", n + 1
            taken.add(function)
            popt = "popt" if len(fits) == 1 else f"{function}_popt"
            found[fit.id] = (function, popt)
        return found

    def _name_axes(self) -> list[str]:
        if len(self.figure.axes) == 1:
            return ["ax"]
        return [f"ax_{_letter(i)}" for i in range(len(self.figure.axes))]

    def column(self, ref: ColumnRef) -> str:
        return self.columns[(ref.source, ref.column)]

    # --- output -----------------------------------------------------------------

    def emit(self, *lines: str) -> None:
        self.lines.extend(lines)

    def call(self, function: str, *args: str, indent: str = "", **kwargs: str) -> None:
        """A call, on one line if it fits, else one argument per line."""
        parts = [*args, *(f"{k}={v}" for k, v in kwargs.items())]
        one = f"{indent}{function}({', '.join(parts)})"
        if len(one) <= WIDTH:
            self.emit(one)
            return
        self.emit(f"{indent}{function}(")
        self.emit(*(f"{indent}    {p}," for p in parts))
        self.emit(f"{indent})")

    def section(self, title: str) -> None:
        head = f"# --- {title} "
        self.emit("", "", head + "-" * max(3, WIDTH - 1 - len(head)), "")

    def write(self, script_dir: Path, output: str) -> str:
        self._header()
        self._imports()
        self._data(script_dir)
        self._fit_models()
        self._fits()
        self._figure()
        self.section("Save")
        self.emit(f"fig.savefig(HERE / {_str(output)})")
        return "\n".join(self.lines) + "\n"

    # --- parts ------------------------------------------------------------------

    def _header(self) -> None:
        figure = self.figure
        needs = "NumPy, Matplotlib and SciPy" if self.fits else "NumPy and Matplotlib"
        self.emit(
            f'"""{figure.name}: {_num(figure.width_mm)} × {_num(figure.height_mm)} mm '
            f"at {_num(figure.dpi)} dpi.",
            "",
            f"Generated by figscribe {__version__} on {date.today().isoformat()}.",
            f"It runs without figscribe and needs {needs}.",
        )
        used = [s for s in self.project.sources if self._used(s.id)]
        if used:
            self.emit("", "Data:")
            for source in used:
                self.emit(f"    {source.path}", f"        sha256 {source.sha256}")
        self.emit('"""')

    def _used(self, source_id: str) -> bool:
        return any(key[0] == source_id for key in [*self.columns, *self.arrays])

    def _imports(self) -> None:
        self.emit("")
        if self.columns or self.arrays:
            self.emit("import hashlib")
        self.emit("from pathlib import Path", "")
        self.emit("import matplotlib.pyplot as plt", "import numpy as np")
        locators = self._locators()
        if locators:
            self.emit(f"from matplotlib.ticker import {', '.join(locators)}")
        if any(getattr(a, "norm", None) == "log" for a in self.artists.values()):
            self.emit("from matplotlib.colors import LogNorm")
        if self.fits:
            self.emit("from scipy.optimize import curve_fit")
        self.emit("", "HERE = Path(__file__).resolve().parent")
        if self.figure.stylesheet is not None:
            self.emit(f"plt.style.use({_str(self.figure.stylesheet)})")
        if self.figure.font_size is not None:
            self.emit(f'plt.rcParams["font.size"] = {_num(self.figure.font_size)}')
        style = tick_style(self.figure)
        if style:
            entries = [f"{_str(k)}: {_value(v)}" for k, v in style.items()]
            line = f"plt.rcParams.update({{{', '.join(entries)}}})"
            if len(line) <= WIDTH:
                self.emit(line)
            else:
                self.emit("plt.rcParams.update(", "    {")
                self.emit(*(f"        {entry}," for entry in entries))
                self.emit("    }", ")")

    def _locators(self) -> list[str]:
        """The tick locators and formatters the script needs to import."""
        specs = [
            s for a in self.figure.axes for s in (a.x, a.y, a.y_right) if s is not None
        ]
        needed = []
        if any(minor_ticks(s)[0] == "parts" for s in specs):
            needed.append("AutoMinorLocator")
        if any(scaling(s) is not None for s in specs):
            needed.append("FuncFormatter")
        if any(
            (s.ticks is None and s.major_step) or minor_ticks(s)[0] == "step"
            for s in specs
        ):
            needed.append("MultipleLocator")
        if any(silent_minor_labels(s) for s in specs):
            needed.append("NullFormatter")
        return needed

    def _data(self, script_dir: Path) -> None:
        used = [s for s in self.project.sources if self._used(s.id)]
        if not used:
            return
        self.section("Data")
        for i, source in enumerate(used):
            if i:
                self.emit("")
            self._source(source, script_dir)

    def _source(self, source, script_dir: Path) -> None:
        if not isinstance(source, CsvSource | NumpySource):
            raise NotImplementedError(
                f"generating code for {source.format!r} sources is not implemented"
            )
        stem = _slug(Path(source.path).stem) or "data"
        path = f"{stem}_path"
        location = resolve_path(source.path, self.base_dir)
        self.emit(f"{path} = HERE / {_str(_relative(location, script_dir))}")
        self.emit(
            "# The figure was made from exactly this file; delete the check to "
            "plot a newer one.",
            f"if hashlib.sha256({path}.read_bytes()).hexdigest() != (",
            f'    "{source.sha256}"',
            "):",
            f'    raise SystemExit(f"{{{path}}} changed since the figure was made")',
        )
        refs = [(c, n) for (sid, c), n in self.columns.items() if sid == source.id]
        indices = [_index(source, column) for column, _ in refs]
        if isinstance(source, NumpySource):
            self._numpy(source, path, refs, indices)
            return
        kwargs: dict[str, str] = {}
        if source.delimiter is not None:
            kwargs["delimiter"] = _str(source.delimiter)
        skip = (0 if source.header_row is None else source.header_row + 1) + (
            source.skip_rows
        )
        if skip:
            kwargs["skiprows"] = str(skip)
        if source.comment != "#":
            kwargs["comments"] = _str(source.comment) if source.comment else "None"
        if source.decimal != ".":
            kwargs["converters"] = (
                f"lambda field: float(field.replace({_str(source.decimal)}, '.'))"
            )
        if _has_bom(location):
            kwargs["encoding"] = '"utf-8-sig"'
        table = self.arrays.get((source.id, None))
        if table is not None:
            # The whole table is plotted as an image; columns are slices of it.
            self.call(f"{table} = np.loadtxt", path, **kwargs)
            for (_, name), index in zip(refs, indices, strict=True):
                self.emit(f"{name} = {table}[:, {index}]")
            return
        if len(refs) == 1:
            kwargs["usecols"] = str(indices[0])
            self.call(f"{refs[0][1]} = np.loadtxt", path, **kwargs)
            return
        if indices != list(range(len(source.columns))) or not source.columns:
            kwargs["usecols"] = "(" + ", ".join(str(i) for i in indices) + ")"
        if self._single_row(refs, source):
            kwargs["ndmin"] = "2"
        kwargs["unpack"] = "True"
        targets = ", ".join(name for _, name in refs)
        self.call(f"{targets} = np.loadtxt", path, **kwargs)

    def _numpy(self, source: NumpySource, path: str, refs, indices) -> None:
        """np.load the arrays used, as floats like figscribe reads them."""
        keys = {key for sid, key in self.arrays if sid == source.id}
        flat = self.data is not None and (
            self.data(ArrayRef(source=source.id)).ndim == 1
        )
        if flat and len(refs) == 1 and (source.id, None) not in self.arrays:
            # A 1-D array used as one column: load it under the column's name.
            self.arrays[(source.id, None)] = refs[0][1]
            refs, indices = [], []
            keys.add(None)
        elif refs:
            keys.add(None)  # columns come out of the source's own array
        for key in sorted(keys, key=lambda k: (k is not None, k or "")):
            name = self.arrays.get((source.id, key))
            if name is None:
                stem = _slug(Path(source.path).stem) or "data"
                name = f"{stem}_{_slug(source.array)}" if source.array else stem
                taken = {*self.arrays.values(), *self.columns.values(), *RESERVED}
                while name in taken:
                    name += "_"
                self.arrays[(source.id, key)] = name
            wanted = key or source.array
            item = f"[{_str(wanted)}]" if source.format == "npz" else ""
            self.emit(f"{name} = np.load({path}){item}.astype(float)")
        base = self.arrays.get((source.id, None))
        for (_, name), index in zip(refs, indices, strict=True):
            self.emit(f"{name} = {base}" if flat else f"{name} = {base}[:, {index}]")

    def _single_row(self, refs, source) -> bool:
        if self.data is None:
            return False
        values = self.data(ColumnRef(source=source.id, column=refs[0][0]))
        return len(values) == 1

    def _fit_models(self) -> None:
        if not self.fits:
            return
        self.section("Fit models")
        for fit_id, (function, _) in self.fits.items():
            fit = self.artists[fit_id]
            names = parameter_names(fit.model)
            self.emit("", f"def {function}(x, {', '.join(names)}):")
            self.emit(f"    return {numpy_source(fit.model)}", "")

    def _fits(self) -> None:
        for fit_id, (function, popt) in self.fits.items():
            fit = self.artists[fit_id]
            target = self.artists[fit.target]
            self.section(f"Fit: {_describe(fit)} to {_describe(target)}")
            x, y = self.column(target.x), self.column(target.y)
            yerr = (
                self.column(target.yerr)
                if isinstance(target, ErrorbarPlot) and target.yerr is not None
                else None
            )
            names = parameter_names(fit.model)
            arrays = [a for a in (x, y, yerr) if a is not None]
            if self._finite(fit) is not True:
                self.emit(
                    "# curve_fit needs finite values.",
                    "valid = " + " & ".join(f"np.isfinite({a})" for a in arrays),
                )
                x, y = f"{x}[valid]", f"{y}[valid]"
                yerr = f"{yerr}[valid]" if yerr is not None else None
            start = [fit.initial_values.get(n, 1.0) for n in names]
            kwargs = {"p0": "[" + ", ".join(repr(float(v)) for v in start) + "]"}
            if yerr is not None:
                kwargs |= {"sigma": yerr, "absolute_sigma": "True"}
            pcov = "pcov" if popt == "popt" else popt.replace("popt", "pcov")
            self.call(f"{popt}, {pcov} = curve_fit", function, x, y, **kwargs)
            result = fit.result
            if result.reduced_chi_square is not None:
                self.emit(
                    f"# figscribe found χ²/ndf = {result.reduced_chi_square:.3g} "
                    f"for this fit."
                )
            labels = "[" + ", ".join(_str(n) for n in names) + "]"
            perr = "perr" if popt == "popt" else popt.replace("popt", "perr")
            self.emit(
                f"{perr} = np.sqrt(np.diag({pcov}))",
                f"for name, value, error in zip({labels}, {popt}, {perr}):",
                '    print(f"{name} = {value:.6g} ± {error:.2g}")',
            )

    def _finite(self, fit: FitCurve) -> bool | None:
        """Whether all data of the fit is finite; None if unknown."""
        if self.data is None:
            return None
        target = self.artists[fit.target]
        refs = [target.x, target.y]
        if isinstance(target, ErrorbarPlot) and target.yerr is not None:
            refs.append(target.yerr)
        return all(bool(np.all(np.isfinite(self.data(r)))) for r in refs)

    def _figure(self) -> None:
        figure = self.figure
        self.section(
            f"Figure: {figure.name}, "
            f"{_num(figure.width_mm)} × {_num(figure.height_mm)} mm"
        )
        kwargs = {
            "figsize": f"({_num(figure.width_mm)} / {_num(MM_PER_INCH)}, "
            f"{_num(figure.height_mm)} / {_num(MM_PER_INCH)})",
            "dpi": _num(figure.dpi),
        }
        if figure.layout.constrained_layout:
            kwargs["layout"] = '"constrained"'
        self.call("fig = plt.figure", **kwargs)
        layout = figure.layout
        grid_kwargs = {
            name: _value(getattr(layout, name))
            for name in ("width_ratios", "height_ratios", "hspace", "wspace")
            if getattr(layout, name) is not None
        }
        simple = (layout.rows, layout.cols) == (1, 1) and not grid_kwargs
        if not simple:
            self.call(
                "grid = fig.add_gridspec",
                str(layout.rows),
                str(layout.cols),
                **grid_kwargs,
            )
        for i in creation_order(figure):
            axes = figure.axes[i]
            name = self.axes_names[i]
            if axes.inset is not None:
                host = self.axes_names[inset_parent(figure, i)]
                bounds = _value(list(axes.inset.bounds))
                self.emit(f"{name} = {host}.inset_axes({bounds})")
                continue
            kwargs = {}
            for axis, key in (("x", "sharex"), ("y", "sharey")):
                partner = share_partner(figure, i, axis)
                if partner is not None:
                    kwargs[key] = self.axes_names[partner]
            where = (
                []
                if simple
                else [
                    f"grid[{_span(axes.row, axes.rowspan)}, "
                    f"{_span(axes.col, axes.colspan)}]"
                ]
            )
            self.call(f"{name} = fig.add_subplot", *where, **kwargs)
        for i in creation_order(figure):
            self._panel(i, figure.axes[i])
        hidden = hidden_tick_labels(figure)
        if any(x or y for x, y in hidden):
            self.emit(
                "", "# Shared axes: tick labels only where no partner shows them."
            )
        for name, (hide_x, hide_y) in zip(self.axes_names, hidden, strict=True):
            if hide_x:
                self.emit(
                    f'{name}.tick_params(axis="x", which="both", labelbottom=False)'
                )
            if hide_y:
                self.emit(
                    f'{name}.tick_params(axis="y", which="both", labelleft=False)'
                )

    def _panel(self, index: int, axes: Axes) -> None:
        ax = self.axes_names[index]
        title = (
            f"Panel {_letter(index).upper()}" if len(self.figure.axes) > 1 else "Plot"
        )
        if axes.inset is not None:
            host = _letter(inset_parent(self.figure, index)).upper()
            title += f", inset in Panel {host}"
        self.emit("", f"# {title}" + (f": {axes.title}" if axes.title else ""))
        if axes.title is not None:
            size = {"fontsize": _num(axes.title_size)} if axes.title_size else {}
            self.call(f"{ax}.set_title", _str(axes.title), **size)
        self._axis(ax, "x", axes.x)
        self._axis(ax, "y", axes.y)
        right = None
        if axes.y_right is not None:
            right = f"{ax}_right"
            self.emit(f"{right} = {ax}.twinx()")
            self._axis(right, "y", axes.y_right)
        if axes.grid:
            kwargs = {}
            if axes.grid_which != "major":
                kwargs["which"] = _str(axes.grid_which)
            if axes.grid_axis != "both":
                kwargs["axis"] = _str(axes.grid_axis)
            self.call(f"{ax}.grid", "True", **kwargs)
        for artist in axes.artists:
            on_right = artist.axis == "right" and right is not None
            self._artist(right if on_right else ax, artist)
        if axes.legend.visible:
            self._legend(ax, axes.legend, right)

    def _axis(self, ax: str, name: str, spec: AxisSpec) -> None:
        label = axis_label(spec, self.figure.unit_format)
        if label is not None:
            size = {"fontsize": _num(spec.label_size)} if spec.label_size else {}
            self.call(f"{ax}.set_{name}label", _str(label), **size)
        if spec.scale == "symlog" and spec.symlog_linthresh is not None:
            self.emit(
                f'{ax}.set_{name}scale("symlog", '
                f"linthresh={_num(spec.symlog_linthresh)})"
            )
        elif spec.scale != "linear":
            self.emit(f"{ax}.set_{name}scale({_str(spec.scale)})")
        if spec.limits is not None:
            low, high = spec.limits
            self.emit(f"{ax}.set_{name}lim({_num(low)}, {_num(high)})")
        if spec.ticks is not None:
            kwargs = {}
            if spec.tick_labels is not None:
                kwargs["labels"] = _value(spec.tick_labels)
            self.call(f"{ax}.set_{name}ticks", _value(spec.ticks), **kwargs)
        elif spec.major_step is not None:
            step = _num(spec.major_step)
            self.emit(f"{ax}.{name}axis.set_major_locator(MultipleLocator({step}))")
        how, value = minor_ticks(spec)
        if how == "parts":
            self.emit(f"{ax}.{name}axis.set_minor_locator(AutoMinorLocator({value}))")
        elif how == "step":
            self.emit(
                f"{ax}.{name}axis.set_minor_locator(MultipleLocator({_num(value)}))"
            )
        elif how == "on":
            self.emit(f"{ax}.{name}axis.minorticks_on()")
        elif self.figure.stylesheet is not None:
            self.emit(f"{ax}.{name}axis.minorticks_off()")
        scaled = scaling(spec)
        if scaled is not None:
            op, factor = scaled
            number = "v" if (op, factor) == ("*", "1") else f"v {op} {factor}"
            if spec.prefix is not None:
                self.emit(f"# Values shown in {unit_shown(spec)}")
            self.emit(
                f"{ax}.{name}axis.set_major_formatter("
                f'FuncFormatter(lambda v, _: f"{{{number}:g}}"))'
            )
        if silent_minor_labels(spec):
            self.emit(f"{ax}.{name}axis.set_minor_formatter(NullFormatter())")
        if spec.tick_size is not None:
            self.call(
                f"{ax}.tick_params",
                axis=_str(name),
                which='"both"',
                labelsize=_num(spec.tick_size),
            )

    def _artist(self, ax: str, artist) -> None:
        common = _common(artist, default_zorder=DEFAULT_ZORDER.get(artist.kind, 2.0))
        if isinstance(artist, LinePlot):
            kwargs = _some(color=artist.color)
            kwargs |= {
                "linestyle": _str(artist.linestyle),
                "linewidth": _num(artist.linewidth),
            }
            if artist.marker is not None:
                kwargs |= {
                    "marker": _str(artist.marker),
                    "markersize": _num(artist.markersize),
                }
            x, y = self.column(artist.x), self.column(artist.y)
            self.call(f"{ax}.plot", x, y, **kwargs, **common)
        elif isinstance(artist, ScatterPlot):
            kwargs = {"s": _num(artist.size)} | _some(color=artist.color)
            kwargs["marker"] = _str(artist.marker)
            kwargs |= _some(edgecolors=artist.edgecolor)
            x, y = self.column(artist.x), self.column(artist.y)
            self.call(f"{ax}.scatter", x, y, **kwargs, **common)
        elif isinstance(artist, ErrorbarPlot):
            kwargs = {}
            if artist.xerr is not None:
                kwargs["xerr"] = self.column(artist.xerr)
            if artist.yerr is not None:
                kwargs["yerr"] = self.column(artist.yerr)
            kwargs |= _some(color=artist.color)
            kwargs |= {
                "linestyle": _str(artist.linestyle),
                "marker": _str(artist.marker),
                "markersize": _num(artist.markersize),
                "capsize": _num(artist.capsize),
                "elinewidth": _num(artist.elinewidth),
            }
            x, y = self.column(artist.x), self.column(artist.y)
            self.call(f"{ax}.errorbar", x, y, **kwargs, **common)
        elif isinstance(artist, Histogram):
            values = self.column(artist.values)
            if not self._all_finite([artist.values]):
                values = f"{values}[np.isfinite({values})]"
            kwargs = {"bins": _value(artist.bins)}
            if artist.density:
                kwargs["density"] = "True"
            if artist.histtype != "bar":
                kwargs["histtype"] = _str(artist.histtype)
            kwargs |= _some(color=artist.color)
            self.call(f"{ax}.hist", values, **kwargs, **common)
        elif isinstance(artist, Annotation):
            self._annotation(ax, artist, common)
        elif isinstance(artist, ImagePlot | ColorMesh):
            self._two_d(ax, artist, common)
        elif isinstance(artist, FitCurve):
            self._fit_curve(ax, artist, common)
        elif isinstance(artist, ResidualPlot):
            self._residuals(ax, artist, common)
        else:
            raise NotImplementedError(
                f"generating code for {artist.kind!r} artists is not implemented yet"
            )

    def _annotation(self, ax: str, note: Annotation, common: dict[str, str]) -> None:
        coords = COORDS[note.coords]
        point = note.arrow_to if note.arrow_to is not None else note.position
        kwargs = {"xy": _value(tuple(point))}
        if coords != "data":
            kwargs["xycoords"] = _str(coords)
        if note.arrow_to is not None:
            kwargs["xytext"] = _value(tuple(note.position))
            if coords != "data":
                kwargs["textcoords"] = _str(coords)
            props = {"arrowstyle": "->"}
            if note.color is not None:
                props["color"] = note.color
            kwargs["arrowprops"] = (
                "dict(" + ", ".join(f"{k}={_str(v)}" for k, v in props.items()) + ")"
            )
        if note.fontsize is not None:
            kwargs["fontsize"] = _num(note.fontsize)
        kwargs |= _some(color=note.color)
        self.call(f"{ax}.annotate", _str(note.text), **kwargs, **common)

    def _two_d(self, ax: str, artist, common: dict[str, str]) -> None:
        image = isinstance(artist, ImagePlot)
        ref = artist.data if image else artist.c
        values = self.arrays[(ref.source, ref.key)]
        kwargs = {"cmap": _str(artist.cmap)}
        if artist.norm == "log":
            limits = ", ".join(
                f"{k}={_num(v)}"
                for k, v in (("vmin", artist.vmin), ("vmax", artist.vmax))
                if v is not None
            )
            kwargs["norm"] = f"LogNorm({limits})"
        else:
            for key in ("vmin", "vmax"):
                if getattr(artist, key) is not None:
                    kwargs[key] = _num(getattr(artist, key))
        if image:
            kwargs |= {"origin": _str(artist.origin), "aspect": _str(artist.aspect)}
            if artist.extent is not None:
                kwargs["extent"] = _value(list(artist.extent))
            args = [values]
            call = f"{ax}.imshow"
        else:
            args = [values]
            if artist.x is not None and artist.y is not None:
                args = [self.column(artist.x), self.column(artist.y), values]
            kwargs["shading"] = '"auto"'
            call = f"{ax}.pcolormesh"
        bar = artist.colorbar
        if bar is None or not bar.visible:
            self.call(call, *args, **kwargs, **common)
            return
        self._mappables += 1
        mappable = "image" if image else "mesh"
        if self._mappables > 1:
            mappable += str(self._mappables)
        self.call(f"{mappable} = {call}", *args, **kwargs, **common)
        label = {"label": _str(bar.label)} if bar.label is not None else {}
        self.call("fig.colorbar", mappable, ax=ax, **label)

    def _all_finite(self, refs) -> bool:
        """Whether the data behind `refs` is all finite; False if unknown."""
        if self.data is None:
            return False
        return all(bool(np.all(np.isfinite(self.data(r)))) for r in refs)

    def _fit_curve(self, ax: str, fit: FitCurve, common: dict[str, str]) -> None:
        if fit.id not in self.fits:
            self.emit(f"# {_describe(fit)} is not fitted yet, so it is not drawn.")
            return
        function, popt = self.fits[fit.id]
        x = self.column(self.artists[fit.target].x)
        xs = f"{x}_fit" if f"{x}_fit" not in self.columns.values() else f"{x}_fit_"
        if self._finite(fit):
            low, high = f"{x}.min()", f"{x}.max()"
        else:
            low = f"{x}[np.isfinite({x})].min()"
            high = f"{x}[np.isfinite({x})].max()"
        self.emit(f"{xs} = np.linspace({low}, {high}, {CURVE_POINTS})")
        kwargs = _some(color=fit.color) | {
            "linestyle": _str(fit.linestyle),
            "linewidth": _num(fit.linewidth),
        }
        self.call(f"{ax}.plot", xs, f"{function}({xs}, *{popt})", **kwargs, **common)

    def _residuals(
        self, ax: str, residuals: ResidualPlot, common: dict[str, str]
    ) -> None:
        self.emit(
            f'{ax}.axhline(0.0, color="0.6", linewidth=0.8, linestyle="--", zorder=1)'
        )
        fit = self.artists.get(residuals.target)
        if not isinstance(fit, FitCurve) or fit.id not in self.fits:
            self.emit("# The fit is not run yet, so there are no residuals to draw.")
            return
        function, popt = self.fits[fit.id]
        target = self.artists[fit.target]
        x, y = self.column(target.x), self.column(target.y)
        kwargs = {}
        if isinstance(target, ErrorbarPlot) and target.yerr is not None:
            kwargs["yerr"] = self.column(target.yerr)
        kwargs |= _some(color=residuals.color) | {
            "marker": _str(residuals.marker),
            "markersize": _num(residuals.markersize),
            "linestyle": _str(residuals.linestyle),
        }
        self.call(
            f"{ax}.errorbar", x, f"{y} - {function}({x}, *{popt})", **kwargs, **common
        )

    def _legend(self, ax: str, legend: Legend, right: str | None = None) -> None:
        args = []
        if right is not None:
            self.emit(
                "# One legend for the plots of both y axes.",
                f"handles, labels = {ax}.get_legend_handles_labels()",
                f"right_handles, right_labels = {right}.get_legend_handles_labels()",
            )
            args = ["handles + right_handles", "labels + right_labels"]
        kwargs = {}
        if not legend.frame:
            kwargs["frameon"] = "False"
        if legend.ncols != 1:
            kwargs["ncols"] = str(legend.ncols)
        if legend.fontsize is not None:
            kwargs["fontsize"] = _num(legend.fontsize)
        if legend.position is not None:
            kwargs["loc"] = '"lower left"'
            kwargs["bbox_to_anchor"] = _value(tuple(legend.position))
        else:
            kwargs["loc"] = _str(legend.location)
        self.call(f"{ax}.legend", *args, **kwargs)


# --- helpers ---------------------------------------------------------------------


def _common(artist, default_zorder: float) -> dict[str, str]:
    """The keywords every artist takes, where they differ from Matplotlib's."""
    kwargs = {}
    if artist.label is not None:
        kwargs["label"] = _str(artist.label)
    if not artist.visible:
        kwargs["visible"] = "False"
    if artist.zorder != default_zorder:
        kwargs["zorder"] = _num(artist.zorder)
    if artist.alpha != 1.0:
        kwargs["alpha"] = _num(artist.alpha)
    return kwargs


def _some(**values) -> dict[str, str]:
    """Only the given values that are set, as code."""
    return {k: _str(v) for k, v in values.items() if v is not None}


def _describe(artist) -> str:
    if artist.label:
        return artist.label
    if isinstance(artist, FitCurve):
        if isinstance(artist.model, ExpressionFit):
            return "fit"
        return f"{artist.model.name} fit"
    return f"{artist.kind} plot"


def _str(text: str) -> str:
    """A string literal as a person would write it: double quotes, and a raw
    string for LaTeX."""
    if "\\" in text and '"' not in text and not text.endswith("\\"):
        return f'r"{text}"'
    if '"' not in text and "\\" not in text and "\n" not in text:
        return f'"{text}"'
    return repr(text)


def _num(value: float) -> str:
    value = float(value)
    return str(int(value)) if value.is_integer() and abs(value) < 1e15 else repr(value)


def _value(value) -> str:
    if isinstance(value, str):
        return _str(value)
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, int | float):
        return _num(value)
    if isinstance(value, tuple):
        return "(" + ", ".join(_value(v) for v in value) + ")"
    return "[" + ", ".join(_value(v) for v in value) + "]"


def _span(start: int, count: int) -> str:
    return str(start) if count == 1 else f"{start}:{start + count}"


def _letter(index: int) -> str:
    return ascii_lowercase[index] if index < 26 else f"p{index + 1}"


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()


def _identifier(text: str) -> str:
    name = re.sub(r"\W+", "_", text).strip("_") or "col"
    if name[0].isdigit():
        name = f"col{name}"
    if keyword.iskeyword(name):
        name += "_"
    return name


def _index(source: CsvSource, column: str | int) -> int:
    return source.columns.index(column) if isinstance(column, str) else column


def _relative(path: Path, script_dir: Path) -> str:
    try:
        return Path(os.path.relpath(path, script_dir)).as_posix()
    except ValueError:  # another drive on Windows
        return str(path)


def _has_bom(path: Path) -> bool:
    try:
        with open(path, "rb") as file:
            return file.read(3) == b"\xef\xbb\xbf"
    except OSError:
        return False
