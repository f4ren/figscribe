"""The project: the root of the model, and its JSON persistence."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import Field

from figscribe.model.base import StrictModel
from figscribe.model.data import DataSource
from figscribe.model.figure import Figure

SCHEMA_VERSION = 1
"""Bump whenever the on-disk shape changes, and add a migration below."""


class Project(StrictModel):
    schema_version: int = Field(SCHEMA_VERSION, ge=1)
    """Version of this file format; older files are migrated when they are read."""
    figscribe_version: str = ""
    """Version that wrote the file; recorded for reproducibility, not for logic."""
    created: datetime | None = None
    """When the project was first saved; None if unknown."""
    sources: list[DataSource] = Field(default_factory=list)
    """The data files the figures plot from."""
    figures: list[Figure] = Field(default_factory=list)
    """The figures of the project."""


class SchemaVersionError(ValueError):
    """A project file this build cannot read."""


def dumps(project: Project) -> str:
    """Serialize a project to the JSON stored in a .figscribe file."""
    return project.model_dump_json(indent=2)


def loads(text: str) -> Project:
    """Parse a project file, migrating older schema versions on the way.

    Always goes through `model_validate_json`: in strict mode a JSON array
    arrives as a `list` and would be rejected by a `tuple` field, so parsing to
    a dict first and validating that would break roundtripping.
    """
    version = _peek_schema_version(text)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"project file has schema version {version}, "
            f"this build of figscribe reads up to {SCHEMA_VERSION}"
        )
    if version < SCHEMA_VERSION:
        text = _migrate(text, version)
    return Project.model_validate_json(text)


def _peek_schema_version(text: str) -> int:
    """Read just the schema version, before the model shape is assumed."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaVersionError("not a valid project file") from exc
    if not isinstance(raw, dict) or "schema_version" not in raw:
        raise SchemaVersionError("project file has no schema_version")
    version = raw["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise SchemaVersionError(f"schema_version is not an integer: {version!r}")
    return version


def _migrate(text: str, from_version: int) -> str:
    """Upgrade a project file to SCHEMA_VERSION.

    There is nothing to migrate yet. Each future step gets its own function and
    its own test with a stored example file of that version.
    """
    raise SchemaVersionError(f"no migration from schema version {from_version}")
