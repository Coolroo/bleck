"""Materialising a resolved chain into a staged build.

Writing that out is `outputs.py`'s job. The base is opened read-only throughout,
and staging hardlinks unchanged files rather than copying 400 MB per iteration,
so a build writes only what differs.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from bleck import platforms
from bleck.common.errors import BleckError
from bleck.common.fsio import remove_tree
from bleck.formats import lz77, u8
from bleck.mods.build import generated
from bleck.mods.build.conflicts import Conflict, detect, effective_edits, merge_three_way
from bleck.mods.build.edits import PlacementBuild, apply_chain
from bleck.mods.build.overlay import Plan, build_plan
from bleck.mods.code import CodeBuild, CodeOverride, CodeResult, build_chain
from bleck.mods.resolver import Chain, check_bases


class BuildError(BleckError):
    pass


@dataclass(frozen=True)
class BuildContext:
    """Everything a build step needs, threaded as one value."""

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

    swept: list[str] = field(default_factory=list)
    """Overlay files the previous build wrote that this one no longer produces."""

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
        # Never stage OS clutter (.DS_Store, ._ sidecars) onto the disc.
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


def _detach(path: Path) -> None:
    """Remove a staged file before rewriting it, so the base is never modified.

    Staged files are hardlinks to the base; writing through one edits the base.
    ⚠️ Unlinks unconditionally rather than checking `st_nlink > 1` — Windows
    does not report link counts reliably.
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
    # ⚠️ Matched on a normalised key, not the stored path: `lyt/*.bin.uk` holds
    # `arc/anim/...` while `map/*.bin` holds `./dvd/...`. Matching literally
    # adds a duplicate member instead of replacing the original.
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
    # byte-identical (D17), and a replaced one keeps the archive's spelling.
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


def compile_code(chain: Chain, override: CodeOverride | None = None) -> CodeResult:
    """Compile the chain's code mods into their overlays.

    ⚠️ Must run before `prepare`: the plan comes from walking `overlay/`, so a
    `mod.rel` generated later would not be in the build.
    """
    return build_chain(chain, override=override)


def produce(
    chain: Chain, base: Path, override: CodeOverride | None, report: BuildReport
) -> None:
    """Regenerate every mod's overlay content, taking back the last build's.

    ⚠️ Shared by `check` and `build` on purpose. They used to repeat these
    steps, and a sweep added to one and not the other would mean a mod checked
    clean and shipped stale — the two answering differently is the failure this
    is meant to end.

    ⛔ The sweep runs **before** anything writes. `prepare` builds the disc plan
    by walking `overlay/`, so a file removed after that point is already in it.
    """
    removed: set[str] = set()
    for mod in chain.mods:
        swept = generated.sweep(mod)
        removed.update(f"{mod.name}/{path}" for path in swept.removed)
        report.warnings += swept.notes

    compiled = compile_code(chain, override)
    report.code_builds = compiled.builds
    report.warnings += compiled.notes
    report.warnings += [note for b in report.code_builds for note in b.warnings]
    report.placement_builds = apply_chain(chain, base)
    report.warnings += [note for b in report.placement_builds for note in b.warnings]

    # Recorded from what the builds say they wrote, never re-derived: a second
    # implementation of "where does this land" would drift from the first.
    written: dict[str, list[Path]] = {mod.name: [] for mod in chain.mods}
    for built in report.code_builds:
        for name in built.mod.split(", "):
            written.setdefault(name, []).append(built.output)
    for placed in report.placement_builds:
        written.setdefault(placed.mod, []).extend([placed.output, placed.also_wrote])
    for mod in chain.mods:
        generated.record(mod, written.get(mod.name, []))
        removed -= {f"{mod.name}/{path}" for path in generated.read(mod)}

    # ⚠️ Only what did *not* come back. Nearly every sweep removes `mod.rel`
    # and rewrites it a moment later; calling that "cleared" would bury the
    # line that matters -- a placement whose declaration is gone (D156).
    report.swept = sorted(removed)


def check(
    chain: Chain,
    base: Path,
    allow_binary: bool,
    override: CodeOverride | None = None,
) -> BuildReport:
    """Resolve and detect conflicts without writing a disc.

    Scripts are still compiled: a mod whose code does not build fails checking.
    """
    report = BuildReport(staged=Path())
    produce(chain, base, override, report)
    plan = prepare(chain, base)
    report.conflicts = detect(chain, plan, base, allow_binary)
    report.warnings += _duplicate_warnings(base, plan, report.placement_builds)
    return report


def build(
    chain: Chain,
    base: Path,
    staged: Path,
    allow_binary: bool,
    override: CodeOverride | None = None,
) -> BuildReport:
    """Stage the base, apply the chain, and report what happened."""
    report = BuildReport(staged=staged)
    produce(chain, base, override, report)
    plan = prepare(chain, base)
    report.conflicts = detect(chain, plan, base, allow_binary)
    report.warnings += _duplicate_warnings(base, plan, report.placement_builds)
    if report.conflicts:
        return report

    stage(base, staged)
    apply_plan(BuildContext(base, staged, plan, chain, allow_binary), report)
    return report


def _duplicate_warnings(
    base: Path, plan: Plan, placements: list[PlacementBuild] | None = None
) -> list[str]:
    """Warn when a mod edits a setup file that exists in two places.

    Setup files ship both standalone in `setup/` and embedded in some map
    archives, byte-identically (D13). ✅ The game reads the **standalone**
    `files/setup/<map>.dat` (D62). `bleck` writes both; this warns when a
    hand-written overlay touches only one.

    ⛔ **It used to warn about `bleck`'s own output too.** The plan cannot tell
    a hand-written overlay from a generated one -- both are just files by the
    time it exists -- so a mod that declared its change under `setup` was told
    to go and declare it under `setup`. Advice that fires when it has already
    been followed is worse than silence: it teaches the reader to skip the
    warning that matters. `apply_chain` writes *both* copies for a declared
    map, so those are exactly the ones with nothing to warn about (D122).
    """
    generated = {build.map_name for build in placements or []}
    warnings: list[str] = []
    for file_plan in plan.files:
        path = file_plan.disc_path
        for member in file_plan.members:
            if "/setup/" in member and Path(member).stem not in generated:
                twin = f"setup/{Path(member).name}"
                if (base / twin).exists():
                    warnings.append(
                        f"{path}/{member} also exists as {twin}, which is the "
                        "copy the game actually reads (D62). Editing only this "
                        "one does nothing"
                    )
        if "/setup/" in f"/{path}" and Path(path).stem not in generated:
            warnings.append(
                f"{path} is the copy the game reads (D62); its twin inside the "
                "map archive is ignored. Edit both to keep them consistent, or "
                "declare the change under 'setup' in mod.json"
            )
    return warnings
