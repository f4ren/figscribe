"""The program the installers freeze: what `figscribe` does, as a script.

PyInstaller needs a file to start from; the command `figscribe` of a pip
installation is generated, and in a bundle it does not exist. `figscribe script`
and `figscribe mcp` work through this file too: the bundle's program takes the
same arguments.
"""

import sys

from figscribe.cli import main

if __name__ == "__main__":
    sys.exit(main())
