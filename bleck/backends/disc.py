"""Disc-level operations, delegated to external tools.

`wit` handles ISO/WBFS and the rebuild; it cannot read RVZ, so `dolphin-tool`
converts those first.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from bleck import platforms
from bleck.common import env
from bleck.platforms import ToolKey


class DiscError(Exception):
    pass


def find_tool(key: ToolKey) -> str:
    """Locate an external tool: explicit override, then PATH, then known dirs.

    Where to look is platform data (`bleck/platforms/`), not logic here, and so
    is which variable overrides it (`ToolKey.override`).
    """
    configured = env.path(key.override)
    if configured is not None:
        return str(configured)

    location = platforms.current().tool(key)

    for candidate in location.names:
        found = shutil.which(candidate)
        if found:
            return found

    for directory in location.search_paths():
        for candidate in location.names:
            path = directory.expanduser() / candidate
            if path.exists():
                return str(path)

    tried = ", ".join(location.names)
    raise DiscError(
        f"{key} not found (looked for: {tried})"
        + (f"\n  {location.hint}" if location.hint else "")
    )


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise DiscError(f"{Path(args[0]).name} failed:\n{detail}")


def _ensure_parent(path: Path) -> None:
    """Create an output's parent directory before an external tool writes there.

    Neither wit nor DolphinTool creates missing parents, and both report the
    failure uninformatively (DolphinTool says only "Conversion failed").
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def is_rvz(path: Path) -> bool:
    return path.suffix.lower() == ".rvz"


def convert_rvz(src: Path, dest: Path) -> Path:
    """RVZ -> ISO. wit cannot read RVZ, so this must happen first."""
    tool = find_tool(ToolKey.DOLPHIN_TOOL)
    _ensure_parent(dest)
    _run([tool, "convert", "-f", "iso", "-i", str(src), "-o", str(dest)])
    return dest


def extract(image: Path, dest: Path, keep_iso: bool = False) -> None:
    """Extract a disc image's data partition to a directory."""
    wit = find_tool(ToolKey.WIT)

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
    """Output disc image formats.

    WBFS (~424 MB) is the safe default for sharing: every Dolphin build reads
    it. RVZ is smaller (~249 MB) but needs Dolphin 5.0-12188 (2020) or newer.
    """

    ISO = "iso"
    RVZ = "rvz"
    WBFS = "wbfs"

    @property
    def suffix(self) -> str:
        return f".{self.value}"

    @classmethod
    def for_path(cls, path: Path) -> ImageFormat:
        """Infer the format from an output filename, defaulting to ISO."""
        suffix = path.suffix.lower().lstrip(".")
        return next((f for f in cls if f.value == suffix), cls.ISO)


def build(source: Path, out: Path, wit_format: str = "--iso") -> None:
    """Rebuild an extracted filesystem into an image wit can write.

    ⚠️ `--align-files` is mandatory and fails subtly when omitted, so it is
    passed unconditionally. `--overwrite` likewise: `guard_overwrite` has
    already decided whether clobbering is allowed.
    """
    wit = find_tool(ToolKey.WIT)
    _ensure_parent(out)
    _run(
        [
            wit,
            "COPY",
            str(source),
            str(out),
            wit_format,
            "--align-files",
            "--overwrite",
        ]
    )


# dolphin-tool requires these explicitly for RVZ. Level 5, not the 19 seen on
# retail dumps: 19 is far slower for a few percent.
RVZ_BLOCK_SIZE = "131072"
RVZ_COMPRESSION = "zstd"
RVZ_LEVEL = "5"


def convert_to_rvz(src: Path, dest: Path) -> None:
    """ISO -> RVZ. Roughly a 14x size reduction; Dolphin reads it natively."""
    tool = find_tool(ToolKey.DOLPHIN_TOOL)
    _ensure_parent(dest)
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

    if image_format is ImageFormat.WBFS:
        build(source, out, "--wbfs")
        return

    # A distinct hidden name, not `out.with_suffix('.iso')`: that could collide
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
        wit = find_tool(ToolKey.WIT)
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
        tool = find_tool(ToolKey.DOLPHIN_TOOL)
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
