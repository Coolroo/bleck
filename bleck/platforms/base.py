"""Platform profile types.

Platform differences are data, not conditionals scattered through the code:
each supported OS supplies one `PlatformProfile` and the rest of the toolkit
reads from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

WIT = "wit"
DOLPHIN_TOOL = "dolphin-tool"
DOLPHIN = "dolphin"
"""The emulator itself, which is a different binary from `dolphin-tool`.

They ship together and sit in the same directory, which makes them easy to
conflate — but only one of them boots a game, and only the other one converts
an image. Finding the wrong one fails confusingly, so they are separate keys.
"""

WSTRT = "wstrt"
"""Wiimms StaticR Tool, from the SZS toolset -- a different package from `wit`.

Used to embed the Gecko loader into the game's DOL. It carries its own copy of
the code handler, which is why `bleck` never has to ship one.
"""

PPC_GCC = "powerpc-gcc"
"""The cross-compiler that builds code mods for the Wii's PowerPC CPU.

Only the C compiler is looked up. Its siblings — `g++`, `ld`, `objcopy` — always
live in the same directory under the same prefix, so deriving them from this one
is more reliable than searching for each separately: a machine with two
toolchains installed could otherwise mix a compiler from one with a linker from
the other, which fails in ways that look like source bugs.
"""


ALL_TOOLS = [WIT, DOLPHIN_TOOL, DOLPHIN, WSTRT, PPC_GCC]
"""Every external tool `bleck` knows how to find.

Declared here rather than rebuilt by each caller so that adding a tool is one
edit. The completeness test walks this list, so a new key that some platform
forgot to describe fails immediately instead of only on that platform.
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
