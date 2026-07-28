"""Per-platform behaviour, selected once at import.

Add support for an OS by adding a module with a `PROFILE` and listing it here —
nothing else in the toolkit needs to change.
"""

from __future__ import annotations

import platform as _platform

from . import linux, macos, windows
from .base import (
    ALL_TOOLS,
    DOLPHIN,
    DOLPHIN_TOOL,
    PPC_GCC,
    WIT,
    WSTRT,
    PlatformProfile,
    ToolLocation,
)

_PROFILES = {
    "Linux": linux.PROFILE,
    "Darwin": macos.PROFILE,
    "Windows": windows.PROFILE,
}

# Unknown platforms behave like Linux — the sane default for anything POSIX.
CURRENT: PlatformProfile = _PROFILES.get(_platform.system(), linux.PROFILE)


def current() -> PlatformProfile:
    return CURRENT


__all__ = [
    "ALL_TOOLS",
    "CURRENT",
    "DOLPHIN",
    "DOLPHIN_TOOL",
    "PPC_GCC",
    "WIT",
    "WSTRT",
    "PlatformProfile",
    "ToolLocation",
    "current",
    "linux",
    "macos",
    "windows",
]
