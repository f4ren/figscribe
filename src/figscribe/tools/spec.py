"""Names, descriptions and input schemas of the tools, as an LLM sees them.

One definition for every front end: the MCP server lists these, and a
built-in chat will pass the same to its model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    changes_project: bool


_ID = {"type": ["string", "null"], "description": "Object id; null for the project"}
_PATH = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "description": 'Field path below the object, e.g. ["x", "label"]',
}
_OBJECT_FIELDS = {
    "parent_id": {
        "type": ["string", "null"],
        "description": "Id of the figure (for axes) or axes (for artists); "
        "null for the project (for figures)",
    },
    "field": {"type": "string", "enum": ["figures", "axes", "artists"]},
    "object": {
        "type": "object",
        "description": "The new object as JSON, in the shape of get_schema. Give "
        "it an 'id' of your own to refer to it later in the same apply_changes.",
    },
    "index": {"type": "integer", "description": "Position in the list; end if omitted"},
}
_FIT_FIELDS = {
    "target_id": {"type": "string", "description": "Id of the plot to fit"},
    "model": {
        "type": "object",
        "description": 'Either {"kind": "predefined", "name": "linear" | '
        '"polynomial" | "gaussian" | "lorentzian" | "exponential", "degree": n '
        '(polynomial only)} or {"kind": "expression", "expression": "a*exp(-x/tau)+c", '
        '"parameters": ["a", "tau", "c"]}. Expressions use x, the parameters, pi, '
        "+ - * / ** and exp log log10 sqrt sin cos tan arcsin arccos arctan sinh "
        "cosh tanh abs. Predefined: linear a*x+b; polynomial c0+c1*x+...; gaussian "
        "a*exp(-(x-mu)**2/(2*sigma**2))+c; lorentzian a*gamma**2/((x-x0)**2+"
        "gamma**2)+c; exponential a*exp(-x/tau)+c.",
    },
    "label": {"type": ["string", "null"], "description": "Legend entry"},
    "initial_values": {
        "type": "object",
        "additionalProperties": {"type": "number"},
        "description": "Start values; guessed from the data when omitted",
    },
    "fixed": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Parameters held at their start value instead of fitted; "
        "give that value in initial_values",
    },
    "fit_range": {
        "type": ["array", "null"],
        "items": {"type": "number"},
        "minItems": 2,
        "maxItems": 2,
        "description": "[lower, upper] of x: only the points within are fitted; "
        "omitted fits all",
    },
    "bounds": {
        "type": "object",
        "additionalProperties": {
            "type": "array",
            "items": {"type": ["number", "null"]},
            "minItems": 2,
            "maxItems": 2,
        },
        "description": "[lower, upper] by parameter, null for an open end; the "
        "fitted value stays within them",
    },
    "residuals": {
        "type": "boolean",
        "description": "Also show the residuals in a panel below the plot, "
        "sharing its x axis (added if there is none)",
    },
}


TOOLS: list[ToolSpec] = [
    ToolSpec(
        "get_project",
        "Read the open figscribe project: its figures, axes, plots, data sources "
        "(file names and column names only, never data values), the selected "
        "object and current problems. Call this first, and again whenever you "
        "need fresh ids or values; the user may change the project between calls.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=False,
    ),
    ToolSpec(
        "get_schema",
        "Read the JSON schema of the project format: every field, its type, "
        "allowed values and limits. Call it before building objects for insert "
        "or values for set_field when you are unsure of their shape.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=False,
    ),
    ToolSpec(
        "list_columns",
        "List the data columns that plots and fits can use, as references "
        '({"source": id, "column": name or number}) to put into x, y, xerr, yerr.',
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=False,
    ),
    ToolSpec(
        "render_preview",
        "Return a PNG image of the figure shown in figscribe, exactly as it will "
        "be exported. Use it to check a result visually (overlapping legend, "
        "unreadable labels). Only works if the user allowed it, since the image "
        "shows the data.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=False,
    ),
    ToolSpec(
        "get_python_script",
        "Return the standalone Python script (NumPy, Matplotlib, SciPy for fits) "
        "that draws the shown figure exactly as figscribe does. Give it to the "
        "user when they ask for the code, or read it to explain how the figure "
        "is made.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=False,
    ),
    ToolSpec(
        "set_field",
        "Set one field of an object, e.g. a figure's width_mm, an axis label "
        '(path ["x", "label"]), a plot\'s color or an axis range (path '
        '["x", "limits"], value [0, 10]). One undo step. For more than one '
        "change, prefer apply_changes.",
        {
            "type": "object",
            "properties": {
                "object_id": _ID,
                "path": _PATH,
                "value": {"description": "New value as JSON; null to clear"},
            },
            "required": ["object_id", "path", "value"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "insert",
        "Add a figure, an axes (a panel in the figure's grid, or an inset with "
        '"inset": {"parent": axes id, "bounds": [x0, y0, w, h]}) or an artist '
        '(plot, annotation, residuals) given as JSON. Returns its id. For "kind" '
        "values and fields see get_schema. One undo step.",
        {
            "type": "object",
            "properties": _OBJECT_FIELDS,
            "required": ["parent_id", "field", "object"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "remove",
        "Remove a plot, an axes, a figure or a data source. Fits on a removed "
        "plot and their residuals go with it; a data source takes the plots "
        "that draw from it along, and its file stays on disk. One undo step.",
        {
            "type": "object",
            "properties": {"object_id": {"type": "string"}},
            "required": ["object_id"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "add_panel",
        "Add an empty panel next to the panel axes_id (right, left, above, "
        "below), growing the grid and moving the other panels as needed, or "
        "an inset inside it. Returns the new panel's id. One undo step.",
        {
            "type": "object",
            "properties": {
                "axes_id": {"type": "string"},
                "side": {
                    "type": "string",
                    "enum": ["right", "left", "above", "below", "inset"],
                },
            },
            "required": ["axes_id", "side"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "move",
        "Move an object to another position in its list, e.g. to draw a plot "
        "first. One undo step.",
        {
            "type": "object",
            "properties": {
                "object_id": {"type": "string"},
                "index": {"type": "integer", "minimum": 0},
            },
            "required": ["object_id", "index"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "fit",
        "Fit a model to a line, scatter or errorbar plot with scipy's curve_fit "
        "and add the fitted curve to the same axes. Error bars weight the fit. "
        "Returns the parameters with 1-sigma uncertainties and the reduced "
        "chi-square. One undo step.",
        {
            "type": "object",
            "properties": _FIT_FIELDS,
            "required": ["target_id", "model"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "apply_changes",
        "Apply several changes as ONE undo step, all or nothing: use this for "
        "any request that needs more than one change, so the user can take the "
        "whole request back at once. Each operation is an object with "
        '"op": "set_field" | "insert" | "remove" | "move" | "fit" and that '
        "tool's arguments. Operations run in order; give inserted objects your "
        "own 'id' to refer to them in later operations.",
        {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Short name of the change for the undo menu",
                },
                "operations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {
                                "type": "string",
                                "enum": [
                                    "set_field",
                                    "insert",
                                    "remove",
                                    "move",
                                    "fit",
                                ],
                            }
                        },
                        "required": ["op"],
                    },
                },
            },
            "required": ["description", "operations"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "use_new_data_version",
        "Take a data file that changed since it was imported as it is now: "
        "figscribe hashes it again and reads its columns and rows, keeping how "
        "it is read. Only for a file get_project lists as changed; plots of "
        "columns the new version lacks come back as problems.",
        {
            "type": "object",
            "properties": {"source_id": {"type": "string"}},
            "required": ["source_id"],
            "additionalProperties": False,
        },
        changes_project=True,
    ),
    ToolSpec(
        "undo",
        "Undo the most recent change in figscribe, whoever made it. Use it to "
        "take back a change of yours that turned out wrong.",
        {"type": "object", "properties": {}, "additionalProperties": False},
        changes_project=True,
    ),
]
