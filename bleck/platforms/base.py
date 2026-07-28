"""Platform profile types. Differences are data, not scattered conditionals:
each supported OS supplies one `PlatformProfile`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

WIT = "wit"
DOLPHIN_TOOL = "dolphin-tool"
DOLPHIN = "dolphin"
"""The emulator itself — a separate binary from `dolphin-tool`, easy to conflate
because they ship into the same directory. Only one of them boots a game.
"""

WSTRT = "wstrt"
"""Wiimms StaticR Tool, from the SZS toolset (a different package from `wit`).

Embeds the Gecko loader into the game's DOL, using its own code handler.
"""

PPC_GCC = "powerpc-gcc"
"""The cross-compiler that builds code mods for the Wii's PowerPC CPU.

Only the C compiler is looked up; `g++`, `ld` and `objcopy` are derived from its
directory and prefix, so two installed toolchains cannot be mixed.
"""


ALL_TOOLS = [WIT, DOLPHIN_TOOL, DOLPHIN, WSTRT, PPC_GCC]
"""Every external tool `bleck` knows how to find. The completeness test walks
this list, so a key no platform describes fails everywhere, not just there.
"""


@dataclass(frozen=True)
class ToolLocation:
    """How to find one external tool on one platform."""

    names: list[str]
    """Executable names to try, in order."""

    directories: list[str] = field(default_factory=list)
    """Extra places to look when the tool is not on PATH."""

    hint: str = ""
    """What to tell the user when it cannot be found."""

    def search_paths(self) -> list[Path]:
        return [Path(d) for d in self.directories]


@dataclass(frozen=True)
class PlatformProfile:
    """Everything that differs between operating systems."""

    name: str

    venv_bin: str
    """Subdirectory holding venv executables: `bin` or `Scripts`."""

    tools: dict[str, ToolLocation]

    ignored_filenames: frozenset[str] = frozenset()
    """Files the OS creates that must never reach a built disc."""

    ignored_prefixes: frozenset[str] = frozenset()
    """Filename prefixes to ignore, e.g. AppleDouble `._` sidecars."""

    strip_readonly_on_delete: bool = False
    """Whether deleting a read-only file needs the bit cleared first."""

    def tool(self, key: str) -> ToolLocation:
        return self.tools.get(key, ToolLocation(names=[key]))

    def is_ignored(self, filename: str) -> bool:
        """Whether a filename is OS clutter rather than game content."""
        if filename in self.ignored_filenames:
            return True
        return any(filename.startswith(p) for p in self.ignored_prefixes)
