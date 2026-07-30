"""Discovering mods on disk.

A mod is a directory under the mods root containing `mod.json`. The registry is
the only thing that knows where mods live, so resolution stays off the
filesystem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bleck import platforms
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.mods import levels
from bleck.mods.manifest.code import tags as codetags

from .manifest import (
    MANIFEST_NAME,
    OVERLAY_DIR,
    PLACEMENT_KINDS,
    Manifest,
    read,
)


class RegistryError(BleckError):
    pass


@dataclass(frozen=True)
class Mod:
    manifest: Manifest
    root: Path

    @property
    def name(self) -> str:
        return self.manifest.name

    def tables_of(self, kind):
        """Every table of one kind, from `tables` **and** `levels` (D145).

        ⚠️ **Call this, not `manifest.tables_of`.** The manifest holds only what
        was written literally; a level directory's tables exist on disk and are
        discovered here, where the root is known. A caller that asks the
        manifest sees a level-organised mod as empty.
        """
        return levels.tables_for(self, kind)

    @property
    def code(self):
        """The `code` block, with any tags in the mod's own sources folded in.

        ⚠️ **Call this, not `manifest.code`.** The manifest holds only what
        `mod.json` said literally; a `BLECK_HOOK` or `#[map(...)]` lives in a
        source file and is discovered here, where the root is known. A caller
        that asks the manifest sees a tag-declared hook as absent -- the same
        shape as `tables_of` above, and as D126's four repeats.
        """
        return codetags.code_of(self)

    @property
    def has_placements(self) -> bool:
        """Whether this mod changes any map's setup file, **levels included**.

        ⚠️ `manifest.has_placements` cannot answer this: a level's tables are on
        disk, not in the manifest, so a level-organised mod looks empty to it.
        `mods_with_placements` gates the entire placement build on this, and a
        mod it skips still reports "chain OK" -- D126's shape, hit for a third
        time when `levels` landed (D145).
        """
        return bool(self.manifest.setup) or any(
            self.tables_of(kind) for kind in PLACEMENT_KINDS
        )

    @property
    def overlay(self) -> Path:
        """The overlay tree. May not exist — a manifest-only mod is legal."""
        return self.root / OVERLAY_DIR

    def overlay_paths(self) -> list[str]:
        """Every path in the overlay, relative and posix-style, files only.

        Archive-standing-in directories are not listed; their members are.
        """
        if not self.overlay.is_dir():
            return []
        profile = platforms.current()
        return sorted(
            entry.relative_to(self.overlay).as_posix()
            for entry in self.overlay.rglob("*")
            if entry.is_file() and not profile.is_ignored(entry.name)
        )


@dataclass(frozen=True)
class Registry:
    """Every mod discoverable under one root."""

    root: Path
    mods: list[Mod]

    broken: dict[str, BleckError] = field(default_factory=dict)
    """Directory name -> the error its manifest raised.

    ⚠️ Kept rather than raised at load, so one bad mod does not break every
    command that enumerates (D141). `require` **re-raises the original**, so
    asking for a broken mod reports exactly what it would have before -- the
    message already names the file -- while asking for anything else is
    unaffected.
    """

    def find(self, name: str) -> Mod | None:
        return next((mod for mod in self.mods if mod.name == name), None)

    def require(self, name: str) -> Mod:
        found = self.find(name)
        if found is not None:
            return found
        if name in self.broken:
            # Re-raised as-is: the original message already names the file, and
            # wrapping it would change the exception type callers catch.
            raise self.broken[name]
        known = ", ".join(sorted(m.name for m in self.mods)) or "none"
        also = (
            f"\n  {len(self.broken)} mod(s) could not be read: "
            f"{', '.join(sorted(self.broken))}"
            if self.broken
            else ""
        )
        raise RegistryError(
            f"no mod named {name!r} in {self.root} (found: {known}){also}"
        )


def mods_root() -> Path:
    return Path(env.text(env.MODS_DIR))


def base_root() -> Path:
    return Path(env.text(env.BASE_DIR))


def build_root() -> Path:
    return Path(env.text(env.BUILD_DIR))


def load(root: Path | None = None) -> Registry:
    """Discover every mod under `root`, defaulting to the configured mods dir.

    ⚠️ **One unreadable mod must not break every command.** Loading the registry
    reads *every* manifest, so a single bad one used to fail `bleck mod list`,
    `mod check <other>`, and anything else that enumerates -- with a message
    naming a mod the user had not asked about. That surfaced the moment door
    selectors started being bounds-checked (D141): two committed mods carried a
    dead `door:he1_01:9`, and every command in the repo stopped working.

    A broken mod is skipped and remembered. `require` still raises for one asked
    for by name, with the reason it could not be read -- the error arrives when
    it is relevant instead of on every unrelated command.
    """
    where = root if root is not None else mods_root()
    if not where.is_dir():
        return Registry(where, [])

    found: list[Mod] = []
    broken: dict[str, BleckError] = {}
    for candidate in sorted(where.iterdir()):
        if not candidate.is_dir() or not (candidate / MANIFEST_NAME).exists():
            continue
        try:
            found.append(Mod(read(candidate), candidate))
        except BleckError as exc:
            broken[candidate.name] = exc
    return Registry(where, found, broken)
