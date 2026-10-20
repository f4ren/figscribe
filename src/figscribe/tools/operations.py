"""The tools: what an assistant may read and change, and nothing more.

Every change becomes a command on the workspace's history, so it is validated
by the model, shown at once and undoable like a change made by hand. Inputs
arrive as JSON values and are validated strictly against the model's field
types, exactly as a project file is loaded.

Used by the MCP server now and by a built-in chat later; neither Qt nor any
LLM provider is involved here.
"""

from __future__ import annotations

import inspect
import io
import json
import typing
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from matplotlib.backends.backend_agg import FigureCanvasAgg
from pydantic import BaseModel, TypeAdapter, ValidationError, validate_call

from figscribe.commands import (
    Command,
    CommandError,
    InsertItem,
    Macro,
    MoveItem,
    RemoveItem,
    SetField,
    add_panel,
    find,
    remove_artist,
    remove_axes,
)
from figscribe.commands.core import ITEM_FIELDS, walk
from figscribe.fit import FitError, add_fit, refit
from figscribe.io import DataError
from figscribe.model import (
    Axes,
    DataSource,
    Figure,
    FitCurve,
    FitModel,
    Project,
    validate_references,
)
from figscribe.model.artists import Artist
from figscribe.render import render
from figscribe.render.figure import style_context
from figscribe.tools.workspace import Workspace, column_choices

PROTECTED_SOURCE_FIELDS = frozenset({"path", "sha256", "columns"})
"""Set by importing a file in figscribe; a tool must not point a source
elsewhere on the machine. How a file is read (delimiter, header...) may change."""

_REFUSED = (CommandError, FitError, DataError)
"""Errors that mean the request cannot be carried out, as opposed to bugs."""

PREVIEW_DPI = 150.0
"""Enough to judge a layout, at a fraction of the export's pixels."""

_ITEM_TYPES: dict[str, Any] = {
    "sources": DataSource,
    "figures": Figure,
    "axes": Axes,
    "artists": Artist,
}


class ToolError(ValueError):
    """A tool call that cannot be carried out; nothing was changed."""


class Toolbox:
    """The tools, bound to one workspace."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run the tool `name`; raises ToolError, changing nothing, on failure."""
        method: Callable | None = getattr(self, f"tool_{name}", None)
        if method is None:
            raise ToolError(f"unknown tool {name!r}")
        try:
            inspect.signature(method).bind(**arguments)
        except TypeError as exc:
            raise ToolError(f"bad arguments for {name}: {exc}") from None
        try:
            return validate_call(method)(**arguments)
        except ValidationError as exc:
            raise ToolError(
                f"bad arguments for {name}: {_reasons(exc, name)}"
            ) from None
        except _REFUSED as exc:
            raise ToolError(str(exc)) from exc

    # --- reading -------------------------------------------------------------

    def tool_get_project(self) -> dict[str, Any]:
        """The project's structure, without file locations or data values."""
        project = json.loads(self.workspace.project.model_dump_json())
        for source in project["sources"]:
            source["path"] = Path(source["path"]).name
            source.pop("sha256", None)
        figure = self.workspace.figure
        return {
            "project": project,
            "selected": self.workspace.selected,
            "shown_figure": figure.id if figure is not None else None,
            "problems": self._problems(),
        }

    def tool_get_schema(self) -> dict[str, Any]:
        return Project.model_json_schema()

    def tool_list_columns(self) -> dict[str, Any]:
        choices = column_choices(self.workspace.project, self.workspace.data)
        return {
            "columns": [
                {"label": label, "ref": ref.model_dump()} for label, ref in choices
            ]
        }

    def tool_render_preview(self) -> dict[str, Any]:
        """The shown figure as PNG bytes, if the user allowed it."""
        if not self.workspace.allow_preview:
            raise ToolError(
                "the preview image is turned off in figscribe; it shows the data, "
                "so the user has to allow it (Assistant menu)"
            )
        figure = self.workspace.figure
        if figure is None:
            raise ToolError("the project has no figure")
        try:
            fig = render(figure, self.workspace.data)
        except Exception as exc:
            raise ToolError(f"cannot draw the figure: {exc}") from exc
        fig.set_dpi(min(figure.dpi, PREVIEW_DPI))
        buffer = io.BytesIO()
        with style_context(figure):
            FigureCanvasAgg(fig).print_png(buffer, metadata={"Software": None})
        return {"png": buffer.getvalue()}

    def tool_get_python_script(self) -> dict[str, Any]:
        """The script that draws the shown figure, as `figscribe.codegen` writes it."""
        from figscribe.codegen import generate

        figure = self.workspace.figure
        if figure is None:
            raise ToolError("the project has no figure")
        try:
            script = generate(
                self.workspace.project, figure, base_dir=self.workspace.base_dir
            )
        except (NotImplementedError, ValueError) as exc:
            raise ToolError(f"cannot write the script: {exc}") from exc
        return {"script": script}

    # --- changing ------------------------------------------------------------

    def tool_set_field(
        self, object_id: str | None, path: list[str], value: Any
    ) -> dict[str, Any]:
        command = _set_field(self.workspace.project, object_id, path, value)
        return self._push(command, {})

    def tool_insert(
        self,
        parent_id: str | None,
        field: str,
        object: dict[str, Any],
        index: int | None = None,
    ) -> dict[str, Any]:
        command, new_id = _insert(
            self.workspace.project, parent_id, field, object, index
        )
        return self._push(command, {"id": new_id})

    def tool_remove(self, object_id: str) -> dict[str, Any]:
        command = _remove(self.workspace.project, object_id)
        return self._push(command, {"removed": _removed_ids(command)})

    def tool_add_panel(
        self, axes_id: str, side: Literal["right", "left", "above", "below", "inset"]
    ) -> dict[str, Any]:
        command, new = add_panel(self.workspace.project, axes_id, side)
        return self._push(command, {"id": new.id})

    def tool_move(self, object_id: str, index: int) -> dict[str, Any]:
        return self._push(_move(self.workspace.project, object_id, index), {})

    def tool_fit(
        self,
        target_id: str,
        model: dict[str, Any],
        label: str | None = None,
        initial_values: dict[str, float] | None = None,
        residuals: bool = False,
    ) -> dict[str, Any]:
        command, fit_id = _fit(
            self.workspace.project,
            self.workspace.data,
            target_id,
            model,
            label,
            initial_values,
            residuals,
        )
        info = self._push(command, {"id": fit_id})
        info["result"] = find(self.workspace.project, fit_id).result.model_dump()
        return info

    def tool_apply_changes(
        self, description: str, operations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Several changes as one undo step: all of them, or none."""
        if not operations:
            raise ToolError("no operations given")
        staging = self.workspace.project.model_copy(deep=True)
        steps: list[Command] = []
        ids: list[str | None] = []
        for i, operation in enumerate(operations):
            try:
                command, new_id = self._build(staging, dict(operation))
                command.apply(staging)
            except (ToolError, TypeError, *_REFUSED) as exc:
                raise ToolError(
                    f"operation {i} ({operation.get('op')!r}) failed, "
                    f"nothing was changed: {exc}"
                ) from exc
            steps.append(command)
            ids.append(new_id)
        info = self._push(Macro(description or "Assistant changes", steps), {})
        info["ids"] = ids
        return info

    def tool_undo(self) -> dict[str, Any]:
        history = self.workspace.history
        if not history.can_undo:
            raise ToolError("there is nothing to undo")
        text = history.undo_text
        self.workspace.undo()
        return {"undone": text, "problems": self._problems()}

    # --- internals -----------------------------------------------------------

    def _build(
        self, project: Project, operation: dict[str, Any]
    ) -> tuple[Command, str | None]:
        op = operation.pop("op", None)
        builders = {
            "set_field": lambda **a: (_set_field(project, **a), None),
            "insert": lambda **a: _insert(project, **a),
            "remove": lambda **a: (_remove(project, **a), None),
            "move": lambda **a: (_move(project, **a), None),
            "fit": lambda **a: _fit(project, self.workspace.data, **a),
        }
        if op not in builders:
            raise ToolError(
                f"unknown op {op!r}; use set_field, insert, remove, move or fit"
            )
        # The same argument check as a single call of that tool.
        signature = inspect.signature(getattr(self, f"tool_{op}"))
        try:
            signature.bind(**operation)
            arguments = validate_call(_echo(signature))(**operation)
        except ValidationError as exc:
            raise ToolError(f"bad arguments: {_reasons(exc, op)}") from None
        return builders[op](**arguments)

    def _push(self, command: Command, info: dict[str, Any]) -> dict[str, Any]:
        self.workspace.push(command)
        return {**info, "undo_step": command.description, "problems": self._problems()}

    def _problems(self) -> list[str]:
        return [str(issue) for issue in validate_references(self.workspace.project)]


# --- building commands ---------------------------------------------------------


def _set_field(
    project: Project, object_id: str | None, path: list[str], value: Any
) -> SetField:
    if not path:
        raise ToolError("path is empty")
    owner: BaseModel = find(project, object_id)
    for part in path[:-1]:
        owner = _field_value(owner, part)
        if not isinstance(owner, BaseModel):
            raise ToolError(f"{'.'.join(path)}: {part} is not an object with fields")
    name = path[-1]
    if name not in type(owner).model_fields:
        raise ToolError(f"{type(owner).__name__} has no field {name!r}")
    if len(path) == 1 and name in PROTECTED_SOURCE_FIELDS and _is_source(owner):
        raise ToolError(
            f"a data source's {name} is set by importing the file in figscribe"
        )
    annotation = type(owner).model_fields[name].annotation
    parsed = _validate(annotation, value, ".".join(path))
    return SetField(object_id, tuple(path), parsed)


def _insert(
    project: Project,
    parent_id: str | None,
    field: str,
    object: dict[str, Any],
    index: int | None = None,
) -> tuple[InsertItem, str]:
    parent = find(project, parent_id)
    if field not in ITEM_FIELDS.get(type(parent), ()):
        raise ToolError(f"{type(parent).__name__} has no list {field!r} to insert into")
    if field == "sources":
        raise ToolError("data files are imported by the user in figscribe, not here")
    item = _validate(_ITEM_TYPES[field], object, field)
    return InsertItem(parent_id, field, item, index), item.id


def _remove(project: Project, object_id: str) -> Command:
    for obj, _, field in walk(project):
        if obj.id != object_id:
            continue
        if field == "artists":
            return remove_artist(project, object_id)
        if field == "axes":
            return remove_axes(project, object_id)
        if field == "figures":
            return RemoveItem(None, "figures", object_id)
        raise ToolError("data sources cannot be removed here")
    raise ToolError(f"no object with id {object_id!r}")


def _move(project: Project, object_id: str, index: int) -> MoveItem:
    for obj, parent, field in walk(project):
        if obj.id == object_id:
            return MoveItem(parent.id if parent else None, field, object_id, index)
    raise ToolError(f"no object with id {object_id!r}")


def _fit(
    project: Project,
    data,
    target_id: str,
    model: dict[str, Any],
    label: str | None = None,
    initial_values: dict[str, float] | None = None,
    residuals: bool = False,
) -> tuple[Macro, str]:
    """A FitCurve on `target_id`, in the target's axes, fitted at once; with
    `residuals` also their panel below, as the GUI's fit dialog makes it."""
    axes_id = next(
        (
            parent.id
            for obj, parent, field in walk(project)
            if obj.id == target_id and field == "artists"
        ),
        None,
    )
    if axes_id is None:
        raise ToolError(f"no plot with id {target_id!r} to fit")
    fit = FitCurve(
        target=target_id,
        model=_validate(FitModel, model, "model"),
        label=label,
        initial_values=initial_values or {},
    )
    placed = add_fit(project, fit, residuals)
    staging = project.model_copy(deep=True)
    placed.apply(staging)
    fitted = refit(staging, fit.id, data)
    return Macro(fitted.description, [*placed.steps, *fitted.steps]), fit.id


def _validate(annotation: Any, value: Any, where: str) -> Any:
    """`value` as the field type expects it, validated strictly from JSON."""
    try:
        return TypeAdapter(annotation).validate_json(json.dumps(value), strict=True)
    except ValidationError as exc:
        raise ToolError(f"invalid {where}: {_reasons(exc, where)}") from None
    except TypeError as exc:  # not JSON-serializable
        raise ToolError(f"invalid {where}: {exc}") from None


def _is_source(obj: BaseModel) -> bool:
    return isinstance(obj, typing.get_args(typing.get_args(DataSource)[0]))


def _echo(signature: inspect.Signature) -> Callable[..., dict[str, Any]]:
    """A function with `signature` (minus self) that returns its arguments."""

    def echo(**arguments: Any) -> dict[str, Any]:
        return arguments

    echo.__signature__ = signature  # type: ignore[attr-defined]
    echo.__annotations__ = {
        name: p.annotation for name, p in signature.parameters.items()
    }
    return echo


def _reasons(exc: ValidationError, where: str) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or where}: {e['msg']}"
        for e in exc.errors()
    )


def _field_value(owner: BaseModel, name: str) -> Any:
    if name not in type(owner).model_fields:
        raise ToolError(f"{type(owner).__name__} has no field {name!r}")
    return getattr(owner, name)


def _removed_ids(command: Command) -> list[str]:
    steps = command.steps if isinstance(command, Macro) else [command]
    return [s.item_id for s in steps if isinstance(s, RemoveItem)]
