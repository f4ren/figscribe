"""Style strings Matplotlib accepts: colors, markers, line styles, color maps,
legend locations and style sheets.

The model keeps them as plain strings, since Matplotlib accepts many forms.
The commands check them when they are set, so that a bad one is refused in
plain words instead of failing when the figure is drawn; validate_references
reports one that a project file already has. Matplotlib is imported only when
a check runs, so the model can be read without it.
"""

from __future__ import annotations

from pydantic import BaseModel

KINDS = {
    "color": "color",
    "edgecolor": "color",
    "grid_color": "color",
    "left_out_color": "color",
    "marker": "marker",
    "left_out_marker": "marker",
    "linestyle": "line style",
    "cmap": "color map",
    "location": "legend location",
    "stylesheet": "style sheet",
}
"""Style fields of the model, by name, and what they hold."""

EXAMPLES = {
    "color": "use a name such as blue or tab:orange, or a code such as #1f77b4",
    "marker": "use for example o, s, ^, x or +",
    "line style": "use -, --, -., : or none",
    "color map": "use for example viridis, magma or gray",
    "legend location": "use for example best, upper right or lower left",
    "style sheet": "use a name such as classic or ggplot, or the path of an "
    ".mplstyle file",
}


def style_problem(name: str, value: object) -> str | None:
    """Why `value` cannot be the style field `name`; None if it can, or if
    `name` is not a style field."""
    kind = KINDS.get(name)
    if kind is None or not isinstance(value, str) or _accepted(kind, value):
        return None
    return f"{value!r} is not a {kind}; {EXAMPLES[kind]}"


def style_problems(obj: BaseModel) -> list[tuple[str, str]]:
    """(dotted field path, why) for every refused style string of `obj` and
    its parts; lists of other objects are left to their own checks."""
    found = []
    for name in type(obj).model_fields:
        value = getattr(obj, name)
        if isinstance(value, BaseModel):
            found += [(f"{name}.{path}", why) for path, why in style_problems(value)]
        elif (why := style_problem(name, value)) is not None:
            found.append((name, why))
    return found


def _accepted(kind: str, value: str) -> bool:
    if kind == "color":
        from matplotlib.colors import is_color_like

        return is_color_like(value)
    if kind == "color map":
        import matplotlib

        return value in matplotlib.colormaps
    if kind == "legend location":
        from matplotlib.legend import Legend

        return value in Legend.codes
    if kind == "style sheet":
        # A file is looked for when the figure is drawn, next to the project.
        if value.lower().endswith(".mplstyle"):
            return True
        import matplotlib.style

        return value in matplotlib.style.available
    from matplotlib.lines import Line2D

    keyword = "marker" if kind == "marker" else "linestyle"
    try:  # a line refuses what it cannot draw, in all its forms
        Line2D([], [], **{keyword: value})
    except ValueError:
        return False
    return True
