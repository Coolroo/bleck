"""Packing a mod into a shareable `.bleck` archive.

A mod is shared as **what its author wrote**, never as game bytes. Everything
`bleck` can regenerate from those declarations is left out and rebuilt against
the recipient's own disc, so a `.bleck` carries no Nintendo content and can be
unzipped and read to confirm it.

Three kinds of file, decided by path:

- **source** — `mod.json`, tables, C, scripts. Always packed.
- **generated** — the compiled `mod.rel`, and the setup files written for maps
  the mod declares placements for. Never packed; regenerated on build.
- **asset** — anything else under `overlay/`. An overlay file replaces a file on
  the disc, but ⛔ **that says nothing about where its bytes came from**: a
  replacement texture may be entirely the author's own work, or a vendored one
  they edited. `bleck` cannot tell, and used to assert the worse of the two.

⚠️ So the author says, once, with `"assets"` in `mod.json` (D186). `original`
packs like any other source; `derived` takes an explicit flag; unstated asks.

⚠️ An asset is **never** refused outright. Refusing would only move the problem
to a hand-made zip, where nobody is told anything at all.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from bleck.mods.errors import ManifestError
from bleck.mods.manifest import OVERLAY_DIR, REL_DISC_PATH, AssetOrigin

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
    """Overlay files that replace disc content. Whether they *are* game-derived
    is `origin`'s business, not this list's."""

    origin: AssetOrigin = AssetOrigin.UNSTATED
    """What the manifest says about where `assets` came from."""

    @property
    def needs_consent(self) -> bool:
        """⛔ Not "does this mod have overlay files".

        An overlay file replaces something on the disc, but a replacement can
        be original artwork carrying no game data at all. `bleck` cannot tell
        those apart, so it asks only when nobody has said (D186).
        """
        return bool(self.assets) and self.origin is AssetOrigin.UNSTATED

    def describe_assets(self) -> str:
        """The question, naming every file rather than summarising.

        ⚠️ **A question, not an accusation.** This used to state that the files
        *are* derived from the game and that packing them redistributes
        Nintendo's work. Both are things the tool cannot know, and both are
        false for a texture someone drew themselves.
        """
        lines = [
            f"{len(self.assets)} file(s) in {self.mod} replace content on the disc:",
        ]
        lines += [f"    {path}" for path in self.assets]
        lines += [
            "",
            "  If you made them, they are yours to share and this is a formality.",
            "  If any started as game data -- vendored and edited, say -- then packing",
            "  them redistributes Nintendo's work in modified form.",
            "",
            "  Only you know which. Declare it once in mod.json to stop being asked:",
            '      "assets": "original"   your own work',
            '      "assets": "derived"    started as game data',
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

    return PackPlan(
        mod=mod.name,
        sources=sources,
        generated=generated,
        assets=assets,
        origin=mod.manifest.assets,
    )


@dataclass(frozen=True)
class PackResult:
    """Where the archive went, and what it holds."""

    path: Path
    packed: list[str]
    skipped: list[str]
    assets_included: bool


def packs_assets(plan_: PackPlan, include_assets: bool) -> bool:
    """Whether this archive carries the mod's overlay files.

    ⚠️ A mod whose author has said the files are **their own work** packs them
    like any other source, because that is what they are. Only `derived` and
    `unstated` need the flag: one because it really is game data, the other
    because nobody has said (D186).
    """
    if plan_.origin is AssetOrigin.ORIGINAL:
        return True
    return include_assets


def write(mod, plan_: PackPlan, out: Path, include_assets: bool = False) -> PackResult:
    """Write the archive. Assets are packed when the mod's origin allows it."""
    with_assets = packs_assets(plan_, include_assets)
    packed = sorted(plan_.sources + (plan_.assets if with_assets else []))

    out.parent.mkdir(parents=True, exist_ok=True)
    toc = {
        "schema": TOC_SCHEMA,
        "mod": mod.name,
        "version": str(mod.manifest.version),
        "base": mod.manifest.base,
        "assets_included": bool(with_assets and plan_.assets),
        # ⚠️ Travels with the archive: the recipient needs the *author's*
        # statement, not this tool's guess about their files (D186).
        "assets_origin": str(plan_.origin),
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
        skipped=plan_.generated + ([] if with_assets else plan_.assets),
        assets_included=bool(toc["assets_included"]),
    )


@dataclass(frozen=True)
class Installed:
    """A `.bleck` unpacked into a mods directory."""

    name: str
    root: Path
    files: list[str]
    assets_included: bool
    assets_origin: AssetOrigin = AssetOrigin.UNSTATED
    """What the author said about the overlay files they packed."""


def _origin_from_toc(toc: dict) -> AssetOrigin:
    """An archive written before `assets_origin` existed simply says nothing."""
    try:
        return AssetOrigin(str(toc.get("assets_origin", "")))
    except ValueError:
        return AssetOrigin.UNSTATED


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
        assets_origin=_origin_from_toc(toc),
    )
