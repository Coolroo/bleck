"""Turning a chain of mods into a concrete set of edits against the base.

An overlay path may point *into* an archive: the disc file is the longest
prefix that exists as a file in the base, and the remainder names a member
inside it, so a mod ships one texture rather than a repacked archive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError


class OverlayError(BleckError):
    pass


@dataclass(frozen=True)
class TargetPath:
    """Where an overlay entry lands in the base."""

    disc_path: str
    """Path of the real file on the disc."""

    member: str = ""
    """Path inside that file's archive, empty for whole-file replacement."""

    @property
    def is_member(self) -> bool:
        return bool(self.member)

    def __str__(self) -> str:
        return f"{self.disc_path}/{self.member}" if self.member else self.disc_path


@dataclass(frozen=True)
class Edit:
    """One mod's change to one target."""

    target: TargetPath
    source: Path
    """File in the mod's overlay providing the new contents."""

    mod_name: str


@dataclass(frozen=True)
class Removal:
    """A base file a mod asks to delete."""

    disc_path: str
    mod_name: str


@dataclass
class FilePlan:
    """Every edit landing on one disc file, in chain order."""

    disc_path: str
    whole_file: list[Edit] = field(default_factory=list)
    members: dict[str, list[Edit]] = field(default_factory=dict)

    @property
    def is_archive_merge(self) -> bool:
        return bool(self.members)

    def contributors(self) -> list[str]:
        """Mod names touching this file, in chain order, deduplicated."""
        names: list[str] = []
        for edit in [*self.whole_file, *(e for v in self.members.values() for e in v)]:
            if edit.mod_name not in names:
                names.append(edit.mod_name)
        return names


@dataclass
class Plan:
    """The full set of changes a chain makes to the base."""

    files: list[FilePlan] = field(default_factory=list)
    removals: list[Removal] = field(default_factory=list)

    def for_path(self, disc_path: str) -> FilePlan | None:
        return next((f for f in self.files if f.disc_path == disc_path), None)

    def touched_paths(self) -> list[str]:
        return [f.disc_path for f in self.files]


# The data partition sits under `files/` in a wit extract; overlays mirror the
# extract root, but a bare path is accepted when it resolves under this prefix.
DATA_PREFIX = "files"


def normalize_disc_path(base: Path, path: str) -> str:
    """Accept either a full extract-relative path or a bare data-partition one."""
    cleaned = path.strip("/")
    if (base / cleaned).exists():
        return cleaned
    prefixed = f"{DATA_PREFIX}/{cleaned}"
    if (base / prefixed).exists():
        return prefixed
    # Neither exists; prefer the prefixed form if any ancestor of it does,
    # so archive-member paths still resolve.
    probe = Path(prefixed)
    while probe.parent != probe:
        probe = probe.parent
        if (base / probe).is_file():
            return prefixed
    return cleaned


def resolve_target(base: Path, overlay_path: str) -> TargetPath:
    """Split an overlay path into a disc file plus an optional archive member.

    The disc file is the longest prefix that exists as a file in the base. If no
    prefix is a file, the whole path is a new file being added.
    """
    parts = overlay_path.split("/")
    for cut in range(len(parts), 0, -1):
        candidate = "/".join(parts[:cut])
        if (base / candidate).is_file():
            return TargetPath(candidate, "/".join(parts[cut:]))
    return TargetPath(overlay_path)


def build_plan(base: Path, chain_mods: list) -> Plan:
    """Collect every edit from every mod, in chain order.

    Order matters: where no merge is attempted, the last edit wins.
    """
    plan = Plan()
    by_path: dict[str, FilePlan] = {}

    for mod in chain_mods:
        for relative in mod.overlay_paths():
            target = resolve_target(base, relative)
            file_plan = by_path.get(target.disc_path)
            if file_plan is None:
                file_plan = FilePlan(target.disc_path)
                by_path[target.disc_path] = file_plan
                plan.files.append(file_plan)

            edit = Edit(target, mod.overlay / relative, mod.name)
            if target.is_member:
                file_plan.members.setdefault(target.member, []).append(edit)
            else:
                file_plan.whole_file.append(edit)

        for path in mod.manifest.remove:
            plan.removals.append(Removal(path, mod.name))

    return plan
