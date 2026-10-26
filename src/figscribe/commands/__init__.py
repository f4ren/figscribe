"""Commands: the only way the GUI changes the model, each one undoable.

Primitives (SetField, InsertItem, RemoveItem, MoveItem) address objects by id;
Macro bundles them into one undo step. The functions in `ops` build the macros
for user-level actions, such as removing an artist together with its fits.
"""

from figscribe.commands.core import (
    Command,
    CommandError,
    InsertItem,
    Macro,
    MoveItem,
    RemoveItem,
    SetField,
    find,
)
from figscribe.commands.history import History
from figscribe.commands.ops import (
    add_figure,
    add_panel,
    copy_style,
    drawing_order,
    duplicate_figure,
    remove_artist,
    remove_artists,
    remove_axes,
    remove_figure,
    remove_source,
    to_front,
)

__all__ = [
    "Command",
    "CommandError",
    "History",
    "InsertItem",
    "Macro",
    "MoveItem",
    "RemoveItem",
    "SetField",
    "find",
    "add_figure",
    "add_panel",
    "copy_style",
    "drawing_order",
    "duplicate_figure",
    "remove_artist",
    "remove_artists",
    "remove_axes",
    "remove_figure",
    "remove_source",
    "to_front",
]
