"""Platform options for background child processes."""

import sys

WINDOWS_CREATE_NO_WINDOW = 0x08000000


def hidden_subprocess_creation_flags() -> int:
    """Return the Windows flag that suppresses background console windows."""
    if sys.platform == "win32":
        return WINDOWS_CREATE_NO_WINDOW
    return 0
