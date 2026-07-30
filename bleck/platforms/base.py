"""Platform profile types. Differences are data, not scattered conditionals:
each supported OS supplies one `PlatformProfile`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from bleck.common import env


# ⚠️ Member names are free; the *values* are not. `PlatformProfile.tool` falls
# back to `ToolLocation(names=[key])`, so a value is the executable name
# searched for. `StrEnum` is required, not stylistic -- see D99.
class ToolKey(StrEnum):
    """An external program `bleck` shells out to, and looks up per platform.

    ⚠️ Each value doubles as the executable name to search for, used when a
    platform profile has nothing to say about the tool.
    """

    WIT = "wit"
    """Wiimms ISO Tool: extracts and rebuilds disc images."""

    DOLPHIN_TOOL = "dolphin-tool"
    """Dolphin's headless converter, the only thing here that reads RVZ."""

    DOLPHIN = "dolphin"
    """The emulator itself — a separate binary from `dolphin-tool`, easy to
    conflate because they ship into the same directory. Only one boots a game.
    """

    WSTRT = "wstrt"
    """Wiimms StaticR Tool, from the SZS toolset (a different package from `wit`).

    Embeds the Gecko loader into the game's DOL, using its own code handler.
    """

    PPC_GCC = "powerpc-gcc"
    """The cross-compiler that builds code mods for the Wii's PowerPC CPU.

    Only the C compiler is looked up; `g++`, `ld` and `objcopy` are derived from
    its directory and prefix, so two installed toolchains cannot be mixed.
    """

    @property
    def override(self) -> env.EnvVar:
        """The variable that names this tool's path outright, checked before PATH.

        Belongs to the tool, not to a platform: `BLECK_WIT` means the same
        everywhere, so it would be repeated once per OS if it lived on
        `ToolLocation`.
        """
        return _TOOL_OVERRIDES[self]


#: Kept beside the enum rather than in its body, where the Enum metaclass would
#: read a dict as another member. Complete by test, which the dict this replaced
#: in `backends.disc` never was.
_TOOL_OVERRIDES = {
    ToolKey.WIT: env.WIT,
    ToolKey.DOLPHIN_TOOL: env.DOLPHIN_TOOL,
    ToolKey.DOLPHIN: env.DOLPHIN,
    ToolKey.WSTRT: env.WSTRT,
    ToolKey.PPC_GCC: env.PPC_GCC,
}


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

    tools: dict[ToolKey, ToolLocation]

    ignored_filenames: frozenset[str] = frozenset()
    """Files the OS creates that must never reach a built disc."""

    ignored_prefixes: frozenset[str] = frozenset()
    """Filename prefixes to ignore, e.g. AppleDouble `._` sidecars."""

    strip_readonly_on_delete: bool = False
    """Whether deleting a read-only file needs the bit cleared first."""

    def tool(self, key: ToolKey) -> ToolLocation:
        """How to find `key` here. Undescribed tools are searched for by value."""
        return self.tools.get(key, ToolLocation(names=[key.value]))

    def is_ignored(self, filename: str) -> bool:
        """Whether a filename is OS clutter rather than game content."""
        if filename in self.ignored_filenames:
            return True
        return any(filename.startswith(p) for p in self.ignored_prefixes)
