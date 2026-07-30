"""Packing a mod into a shareable `.bleck` archive.

A mod is shared as **what its author wrote**, never as game bytes. Everything
`bleck` can regenerate from those declarations is left out and rebuilt against
the recipient's own disc, so a `.bleck` carries no Nintendo content and can be
unzipped and read to confirm it.

Three kinds of file, decided by path:

- **source** — `mod.json`, tables, C, scripts. Always packed.
- **generated** — the compiled `mod.rel`, and the setup files written for maps
  the mod declares placements for. Never packed; regenerated on build.
- **asset** — anything else under `overlay/`. An overlay file *replaces a file
  on the disc*, so it is game-derived by construction, and packing one means
  redistributing Nintendo's work in modified form.

⚠️ An asset is **not** refused. The caller is told exactly which files and why,
and decides. Refusing would only move the problem to a hand-made zip, where
nobody gets a warning at all.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from bleck.mods.errors import ManifestError
from bleck.mods.manifest import OVERLAY_DIR, REL_DISC_PATH

#: Extension for a shared mod. A zip, so a recipient can open it with anything.
SUFFIX = ".bleck"

#: The table of contents, so a reader knows what the archive is without bleck.
TOC_NAME = "bleck.toc"

#: Bumped when the archive layout changes in a way an older bleck cannot read.
TOC_SCHEMA = 1

#: Where a mod's placement edits land, from `mods.build.edits`. Duplicated as
#: patterns rather than imported to keep this module off the build path.
_GENERATED_SETUP = (
    "files/setup/{map_name}.dat",
    "files/map/{map_name}.bin/dvd/setup/{map_name}.dat",
)


@dataclass(frozen=True)
class PackPlan:
    """What packing this mod would include, exclude, and warn about."""

    mod: str

    sources: list[str] = field(default_factory=list)
    """Author-written files, relative to the mod root. Always packed."""

    generated: list[str] = field(default_factory=list)
    """Rebuilt from declarations, so left out."""

    assets: list[str] = field(default_factory=list)
    """Overlay files that replace disc content. Packing these ships game-derived
    bytes, which is the caller's decision to make."""

    @property
    def needs_consent(self) -> bool:
        return bool(self.assets)

    def describe_assets(self) -> str:
        """The warning text, naming every file rather than summarising."""
        lines = [
            f"{len(self.assets)} file(s) in {self.mod} replace content on the "
            f"disc, so they are derived from the game:",
        ]
        lines += [f"    {path}" for path in self.assets]
        lines += [
            "",
            "  Packing them redistributes Nintendo's work in modified form.",
            "  Everything else in this mod is regenerated from its declarations "
            "against the recipient's own disc, and carries no game data.",
        ]
        return "\n".join(lines)


def _generated_overlay_paths(mod) -> set[str]:
    """Overlay paths this mod's declarations would produce on a build."""
    # ⚠️ Unconditional. `mod.rel` is build output whoever wrote it, and a mod
    # with no `code` block can still have a stale one from an earlier build --
    # calling that a game-derived asset would be wrong and alarming.
    produced: set[str] = {REL_DISC_PATH}

    # ⚠️ Asked of the builder, not re-derived: an *unbound* table keeps its map
    # names in the CSV rows, so reading the manifest alone misses them and
    # calls the mod's own generated setup files game assets.
    from bleck.mods.build import edits  # pylint: disable=import-outside-toplevel

    maps = {placement.map_name for placement in edits.placements_for(mod)}
    for name in maps:
        produced.update(p.format(map_name=name) for p in _GENERATED_SETUP)
    return produced


def plan(mod) -> PackPlan:
    """Classify every file in a mod without reading or writing an archive."""
    sources: list[str] = []
    generated: list[str] = []
    assets: list[str] = []

    produced = _generated_overlay_paths(mod)
    for path in sorted(mod.root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(mod.root).as_posix()
        if not relative.startswith(f"{OVERLAY_DIR}/"):
            sources.append(relative)
            continue
        inside = relative[len(OVERLAY_DIR) + 1 :]
        # ⚠️ Unknown overlay paths count as assets, not as generated. Guessing
        # the safe way round would ship game bytes silently.
        (generated if inside in produced else assets).append(relative)

    return PackPlan(mod=mod.name, sources=sources, generated=generated, assets=assets)


@dataclass(frozen=True)
class PackResult:
    """Where the archive went, and what it holds."""

    path: Path
    packed: list[str]
    skipped: list[str]
    assets_included: bool


def write(mod, plan_: PackPlan, out: Path, include_assets: bool = False) -> PackResult:
    """Write the archive. Assets are packed only when explicitly allowed."""
    if plan_.needs_consent and not include_assets:
        # Not a refusal to *pack* -- a refusal to pack game data unasked.
        packed = list(plan_.sources)
    else:
        packed = sorted(plan_.sources + (plan_.assets if include_assets else []))

    out.parent.mkdir(parents=True, exist_ok=True)
    toc = {
        "schema": TOC_SCHEMA,
        "mod": mod.name,
        "version": str(mod.manifest.version),
        "base": mod.manifest.base,
        "assets_included": bool(include_assets and plan_.assets),
        "files": {},
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in packed:
            data = (mod.root / relative).read_bytes()
            toc["files"][relative] = hashlib.sha256(data).hexdigest()
            archive.writestr(relative, data)
        archive.writestr(TOC_NAME, json.dumps(toc, indent=2) + "\n")

    return PackResult(
        path=out,
        packed=packed,
        skipped=plan_.generated + ([] if include_assets else plan_.assets),
        assets_included=bool(toc["assets_included"]),
    )


@dataclass(frozen=True)
class Installed:
    """A `.bleck` unpacked into a mods directory."""

    name: str
    root: Path
    files: list[str]
    assets_included: bool


def read_toc(source: Path) -> dict:
    """The archive's table of contents, or a clear error."""
    # pylint: disable=container-return  # the toc is JSON, not a record we own
    if not zipfile.is_zipfile(source):
        raise ManifestError(
            f"{source} is not a {SUFFIX} archive (it is not even a zip).\n"
            f"  A {SUFFIX} file is a zip of a mod's source, written by "
            f"`bleck mod pack`."
        )
    with zipfile.ZipFile(source) as archive:
        if TOC_NAME not in archive.namelist():
            raise ManifestError(
                f"{source} has no {TOC_NAME}, so it was not written by bleck."
            )
        toc = json.loads(archive.read(TOC_NAME))
    if toc.get("schema") != TOC_SCHEMA:
        raise ManifestError(
            f"{source} declares schema {toc.get('schema')!r}; this bleck reads "
            f"{TOC_SCHEMA}."
        )
    return toc


def install(source: Path, mods_dir: Path, force: bool = False) -> Installed:
    """Unpack an archive into `mods_dir`, verifying every file's hash."""
    toc = read_toc(source)
    name = str(toc["mod"])
    root = mods_dir / name
    if root.exists() and not force:
        raise ManifestError(f"{root} already exists.\n  Pass --force to replace it.")

    written: list[str] = []
    with zipfile.ZipFile(source) as archive:
        for relative, digest in toc.get("files", {}).items():
            data = archive.read(relative)
            actual = hashlib.sha256(data).hexdigest()
            if actual != digest:
                raise ManifestError(
                    f"{source}: {relative} does not match the hash in "
                    f"{TOC_NAME}; the archive is damaged or was edited."
                )
            # ⚠️ Rejected rather than sanitised: a path escaping the mod root is
            # not a mistake worth guessing the intent of.
            target = (root / relative).resolve()
            if not str(target).startswith(str(root.resolve())):
                raise ManifestError(f"{source}: {relative} escapes the mod root")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written.append(relative)

    return Installed(
        name=name,
        root=root,
        files=sorted(written),
        assets_included=bool(toc.get("assets_included")),
    )
