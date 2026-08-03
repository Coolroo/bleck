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


@dataclass(frozen=True)
class ToolSearch:
    """What looking for one external tool turned up.

    `find_tool` is this plus a raise. Anything that wants to *report* rather
    than fail -- `bleck doctor`, the CLI's preflight check -- reads the same
    search, so there is one answer to "where is wit" and not two.
    """

    key: ToolKey

    path: str = ""
    """The executable, or empty when nothing usable was found."""

    where: str = ""
    """How it was reached: an override variable, `PATH`, or a directory."""

    problem: str = ""
    """Why nothing was found, already written for a user to read."""

    override_is_broken: bool = False
    """Whether an override variable names a path that does not exist.

    The distinction the exit code turns on: this is a misconfiguration somebody
    can fix, where a tool that is simply absent may be one they never wanted.
    """

    @property
    def found(self) -> bool:
        return bool(self.path)


def locate(key: ToolKey) -> ToolSearch:
    """Look for an external tool: explicit override, then PATH, then known dirs.

    Where to look is platform data (`bleck/platforms/`), not logic here, and so
    is which variable overrides it (`ToolKey.override`).
    """
    location = platforms.current().tool(key)
    hint = f"\n  {location.hint}" if location.hint else ""

    configured = env.path(key.override)
    if configured is not None:
        if configured.exists():
            return ToolSearch(key, str(configured), f"${key.override.name}")
        # ⚠️ An override that points nowhere is a typo, not a reason to search
        # on: silently falling back to PATH would run a *different* binary than
        # the one asked for. Say so instead.
        return ToolSearch(
            key,
            problem=(
                f"{key.override.name} is set to {configured}, which does not exist"
                + hint
                + f"\n  unset {key.override.name} to search PATH and the usual places"
            ),
            override_is_broken=True,
        )

    for candidate in location.names:
        found = shutil.which(candidate)
        if found:
            return ToolSearch(key, found, "PATH")

    for directory in location.search_paths():
        for candidate in location.names:
            path = directory.expanduser() / candidate
            if path.exists():
                return ToolSearch(key, str(path), str(path.parent))

    tried = ", ".join(location.names)
    return ToolSearch(key, problem=f"{key} not found (looked for: {tried})" + hint)


def find_tool(key: ToolKey) -> str:
    """Locate an external tool, or raise a `DiscError` explaining the search."""
    search = locate(key)
    if search.found:
        return search.path
    raise DiscError(search.problem)


def killed_advice(executable: str) -> str:
    """What to suggest when the OS terminated a tool before it could speak.

    Which repair to name is platform data (`PlatformProfile.signing_remedy`):
    on Apple Silicon an unsigned arm64 binary is `SIGKILL`ed with no output,
    and nowhere else does that happen.
    """
    remedy = platforms.current().signing_remedy
    if not remedy:
        return ""
    return "  the OS may be refusing to run it; an ad-hoc signature repairs that:\n" + (
        f"    {remedy.format(path=executable)}"
    )


def explain_exit(executable: str, returncode: int) -> str:
    """Stand in for a tool's own words when it produced none.

    ⚠️ Without this a killed binary reports as `wit failed:` and then nothing,
    which is the least useful sentence the toolkit can print.
    """
    name = Path(executable).name
    if returncode < 0:
        advice = killed_advice(executable)
        return (
            f"{name} was killed before it could report anything "
            f"(signal {-returncode})." + (f"\n{advice}" if advice else "")
        )
    return f"{name} exited {returncode} without printing anything."


def _run(args: list[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or explain_exit(
            args[0], result.returncode
        )
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

    reason: str = ""
    """Why the fields are empty, when they are.

    ⚠️ `identify` still answers rather than raising -- a caller printing a file
    summary should not abort over a missing tool. But it knew exactly which
    tool was missing and where it looked, and throwing that away left
    `bleck info` asking the user a question it had the answer to (D274).
    """

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
    """Read disc header fields. Returns an empty DiscInfo, and why, if unreadable."""
    if is_rvz(image):
        return _identify_rvz(image)
    search = locate(ToolKey.WIT)
    if not search.found:
        return DiscInfo(reason=search.problem)
    wit = search.path
    result = subprocess.run(
        [wit, "DUMP", str(image)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return DiscInfo(reason=_tool_said(wit, result))

    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        attr = _WIT_FIELDS.get(key.strip())
        if attr and attr not in found:
            found[attr] = value.strip()
    return DiscInfo(**found)


def _tool_said(executable: str, result: subprocess.CompletedProcess[str]) -> str:
    """A failed run's own words, or a stand-in when it had none."""
    return (result.stderr or result.stdout).strip() or explain_exit(
        executable, result.returncode
    )


def _identify_rvz(image: Path) -> DiscInfo:
    """RVZ headers come from dolphin-tool; wit cannot read the format.

    ⚠️ So `wit` is not a candidate here and must not appear in the reason. Half
    a sentence naming a tool that could never have helped is what made the old
    "is wit or dolphin-tool installed?" message useless.
    """
    search = locate(ToolKey.DOLPHIN_TOOL)
    if not search.found:
        return DiscInfo(reason=search.problem)
    tool = search.path
    result = subprocess.run(
        [tool, "header", "-i", str(image)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return DiscInfo(reason=_tool_said(tool, result))

    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        attr = _DOLPHIN_FIELDS.get(key.strip())
        if attr and attr not in found:
            found[attr] = value.strip()
    return DiscInfo(**found)
