"""Shared base class and helpers for all model types."""

from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for every model class.

    Strict validation on purpose: a project file is a reproducibility artifact,
    so a string where a number belongs is an error, not something to coerce.
    Unknown keys are refused so that a file written by a newer figscribe fails
    loudly instead of silently dropping fields.

    Numbers must be finite: an infinite width or range cannot be drawn. Fit
    results are the exception (`AnyFloat`), since curve_fit reports inf
    uncertainties for an inestimable covariance. Those are written as the JSON
    extensions Infinity and NaN, which the loader reads back; the default would
    write null, and the file would then refuse to load.
    """

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        allow_inf_nan=False,
        ser_json_inf_nan="constants",
        use_attribute_docstrings=True,  # the assistant reads them in the schema
    )


AnyFloat = Annotated[float, Field(allow_inf_nan=True)]
"""A float that may be infinite or NaN, where a field means it."""


def new_id() -> str:
    """Return a short identifier, stable across save and load."""
    return uuid.uuid4().hex[:12]


class Identified(StrictModel):
    """A model object that other objects can refer to by id."""

    id: str = Field(default_factory=new_id, min_length=1)
