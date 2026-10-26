"""No setting is forgotten (roadmap U1).

Every field of the model needs a plain name, an explanation for the assistant
(its docstring, which reaches the JSON schema), and either an editor in the
property panel with a tooltip and, if it can be empty, a placeholder, or a
stated reason why the panel has none. A new field fails here until it is wired
up everywhere. Each test lists all gaps at once.
"""

from __future__ import annotations

from pydantic import BaseModel

import figscribe.model
from figscribe.gui.names import FIELD_NAMES
from figscribe.gui.properties import (
    EDITED_ELSEWHERE,
    NONE_TEXT,
    PLACEHOLDERS,
    READ_ONLY,
    SHOWN_WHEN_SET,
    SKIPPED,
    spec_for,
    tip_for,
)
from figscribe.model import Project

SCHEMA = Project.model_json_schema()
CLASSES = [Project] + [
    cls
    for name, cls in vars(figscribe.model).items()
    if isinstance(cls, type) and issubclass(cls, BaseModel) and name in SCHEMA["$defs"]
]
FIELDS = [(cls, name) for cls in CLASSES for name in cls.model_fields]


def _shown_in_the_panel(cls: type[BaseModel], name: str) -> bool:
    return cls not in EDITED_ELSEWHERE and not any(
        name in listed for listed in (SKIPPED, READ_ONLY, SHOWN_WHEN_SET)
    )


def _editors():
    for cls, name in FIELDS:
        if _shown_in_the_panel(cls, name):
            spec = spec_for(name, cls.model_fields[name].annotation)
            if spec is not None:
                yield cls, name, spec


def test_every_field_has_a_plain_name() -> None:
    assert sorted({name for _, name in FIELDS if name not in FIELD_NAMES}) == []


def test_every_field_is_explained_to_the_assistant() -> None:
    missing = []
    for cls, name in FIELDS:
        properties = (SCHEMA if cls is Project else SCHEMA["$defs"][cls.__name__])[
            "properties"
        ]
        # A constant, such as a plot's kind, is explained by its value.
        if "const" not in properties[name] and not properties[name].get("description"):
            missing.append(f"{cls.__name__}.{name}")
    assert missing == []


def test_every_field_has_an_editor_or_a_reason() -> None:
    missing = [
        f"{cls.__name__}.{name}"
        for cls, name in FIELDS
        if _shown_in_the_panel(cls, name)
        and spec_for(name, cls.model_fields[name].annotation) is None
    ]
    assert missing == []
    reasons = [
        *SKIPPED.values(),
        *READ_ONLY.values(),
        *SHOWN_WHEN_SET.values(),
        *EDITED_ELSEWHERE.values(),
    ]
    assert all(isinstance(r, str) and len(r) > 10 for r in reasons)


def test_every_editor_has_a_tooltip() -> None:
    missing = [
        f"{cls.__name__}.{name}"
        for cls, name, spec in _editors()
        if spec.kind not in ("model", "part") and tip_for(cls, name) is None
    ]
    assert missing == []


def test_every_field_that_can_be_empty_says_what_empty_means() -> None:
    # A choice offers "empty" as an entry, and so do the marker buttons; a
    # text field shows it greyed out while nothing is typed.
    def told(name: str, kind: str) -> bool:
        listed = kind in ("choice", "column", "array") or "marker" in name
        return name in (NONE_TEXT if listed else PLACEHOLDERS)

    missing = [
        f"{cls.__name__}.{name}"
        for cls, name, spec in _editors()
        if spec.optional and spec.kind != "part" and not told(name, spec.kind)
    ]
    assert missing == []
