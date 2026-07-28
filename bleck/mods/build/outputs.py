"""Output kinds — how a staged build leaves `bleck`.

One table, one entry per delivery mechanism. Adding a way to ship a mod means
adding an `OutputKind` here, not a branch in the build command.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import disc, riivolution


@dataclass(frozen=True)
class OutputRequest:
    """Everything an output kind needs, threaded as one value."""

    name: str
    base: Path
    staged: Path
    out: Path
    keep_iso: bool = False

    base_image: Path | None = None
    """A retail disc image for a patch to sit on, instead of the extracted base."""


@dataclass(frozen=True)
class OutputResult:
    """What an output kind produced."""

    path: Path
    summary: str

    bootable: Path | None = None
    """What `--launch` should hand Dolphin, if anything."""

    warnings: list[str] = field(default_factory=list)


Writer = Callable[[OutputRequest], OutputResult]


@dataclass(frozen=True)
class OutputKind:
    """One delivery mechanism, as data."""

    name: str
    suffix: str
    """Extension of the artifact, or "" for a directory and for `none`."""

    summary: str
    """One line, shown in `--help`."""

    write: Writer

    produces_artifact: bool = True
    """False for `none`, which stages and stops."""

    embeds_loader: bool = True
    """Whether the Gecko loader should be put in the DOL before writing."""

    @property
    def is_image(self) -> bool:
        return self.suffix != ""

    def default_out(self, build_root: Path, mod: str) -> Path:
        """Where this kind writes when the user names no destination."""
        if self.suffix:
            return build_root / f"{mod}{self.suffix}"
        return build_root / f"{mod}-{self.name}"


def _write_image(request: OutputRequest, image_format: disc.ImageFormat) -> OutputResult:
    disc.build_image(request.staged, request.out, image_format, keep_iso=request.keep_iso)
    size = request.out.stat().st_size
    return OutputResult(
        path=request.out,
        summary=f"built {request.out}  ({size:,} bytes, {image_format.value})",
        bootable=request.out,
    )


def _write_iso(request: OutputRequest) -> OutputResult:
    return _write_image(request, disc.ImageFormat.ISO)


def _write_wbfs(request: OutputRequest) -> OutputResult:
    return _write_image(request, disc.ImageFormat.WBFS)


def _write_rvz(request: OutputRequest) -> OutputResult:
    return _write_image(request, disc.ImageFormat.RVZ)


def _write_riivolution(request: OutputRequest) -> OutputResult:
    patch = riivolution.plan(request.name, request.base, request.staged)
    emitted = riivolution.emit(patch, request.out, request.base_image or request.base)
    return OutputResult(
        path=emitted.root,
        summary=emitted.describe(),
        bootable=emitted.descriptor,
        warnings=patch.unsupported,
    )


def _write_nothing(request: OutputRequest) -> OutputResult:
    return OutputResult(path=request.staged, summary="")


ISO = OutputKind(
    name="iso",
    suffix=".iso",
    summary="plain disc image; the format wit writes natively",
    write=_write_iso,
)

WBFS = OutputKind(
    name="wbfs",
    suffix=".wbfs",
    summary="~424 MB disc image every Dolphin build reads; best for sharing",
    write=_write_wbfs,
)

RVZ = OutputKind(
    name="rvz",
    suffix=".rvz",
    summary="~249 MB disc image, but needs Dolphin 5.0-12188 (2020) or newer",
    write=_write_rvz,
)

RIIVOLUTION = OutputKind(
    name="riivolution",
    suffix="",
    summary="patch XML plus only the changed files; runs on a real Wii from SD",
    write=_write_riivolution,
)

NONE = OutputKind(
    name="none",
    suffix="",
    summary="stage only, write nothing",
    write=_write_nothing,
    produces_artifact=False,
    embeds_loader=False,
)

#: Every output kind, in the order `--help` lists them.
KINDS: list[OutputKind] = [ISO, WBFS, RVZ, RIIVOLUTION, NONE]


def names() -> list[str]:
    return [kind.name for kind in KINDS]


def find(name: str) -> OutputKind:
    """The kind called `name`. Raises `KeyError` for an unknown one."""
    for kind in KINDS:
        if kind.name == name:
            return kind
    raise KeyError(name)


def for_path(path: Path) -> OutputKind:
    """Infer the kind from a destination's extension, defaulting to ISO.

    Riivolution writes a directory, so it has no extension to infer from and
    has to be asked for by name.
    """
    suffix = path.suffix.lower()
    return next((kind for kind in KINDS if kind.suffix and kind.suffix == suffix), ISO)


def describe_choices() -> str:
    """The `--output` help text, built from the table so it cannot drift."""
    return "; ".join(f"{kind.name}: {kind.summary}" for kind in KINDS)
