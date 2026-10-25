"""What went wrong, in the words of the person using figscribe.

Errors figscribe raises on purpose (a data file that changed, a refused
change, a fit that failed, a newer project file) are written for them and
pass unchanged. A file the system cannot read or write is told by its reason
and path. Anything else is a bug, and is called one, with the details a
report needs.
"""

from __future__ import annotations

from pydantic import ValidationError

from figscribe.assistant.chat import ChatError
from figscribe.commands import CommandError
from figscribe.fit import FitError
from figscribe.io import DataError
from figscribe.model import SchemaVersionError

FOR_PEOPLE = (
    DataError,
    CommandError,
    FitError,
    ChatError,
    SchemaVersionError,
    NotImplementedError,
)
"""Raised with a message already written for the user."""


def explain(error: BaseException) -> str:
    if isinstance(error, FOR_PEOPLE):
        return str(error)
    # In the GUI only opening a project raises it; commands turn theirs into
    # CommandError.
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return f"not a valid figscribe project: {where}: {first['msg']}"
    if isinstance(error, OSError) and error.strerror:
        return (
            f"{error.strerror}: {error.filename}" if error.filename else error.strerror
        )
    return (
        "This is a bug in figscribe; please report it with the project file. "
        f"({type(error).__name__}: {error})"
    )
