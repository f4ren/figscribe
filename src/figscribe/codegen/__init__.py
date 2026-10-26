"""The code generator: a figure as a standalone Python script.

The script needs only NumPy, Matplotlib and, for fits, SciPy. It makes the
same Matplotlib calls the renderer makes, so it draws the same figure; the
equivalence test holds the two together.
"""

from figscribe.codegen.script import file_stems, generate, script_name

__all__ = ["file_stems", "generate", "script_name"]
