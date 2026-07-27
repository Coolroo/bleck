"""Discovering mods on disk.

A mod is a directory under the mods root containing `mod.json`. The registry is
the only thing that knows where mods live, so dependency resolution never
touches the filesystem itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck import platforms
from bleck.common import env
from bleck.common.errors import BleckError

from .manifest import MANIFEST_NAME, OVERLAY_DIR, Manifest, read


class RegistryError(BleckError):
    pass


@dataclass(frozen=True)
class Mod:
    """A mod found on disk."""

    manifest: Manifest
    root: Path

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def overlay(self) -> Path:
        """The overlay tree. May not exist — a manifest-only mod is legal."""
        return self.root / OVERLAY_DIR

    def overlay_paths(self) -> list[str]:
        """Every path in the overlay, relative and posix-style, files only.

        Directories that stand in for archives are *not* listed as directories;
        their members appear individually.
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

    def find(self, name: str) -> Mod | None:
        return next((mod for mod in self.mods if mod.name == name), None)

    def require(self, name: str) -> Mod:
        found = self.find(name)
        if found is None:
            known = ", ".join(sorted(m.name for m in self.mods)) or "none"
            raise RegistryError(f"no mod named {name!r} in {self.root} (found: {known})")
        return found


def mods_root() -> Path:
    return Path(env.text(env.MODS_DIR))


def base_root() -> Path:
    return Path(env.text(env.BASE_DIR))


def build_root() -> Path:
    return Path(env.text(env.BUILD_DIR))


def load(root: Path | None = None) -> Registry:
    """Discover every mod under `root`, defaulting to the configured mods dir."""
    where = root if root is not None else mods_root()
    if not where.is_dir():
        return Registry(where, [])

    found: list[Mod] = []
    for candidate in sorted(where.iterdir()):
        if not candidate.is_dir() or not (candidate / MANIFEST_NAME).exists():
            continue
        found.append(Mod(read(candidate), candidate))
    return Registry(where, found)
