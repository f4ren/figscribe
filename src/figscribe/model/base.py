"""Shared base class and helpers for all model types."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for every model class.

    Strict validation on purpose: a project file is a reproducibility artifact,
    so a string where a number belongs is an error, not something to coerce.
    Unknown keys are refused so that a file written by a newer figscribe fails
    loudly instead of silently dropping fields.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
    )


def new_id() -> str:
    """Return a short identifier, stable across save and load."""
    return uuid.uuid4().hex[:12]


class Identified(StrictModel):
    """A model object that other objects can refer to by id."""

    id: str = Field(default_factory=new_id, min_length=1)
