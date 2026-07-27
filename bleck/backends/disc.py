"""Disc-level operations, delegated to external tools.

`wit` handles ISO/WBFS and the rebuild; it cannot read RVZ, so `dolphin-tool`
converts those first. Both are probed before use so a missing dependency
produces an actionable message rather than a traceback.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

WIT = "wit"
DOLPHIN_TOOL = "dolphin-tool"

# Debian ships dolphin-tool under /usr/games, which is not always on PATH.
_EXTRA_PATHS = [Path("/usr/games")]

INSTALL_HINTS = {
    WIT: "install Wiimms ISO Tools:  sudo apt install wit",
    DOLPHIN_TOOL: "install Dolphin (provides dolphin-tool):  sudo apt install dolphin-emu",
}


class DiscError(Exception):
    pass


def find_tool(name: str) -> str:
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
    result = subprocess.run(args, capture_output=True, text=True)
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


def identify(image: Path) -> dict[str, str]:
    """Return disc header fields, or {} if the image cannot be read."""
    try:
        wit = find_tool(WIT)
    except DiscError:
        return {}
    result = subprocess.run([wit, "DUMP", str(image)], capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in {"Disc name", "ID Region", "Disc & part IDs", "File & disc type"}:
            fields[key] = value.strip()
    return fields
