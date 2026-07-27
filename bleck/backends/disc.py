"""Disc-level operations, delegated to external tools.

`wit` handles ISO/WBFS and the rebuild; it cannot read RVZ, so `dolphin-tool`
converts those first. Both are probed before use so a missing dependency
produces an actionable message rather than a traceback.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bleck.common import env

WIT = "wit"
DOLPHIN_TOOL = "dolphin-tool"

# Debian ships dolphin-tool under /usr/games, which is not always on PATH.
_EXTRA_PATHS = [Path("/usr/games")]

INSTALL_HINTS = {
    WIT: "install Wiimms ISO Tools:  sudo apt install wit",
    DOLPHIN_TOOL: "install Dolphin for dolphin-tool:  sudo apt install dolphin-emu",
}


class DiscError(Exception):
    pass


# Declared overrides, checked before PATH.
_OVERRIDES = {WIT: env.WIT, DOLPHIN_TOOL: env.DOLPHIN_TOOL}


def find_tool(name: str) -> str:
    override = _OVERRIDES.get(name)
    if override is not None:
        configured = env.path(override)
        if configured is not None:
            return str(configured)

    found = shutil.which(name)
    if found:
        return found
    for base in _EXTRA_PATHS:
        candidate = base / name
        if candidate.exists():
            return str(candidate)
    hint = INSTALL_HINTS.get(name, "")
    raise DiscError(f"{name} not found on PATH" + (f"\n  {hint}" if hint else ""))


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscError(f"{Path(args[0]).name} failed:\n{detail}")


def is_rvz(path: Path) -> bool:
    return path.suffix.lower() == ".rvz"


def convert_rvz(src: Path, dest: Path) -> Path:
    """RVZ -> ISO. wit cannot read RVZ, so this must happen first."""
    tool = find_tool(DOLPHIN_TOOL)
    _run([tool, "convert", "-f", "iso", "-i", str(src), "-o", str(dest)])
    return dest


def extract(image: Path, dest: Path, keep_iso: bool = False) -> None:
    """Extract a disc image's data partition to a directory."""
    wit = find_tool(WIT)

    source = image
    temp_iso: Path | None = None
    if is_rvz(image):
        temp_iso = dest.parent / f"{image.stem}.iso"
        if not temp_iso.exists():
            convert_rvz(image, temp_iso)
        source = temp_iso

    _run([wit, "EXTRACT", str(source), "--dest", str(dest), "--psel", "data"])

    if temp_iso is not None and not keep_iso:
        temp_iso.unlink(missing_ok=True)


def build(source: Path, out: Path) -> None:
    """Rebuild an extracted filesystem into an ISO.

    --align-files is mandatory: upstream requires it and omitting it fails
    subtly rather than loudly. It is passed unconditionally so callers cannot
    forget it.
    """
    wit = find_tool(WIT)
    _run([wit, "COPY", str(source), str(out), "--iso", "--align-files"])


@dataclass(frozen=True)
class DiscInfo:
    """Header fields read from a disc image. Empty strings mean "not reported"."""

    name: str = ""
    region: str = ""
    ids: str = ""
    disc_type: str = ""

    @property
    def is_empty(self) -> bool:
        return not any((self.name, self.region, self.ids, self.disc_type))

    def describe(self) -> list[DiscField]:
        """Populated fields, in display order."""
        fields = [
            DiscField("Disc name", self.name),
            DiscField("ID Region", self.region),
            DiscField("Disc & part IDs", self.ids),
            DiscField("File & disc type", self.disc_type),
        ]
        return [field for field in fields if field.value]


@dataclass(frozen=True)
class DiscField:
    label: str
    value: str


# wit DUMP labels -> DiscInfo attribute names.
_WIT_FIELDS = {
    "Disc name": "name",
    "ID Region": "region",
    "Disc & part IDs": "ids",
    "File & disc type": "disc_type",
}


def identify(image: Path) -> DiscInfo:
    """Read disc header fields. Returns an empty DiscInfo if unreadable."""
    try:
        wit = find_tool(WIT)
    except DiscError:
        return DiscInfo()
    result = subprocess.run(
        [wit, "DUMP", str(image)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return DiscInfo()

    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        attr = _WIT_FIELDS.get(key.strip())
        if attr and attr not in found:
            found[attr] = value.strip()
    return DiscInfo(**found)
