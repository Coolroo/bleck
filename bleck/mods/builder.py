"""Materialising a resolved chain into a bootable disc.

The base is opened read-only throughout. Staging hardlinks unchanged files
rather than copying, so a build writes only what actually differs — copying
400 MB per iteration would make the loop unusable on modest hardware.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

from bleck import platforms
from bleck.backends import disc
from bleck.common.errors import BleckError
from bleck.formats import lz77, u8

from .code import CodeBuild, build_chain
from .conflicts import Conflict, detect, effective_edits, merge_three_way
from .edits import PlacementBuild, apply_chain
from .overlay import Plan, build_plan
from .resolver import Chain, check_bases


class BuildError(BleckError):
    pass


@dataclass(frozen=True)
class BuildContext:
    """Everything a build step needs, so state is threaded as one value.

    These arguments always travel together; passing them individually made
    every helper take six positionals.
    """

    base: Path
    staged: Path
    plan: Plan
    chain: Chain
    allow_binary: bool


@dataclass
class BuildReport:
    """What a build did, for reporting and for tests to assert on."""

    staged: Path
    files_written: int = 0
    archives_merged: int = 0
    files_removed: int = 0
    warnings: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    code_builds: list[CodeBuild] = field(default_factory=list)
    placement_builds: list[PlacementBuild] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.conflicts


def stage(base: Path, dest: Path) -> int:
    """Mirror the base into `dest`, hardlinking where possible.

    Falls back to copying across filesystem boundaries. Returns the number of
    entries linked or copied.
    """
    if not base.is_dir():
        raise BuildError(f"base not found: {base}")
    if dest.exists():
        remove_tree(dest)

    profile = platforms.current()
    count = 0
    for source in base.rglob("*"):
        # Never stage OS clutter — macOS scatters .DS_Store and ._ sidecars
        # through any directory a user browses, and it must not reach the disc.
        if profile.is_ignored(source.name):
            continue
        target = dest / source.relative_to(base)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        count += 1
    return count


def _on_rmtree_error(func, path: str, _exc) -> None:
    """Retry a failed removal after clearing the read-only bit.

    Windows refuses to delete read-only files, which staged copies inherit from
    a read-only base.
    """
    Path(path).chmod(stat.S_IWRITE)
    func(path)


def remove_tree(path: Path) -> None:
    if platforms.current().strip_readonly_on_delete:
        shutil.rmtree(path, onexc=_on_rmtree_error)
    else:
        shutil.rmtree(path)


def _detach(path: Path) -> None:
    """Remove a staged file before rewriting it, so the base is never modified.

    Staged files are hardlinks to the base, and writing through one would edit
    the base in place — the exact failure this design exists to prevent.

    This unlinks unconditionally rather than checking `st_nlink > 1`: Windows
    does not reliably report link counts, so a check that silently returns 1
    there would write straight through the link. Unlinking always is cheap and
    cannot get this wrong. Callers either rewrite the file or fall back to
    reading the base, both of which are correct once it is gone.
    """
    path.unlink(missing_ok=True)


def apply_plan(context: BuildContext, report: BuildReport) -> None:
    base, staged = context.base, context.staged
    for file_plan in context.plan.files:
        destination = staged / file_plan.disc_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        _detach(destination)

        whole = effective_edits(context.chain, file_plan.whole_file)
        if whole:
            outcome = merge_three_way(
                file_plan.disc_path,
                (base / file_plan.disc_path).read_bytes()
                if (base / file_plan.disc_path).exists()
                else b"",
                whole,
                context.allow_binary,
            )
            if outcome.conflicts:
                report.conflicts += outcome.conflicts
                continue
            destination.write_bytes(outcome.data)
            report.files_written += 1

        if file_plan.members:
            _merge_archive(context, destination, file_plan, report)
            report.archives_merged += 1

    for removal in context.plan.removals:
        target = staged / removal.disc_path
        if target.exists():
            target.unlink()
            report.files_removed += 1
        else:
            report.warnings.append(
                f"{removal.mod_name} asks to remove {removal.disc_path}, "
                "which is not in the base"
            )


def _merge_archive(
    context: BuildContext, destination: Path, file_plan, report: BuildReport
) -> None:
    """Replace named members inside an archive, preserving everything else."""
    source = destination if destination.exists() else context.base / file_plan.disc_path
    raw = source.read_bytes()

    compressed = lz77.is_lz77(raw)
    payload = lz77.decompress(raw) if compressed else raw
    if not u8.is_u8(payload):
        raise BuildError(
            f"{file_plan.disc_path} is not an archive, but a mod addresses "
            f"members inside it ({', '.join(sorted(file_plan.members))})"
        )

    items = u8.read_all(payload)
    packed = _merge_members(items, file_plan, context, report)
    if packed is not None:
        destination.write_bytes(lz77.compress(packed) if compressed else packed)


def _merge_members(items, file_plan, context, report) -> bytes | None:
    """Apply every member edit and repack. None when the merge conflicted."""
    # ⚠️ Matched on a normalised key, not the stored path. SPM's two archive
    # families disagree: `lyt/*.bin.uk` stores `arc/anim/...` while `map/*.bin`
    # stores `./dvd/...`. An overlay path cannot express a `./` component, so
    # matching literally meant a map-archive member was never recognised -- it
    # was silently *added* alongside the original instead of replacing it,
    # producing an archive with two members of the same name.
    known = {u8.member_key(item.path): item.path for item in items}

    replacements: dict[str, bytes] = {}
    for member, raw_edits in file_plan.members.items():
        edits = effective_edits(context.chain, raw_edits)
        if not edits:
            continue
        key = u8.member_key(member)
        if key not in known:
            report.warnings.append(
                f"{file_plan.disc_path}: no member {member!r} "
                f"(added as a new file by {edits[-1].mod_name})"
            )
        ancestor = next(
            (i.data or b"" for i in items if u8.member_key(i.path) == key),
            b"",
        )
        outcome = merge_three_way(
            f"{file_plan.disc_path}/{member}", ancestor, edits, context.allow_binary
        )
        if outcome.conflicts:
            report.conflicts += outcome.conflicts
            continue
        # Keyed so a `./`-prefixed member replaces the right node below.
        replacements[key] = outcome.data

    if report.conflicts:
        return None

    # Preserve node order *and the stored path*: unchanged members stay
    # byte-identical (D17), and a replaced one keeps the archive's own spelling
    # rather than the overlay's.
    merged = [
        u8.U8Item(item.path, replacements.get(u8.member_key(item.path), item.data))
        for item in items
    ]
    merged += [
        u8.U8Item(name, data) for name, data in replacements.items() if name not in known
    ]

    return u8.write(merged)


def prepare(chain: Chain, base: Path) -> Plan:
    """Validate the chain against the base and return its plan."""
    complaints = check_bases(chain, base.name)
    if complaints:
        raise BuildError(
            "mods target a different base build:\n  " + "\n  ".join(complaints)
        )
    return build_plan(base, chain.mods)


def compile_code(chain: Chain) -> list[CodeBuild]:
    """Compile the chain's code mods into their overlays.

    Must happen before `prepare`: the overlay plan comes from walking each mod's
    `overlay/` directory, so a generated `mod.rel` that does not exist yet would
    simply not be part of the build.
    """
    return build_chain(chain)


def check(chain: Chain, base: Path, allow_binary: bool) -> BuildReport:
    """Resolve and detect conflicts without writing anything.

    Scripts are still compiled: a mod whose code does not build is not a mod
    that passes checking, and finding that out here is the whole point.
    """
    report = BuildReport(staged=Path())
    report.code_builds = compile_code(chain)
    report.placement_builds = apply_chain(chain, base)
    plan = prepare(chain, base)
    report.conflicts = detect(chain, plan, base, allow_binary)
    report.warnings += _duplicate_warnings(base, plan)
    return report


def build(chain: Chain, base: Path, staged: Path, allow_binary: bool) -> BuildReport:
    """Stage the base, apply the chain, and report what happened."""
    report = BuildReport(staged=staged)
    report.code_builds = compile_code(chain)
    report.placement_builds = apply_chain(chain, base)
    plan = prepare(chain, base)
    report.conflicts = detect(chain, plan, base, allow_binary)
    report.warnings += _duplicate_warnings(base, plan)
    if report.conflicts:
        return report

    stage(base, staged)
    apply_plan(BuildContext(base, staged, plan, chain, allow_binary), report)
    return report


def emit(
    staged: Path,
    out: Path,
    image_format: disc.ImageFormat = disc.ImageFormat.ISO,
    keep_iso: bool = False,
) -> None:
    disc.build_image(staged, out, image_format, keep_iso=keep_iso)


def _duplicate_warnings(base: Path, plan: Plan) -> list[str]:
    """Warn when a mod edits a setup file that exists in two places.

    Setup files ship both standalone in `setup/` and embedded inside some map
    archives, byte-identically (see docs/decision-log.md D13).

    ✅ D62 settled it: the game reads the **standalone** `files/setup/<map>.dat`.
    A disc with a different enemy in each copy spawned the standalone one's.

    `bleck` writes both when it generates a setup file -- hygiene rather than a
    hedge, since a stale embedded copy would mislead anyone inspecting the
    archive -- and warns when a hand-written overlay touches only one.
    """
    warnings: list[str] = []
    for file_plan in plan.files:
        path = file_plan.disc_path
        for member in file_plan.members:
            if "/setup/" in member:
                twin = f"setup/{Path(member).name}"
                if (base / twin).exists():
                    warnings.append(
                        f"{path}/{member} also exists as {twin}, which is the "
                        "copy the game actually reads (D62). Editing only this "
                        "one does nothing"
                    )
        if "/setup/" in f"/{path}":
            warnings.append(
                f"{path} is the copy the game reads (D62); its twin inside the "
                "map archive is ignored. Edit both to keep them consistent, or "
                "declare the change under 'setup' in mod.json"
            )
    return warnings
