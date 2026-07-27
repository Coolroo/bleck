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
