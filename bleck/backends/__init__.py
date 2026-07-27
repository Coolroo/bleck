"""Wrappers around external tools.

Disc I/O is delegated rather than reimplemented — `wit` for ISO/WBFS and
`dolphin-tool` for RVZ, which `wit` cannot read.
"""

from . import disc

__all__ = ["disc"]
