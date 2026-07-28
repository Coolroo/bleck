"""Wrappers around external tools: `wit` for ISO/WBFS, `dolphin-tool` for RVZ
(which `wit` cannot read)."""

from . import disc

__all__ = ["disc"]
