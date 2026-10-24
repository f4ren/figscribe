"""The command primitives every model change is built from.

Commands address model objects by id and a field path, never by Python
reference: an object that was removed and restored by undo is a different
Python object with the same id, and a command recorded before that must still
find it. The project itself is addressed as `None`.

Every command assigns new values instead of mutating in place, so that
`validate_assignment` checks each change and a refused change leaves the model
untouched. Values and items are deep-copied on the way in, so the model never
shares an object with the caller or with another place in the model.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterator, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from figscribe.model import Axes, Figure, Identified, Project
from figscribe.model.styles import style_problem, style_problems

ITEM_FIELDS: dict[type[BaseModel], tuple[str, ...]] = {
    Project: ("sources", "figures"),
    Figure: ("axes",),
    Axes: ("artists",),
}
"""The list fields that hold identified objects, per owner type.

They change only through InsertItem, RemoveItem and MoveItem, which keep ids
unique; SetField refuses them.
"""


class CommandError(ValueError):
    """A command that cannot be applied. The model is left unchanged."""


class Command(Protocol):
    @property
    def description(self) -> str:
        """Short imperative text for the undo menu, e.g. "Set x label"."""
        ...

    def apply(self, project: Project) -> None:
        """Perform the change, or raise CommandError and change nothing."""
        ...

    def revert(self, project: Project) -> None:
        """Undo the change. Only valid right after `apply` on the same state."""
        ...


class SetField:
    """Assign `value` to the field at `path` below the object `target`."""

    def __init__(
        self,
        target: str | None,
        path: Sequence[str],
        value: Any,
        description: str | None = None,
    ) -> None:
        self.target = target
        self.path = tuple(path)
        self.value = copy.deepcopy(value)
        self.description = description or f"Set {' '.join(self.path)}".replace("_", " ")
        self._old: Any = None

    def apply(self, project: Project) -> None:
        owner, name = self._owner(project)
        self._old = getattr(owner, name)
        _assign(owner, name, copy.deepcopy(self.value), ".".join(self.path))

    def revert(self, project: Project) -> None:
        owner, name = self._owner(project)
        setattr(owner, name, self._old)

    def _owner(self, project: Project) -> tuple[BaseModel, str]:
        if not self.path:
            raise CommandError("empty field path")
        owner: Any = find(project, self.target)
        *head, name = self.path
        for i, part in enumerate(head):
            _check_field(owner, part)
            owner = getattr(owner, part)
            if not isinstance(owner, BaseModel):
                where = ".".join(self.path[: i + 1])
                raise CommandError(f"{where} is {owner!r}, not an object with fields")
        _check_field(owner, name)
        if name == "id":
            raise CommandError("an id cannot be changed")
        if name in ITEM_FIELDS.get(type(owner), ()):
            raise CommandError(
                f"{name} holds identified objects; "
                "use InsertItem, RemoveItem or MoveItem"
            )
        return owner, name


class InsertItem:
    """Insert `item` into the list `field` of `parent`, at `index` or the end."""

    def __init__(
        self,
        parent: str | None,
        field: str,
        item: Identified,
        index: int | None = None,
        description: str | None = None,
    ) -> None:
        self.parent = parent
        self.field = field
        self.item = item.model_copy(deep=True)
        self.index = index
        self.description = description or f"Add {noun(item)}"

    def apply(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        index = len(items) if self.index is None else self.index
        if not 0 <= index <= len(items):
            raise CommandError(f"index {index} is outside 0..{len(items)}")
        taken = set(_ids_in(project))
        for oid in _ids_in(self.item):
            if oid in taken:
                raise CommandError(f"id {oid!r} is already used in the project")
        _refuse_styles(self.item)
        item = self.item.model_copy(deep=True)
        _assign(owner, self.field, [*items[:index], item, *items[index:]], self.field)

    def revert(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        setattr(owner, self.field, [i for i in items if i.id != self.item.id])


class RemoveItem:
    """Remove the item with id `item_id` from the list `field` of `parent`."""

    def __init__(
        self,
        parent: str | None,
        field: str,
        item_id: str,
        description: str | None = None,
    ) -> None:
        self.parent = parent
        self.field = field
        self.item_id = item_id
        self._description = description
        self._index = -1
        self._item: Identified | None = None

    @property
    def description(self) -> str:
        if self._description:
            return self._description
        return f"Remove {noun(self._item) if self._item else 'item'}"

    def apply(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        self._index = _index_of(items, self.item_id, self.field)
        self._item = items[self._index]
        setattr(owner, self.field, [*items[: self._index], *items[self._index + 1 :]])

    def revert(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        i = self._index
        setattr(owner, self.field, [*items[:i], self._item, *items[i:]])


class MoveItem:
    """Move the item with id `item_id` to position `index` within its list."""

    def __init__(
        self,
        parent: str | None,
        field: str,
        item_id: str,
        index: int,
        description: str | None = None,
    ) -> None:
        self.parent = parent
        self.field = field
        self.item_id = item_id
        self.index = index
        self._description = description
        self._old_index = -1
        self._item: Identified | None = None

    @property
    def description(self) -> str:
        if self._description:
            return self._description
        return f"Move {noun(self._item) if self._item else 'item'}"

    def apply(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        if not 0 <= self.index < len(items):
            raise CommandError(f"index {self.index} is outside 0..{len(items) - 1}")
        self._old_index = _index_of(items, self.item_id, self.field)
        self._item = items[self._old_index]
        _move(owner, self.field, items, self._old_index, self.index)

    def revert(self, project: Project) -> None:
        owner, items = _item_list(project, self.parent, self.field)
        _move(owner, self.field, items, self.index, self._old_index)


class Macro:
    """Several commands applied as one undo step, all or nothing."""

    def __init__(self, description: str, steps: Sequence[Command]) -> None:
        self.description = description
        self.steps = list(steps)

    def apply(self, project: Project) -> None:
        done: list[Command] = []
        try:
            for step in self.steps:
                step.apply(project)
                done.append(step)
        except Exception:
            for step in reversed(done):
                step.revert(project)
            raise

    def revert(self, project: Project) -> None:
        for step in reversed(self.steps):
            step.revert(project)


# --- lookup -----------------------------------------------------------------


def walk(project: Project) -> Iterator[tuple[Identified, Identified | None, str]]:
    """Yield (object, parent, field) for every identified object in `project`.

    The parent is None for the project's own lists.
    """
    for source in project.sources:
        yield source, None, "sources"
    for figure in project.figures:
        yield figure, None, "figures"
        for axes in figure.axes:
            yield axes, figure, "axes"
            for artist in axes.artists:
                yield artist, axes, "artists"


def find(project: Project, oid: str | None) -> BaseModel:
    """Return the object with id `oid`, or the project itself for None."""
    if oid is None:
        return project
    for obj, _, _ in walk(project):
        if obj.id == oid:
            return obj
    raise CommandError(f"no object with id {oid!r}")


def _ids_in(obj: BaseModel) -> Iterator[str]:
    """Every id within `obj`, its own included."""
    if isinstance(obj, Identified):
        yield obj.id
    for name in ITEM_FIELDS.get(type(obj), ()):
        for item in getattr(obj, name):
            yield from _ids_in(item)


def _item_list(
    project: Project, parent: str | None, field: str
) -> tuple[BaseModel, list[Identified]]:
    owner = find(project, parent)
    if field not in ITEM_FIELDS.get(type(owner), ()):
        raise CommandError(f"{type(owner).__name__} has no item list {field!r}")
    return owner, getattr(owner, field)


def _index_of(items: list[Identified], oid: str, field: str) -> int:
    for i, item in enumerate(items):
        if item.id == oid:
            return i
    raise CommandError(f"no item with id {oid!r} in {field}")


def _move(owner: BaseModel, field: str, items: list, src: int, dst: int) -> None:
    rest = [*items[:src], *items[src + 1 :]]
    setattr(owner, field, [*rest[:dst], items[src], *rest[dst:]])


def _check_field(owner: BaseModel, name: str) -> None:
    if name not in type(owner).model_fields:
        raise CommandError(f"{type(owner).__name__} has no field {name!r}")


def _assign(owner: BaseModel, name: str, value: Any, where: str) -> None:
    if (why := style_problem(name, value)) is not None:
        raise CommandError(why)
    if isinstance(value, BaseModel):
        _refuse_styles(value)
    try:
        setattr(owner, name, value)
    except ValidationError as exc:
        reason = "; ".join(e["msg"] for e in exc.errors())
        raise CommandError(f"cannot set {where}: {reason}") from exc


def _refuse_styles(obj: BaseModel) -> None:
    """Refuse an object with a style string Matplotlib would not draw; only
    this object, so that one already in the project blocks nothing else."""
    problems = style_problems(obj)
    if problems:
        raise CommandError(problems[0][1])


def noun(obj: BaseModel) -> str:
    """ "LinePlot" -> "line plot", for default descriptions."""
    return re.sub(r"(?<!^)(?=[A-Z])", " ", type(obj).__name__).lower()
