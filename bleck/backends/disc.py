"""Disc-level operations, delegated to external tools.

`wit` handles ISO/WBFS and the rebuild; it cannot read RVZ, so `dolphin-tool`
converts those first. Both are probed before use so a missing dependency
produces an actionable message rather than a traceback.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
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


class ImageFormat(Enum):
    """Output disc image formats."""

    ISO = "iso"
    RVZ = "rvz"

    @property
    def suffix(self) -> str:
        return f".{self.value}"

    @classmethod
    def for_path(cls, path: Path) -> ImageFormat:
        """Infer the format from an output filename, defaulting to ISO."""
        suffix = path.suffix.lower().lstrip(".")
        return next((f for f in cls if f.value == suffix), cls.ISO)


def build(source: Path, out: Path) -> None:
    """Rebuild an extracted filesystem into an ISO.

    --align-files is mandatory: upstream requires it and omitting it fails
    subtly rather than loudly. It is passed unconditionally so callers cannot
    forget it.
    """
    wit = find_tool(WIT)
    _run([wit, "COPY", str(source), str(out), "--iso", "--align-files"])


# dolphin-tool requires these explicitly for RVZ; these are its suggested
# values. Level 5 rather than the 19 seen on retail dumps — 19 is far slower
# for a few percent, which is the wrong trade for an iteration artifact.
RVZ_BLOCK_SIZE = "131072"
RVZ_COMPRESSION = "zstd"
RVZ_LEVEL = "5"


def convert_to_rvz(src: Path, dest: Path) -> None:
    """ISO -> RVZ. Roughly a 14x size reduction, and Dolphin reads it natively."""
    tool = find_tool(DOLPHIN_TOOL)
    _run(
        [
            tool,
            "convert",
            "-f",
            "rvz",
            "-b",
            RVZ_BLOCK_SIZE,
            "-c",
            RVZ_COMPRESSION,
            "-l",
            RVZ_LEVEL,
            "-i",
            str(src),
            "-o",
            str(dest),
        ]
    )


def build_image(
    source: Path, out: Path, image_format: ImageFormat, keep_iso: bool = False
) -> None:
    """Rebuild an extracted filesystem into a disc image.

    `wit` can only write ISO, so RVZ goes through a temporary ISO which is
    removed afterwards unless `keep_iso` is set.
    """
    if image_format is ImageFormat.ISO:
        build(source, out)
        return

    # A distinct hidden name, not `out.with_suffix('.iso')` — that would collide
    # with a real ISO the user already has, and wit refuses to overwrite.
    staging_iso = out.parent / f".{out.stem}.staging.iso"
    staging_iso.unlink(missing_ok=True)
    build(source, staging_iso)
    try:
        convert_to_rvz(staging_iso, out)
    finally:
        if keep_iso:
            staging_iso.replace(out.with_suffix(".iso"))
        else:
            staging_iso.unlink(missing_ok=True)


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


# dolphin-tool header labels -> DiscInfo attribute names.
_DOLPHIN_FIELDS = {
    "Internal Name": "name",
    "Region": "region",
    "Game ID": "ids",
    "Country": "disc_type",
}


def identify(image: Path) -> DiscInfo:
    """Read disc header fields. Returns an empty DiscInfo if unreadable."""
    if is_rvz(image):
        return _identify_rvz(image)
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


def _identify_rvz(image: Path) -> DiscInfo:
    """RVZ headers come from dolphin-tool; wit cannot read the format."""
    try:
        tool = find_tool(DOLPHIN_TOOL)
    except DiscError:
        return DiscInfo()
    result = subprocess.run(
        [tool, "header", "-i", str(image)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return DiscInfo()

    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        attr = _DOLPHIN_FIELDS.get(key.strip())
        if attr and attr not in found:
            found[attr] = value.strip()
    return DiscInfo(**found)
