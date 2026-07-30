"""Mod manifests: `mod.json`.

A manifest declares identity, which base build it targets, what it depends on,
and which paths it claims exclusively.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from bleck.mods.errors import ManifestError

# Re-exported: callers reach these through `manifest`.
# pylint: disable=unused-import
from bleck.mods.manifest.codespec import (  # noqa: F401
    DEFERRED_PATCH_KINDS,
    REL_DISC_PATH,
    BannerSpec,
    CodeSpec,
    ComboBinding,
    FunctionHook,
    HookMode,
    MapHook,
    PatchKind,
    ScriptPatch,
    _parse_code,
)
from bleck.mods.manifest.placements import (  # noqa: F401
    COIN,
    PLACEMENT_KINDS,
    PLANNED_KINDS,
    SPAWN_FLAGS,
    CoinEdit,
    LevelRef,
    MapPlacements,
    PlacementEdit,
    TableKind,
    TableRef,
    _parse_levels,
    _parse_setup,
    _parse_tables,
    tables_to_json,
)


class AssetOrigin(StrEnum):
    """Where a mod's overlay files came from, as its author states it.

    ⛔ **Never inferred.** `bleck` classified overlay files by path and called
    every one game-derived, which is true of a vendored-and-edited texture and
    false of one somebody drew. The tool has no way to tell those apart; the
    author does (D186).
    """

    UNSTATED = "unstated"
    """Not declared. Pack asks, because nobody has said."""

    ORIGINAL = "original"
    """The author's own work. Packs without ceremony."""

    DERIVED = "derived"
    """Started as game data. Packing redistributes it, so it takes a flag."""


MANIFEST_NAME = "mod.json"
# Named `overlay`, not `files`: the disc's data partition is already `files/`.
OVERLAY_DIR = "overlay"
SCHEMA_VERSION = 1

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_REQUIREMENT_RE = re.compile(r"^(>=|<=|==)?\s*(\d+\.\d+\.\d+)$")


@dataclass(frozen=True, order=True)
class Version:
    """A semantic version. Ordered, so requirements compare directly."""

    major: int = 0
    minor: int = 0
    patch: int = 0

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Version:
        match = _VERSION_RE.match(text.strip())
        if not match:
            raise ManifestError(f"bad version {text!r}, expected MAJOR.MINOR.PATCH")
        return cls(int(match[1]), int(match[2]), int(match[3]))


@dataclass(frozen=True)
class Requirement:
    """A dependency on another mod, optionally version-constrained."""

    name: str
    operator: str = ""
    version: Version | None = None

    def __str__(self) -> str:
        if self.version is None:
            return self.name
        return f"{self.name} {self.operator}{self.version}"

    def is_satisfied_by(self, candidate: Version) -> bool:
        if self.version is None:
            return True
        if self.operator == ">=":
            return candidate >= self.version
        if self.operator == "<=":
            return candidate <= self.version
        return candidate == self.version

    @classmethod
    def parse(cls, name: str, spec: str) -> Requirement:
        if not spec:
            return cls(name)
        match = _REQUIREMENT_RE.match(spec.strip())
        if not match:
            raise ManifestError(
                f"bad version requirement {spec!r} for {name!r}; "
                "expected e.g. '>=1.2.0', '==1.0.0'"
            )
        return cls(name, match[1] or "==", Version.parse(match[2]))


# A manifest is a record of independent declarations -- identity, dependencies,
# overlay claims, placements, levels, tables, code. Grouping them to satisfy a
# count would invent structure the file format does not have.
@dataclass(frozen=True)
class Manifest:  # pylint: disable=too-many-instance-attributes
    """A mod's declared identity and relationships."""

    name: str
    version: Version = field(default_factory=Version)
    description: str = ""
    author: str = ""
    base: str = ""
    created: str = ""
    assets: AssetOrigin = AssetOrigin.UNSTATED
    """Where this mod's overlay files came from, as the author states it.

    ⚠️ **`bleck` cannot work this out.** An overlay file replaces something on
    the disc, but a replacement can be original artwork with no game data in it
    at all. Guessing from the path was wrong in both directions (D186), so the
    one person who knows says.
    """
    dependencies: list[Requirement] = field(default_factory=list)
    exclusive: list[str] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    code: CodeSpec | None = None
    setup: list[MapPlacements] = field(default_factory=list)
    """Declared changes to enemy placement, applied at build time."""

    levels: list[LevelRef] = field(default_factory=list)
    """Directories holding one map's tables each -- sugar over `tables` (D145).

    ⚠️ The *paths* only. What a level contains is on disk, so expanding it needs
    the mod's directory: `bleck/mods/levels.py`, reached through
    `Mod.tables_of`."""

    tables: list[TableRef] = field(default_factory=list)
    """CSV files declaring the same thing as `setup`, for when there are enough
    rows that JSON stops being readable. The *paths* only: the rows are read at
    build time, where the mod's directory is known (`bleck/formats/tables.py`).

    Flat, though `mod.json` groups them by kind: a mod may declare several under
    one kind, and every caller either wants one kind or wants all of them.
    `tables_of` is the former."""

    def tables_of(self, kind: TableKind) -> list[TableRef]:
        """Just the tables of one kind, in declaration order.

        ⚠️ **Ask for a kind; never iterate `tables` to read rows.** Doing the
        latter is what made the key decorative -- an `items` table would have
        been read as enemy placements and produced a build nobody asked for
        (D125)."""
        return [ref for ref in self.tables if ref.kind is kind]

    @property
    def has_placements(self) -> bool:
        """Whether this mod changes any map's setup file at all.

        ⚠️ Gates `mods_with_placements`, so a placement kind missing from
        `PLACEMENT_KINDS` is skipped by the whole build while it still reports
        "chain OK" (D126).
        """
        return bool(self.setup) or any(self.tables_of(kind) for kind in PLACEMENT_KINDS)

    @property
    def has_code(self) -> bool:
        return self.code is not None

    def __post_init__(self) -> None:
        """⚠️ A door table without a `code` block would be read by nobody.

        `mods_with_code` gates the whole compile on `has_code`, so such a mod
        would build cleanly, patch nothing, and report success -- D126's exact
        failure. It is refused here instead, where every construction path goes
        through it, rather than at one call site (D134).
        """
        if self.tables_of(TableKind.DOORS) and self.code is None:
            raise ManifestError(
                f"{self.name}: a 'doors' table patches scripts, so it needs a "
                f"'code' block whose sources define the functions its 'call' "
                f"column names.\n"
                f"  Without one the table would be read by nothing and the "
                f"build would report success having patched nothing."
            )

    def to_json(self) -> str:
        body = {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "version": str(self.version),
            "description": self.description,
            "author": self.author,
            "base": self.base,
            "created": self.created,
            "dependencies": [
                {"name": r.name, "version": f"{r.operator}{r.version}"}
                if r.version
                else {"name": r.name}
                for r in self.dependencies
            ],
            "exclusive": self.exclusive,
            "remove": self.remove,
        }
        if self.assets is not AssetOrigin.UNSTATED:
            body["assets"] = str(self.assets)
        if self.setup:
            body["setup"] = {
                placement.map_name: _map_json(placement) for placement in self.setup
            }
        # Omitted rather than written as an empty object, like `setup` and
        # `code`: most mods declare no tables.
        if self.levels:
            body["levels"] = [level.to_json() for level in self.levels]
        if self.tables:
            body["tables"] = tables_to_json(self.tables)
        # Omitted rather than written as null: most mods ship no code.
        if self.code is not None:
            body["code"] = self.code.to_json()
        return json.dumps(body, indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str, source: str = MANIFEST_NAME) -> Manifest:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"{source}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ManifestError(f"{source}: expected a JSON object")

        schema = raw.get("schema", SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            raise ManifestError(
                f"{source}: unsupported schema {schema!r} "
                f"(this build understands {SCHEMA_VERSION})"
            )

        name = raw.get("name", "")
        if not name:
            raise ManifestError(f"{source}: 'name' is required")

        return cls(
            name=name,
            version=Version.parse(raw.get("version", "0.0.0")),
            description=raw.get("description", ""),
            author=raw.get("author", ""),
            base=raw.get("base", ""),
            created=raw.get("created", ""),
            assets=_parse_assets(raw.get("assets"), source),
            dependencies=_parse_dependencies(raw.get("dependencies", []), source),
            exclusive=list(raw.get("exclusive", [])),
            remove=list(raw.get("remove", [])),
            code=_parse_code(raw.get("code"), source),
            setup=_parse_setup(raw.get("setup"), source),
            tables=_parse_tables(raw.get("tables"), source),
            levels=_parse_levels(raw.get("levels"), source),
        )


def _parse_assets(raw: object, source: str) -> AssetOrigin:
    """Read `assets`, which only the author can answer."""
    if raw is None:
        return AssetOrigin.UNSTATED
    if not isinstance(raw, str):
        raise ManifestError(f"{source}: 'assets' must be a string")
    try:
        return AssetOrigin(raw.strip().lower())
    except ValueError:
        known = ", ".join(f"'{member}'" for member in AssetOrigin)
        raise ManifestError(
            f"{source}: unknown 'assets' value {raw!r}. Known values are "
            f"{known}.\n"
            f"  'original' means you made the overlay files yourself; "
            f"'derived' means they started as game data."
        ) from None


def _map_json(placement: MapPlacements) -> object:
    """One map's declared placements, in the shortest shape that says them.

    ⚠️ **A map with no items stays a bare list.** The long form is not an
    upgrade; promoting every map to it would rewrite manifests that never
    mention items, and `bleck setup apply` writes this file back.
    """
    enemies = [edit.to_json() for edit in placement.edits]
    if not placement.coins:
        return enemies
    return {"enemies": enemies, "coins": [coin.to_json() for coin in placement.coins]}


def _parse_dependencies(raw: object, source: str) -> list[Requirement]:
    if not isinstance(raw, list):
        raise ManifestError(f"{source}: 'dependencies' must be a list")
    out: list[Requirement] = []
    for item in raw:
        if isinstance(item, str):
            out.append(Requirement(item))
            continue
        if not isinstance(item, dict) or "name" not in item:
            raise ManifestError(
                f"{source}: each dependency needs a 'name' (got {item!r})"
            )
        out.append(Requirement.parse(item["name"], item.get("version", "")))
    return out


def read(directory: Path) -> Manifest:
    path = directory / MANIFEST_NAME
    if not path.exists():
        raise ManifestError(f"no {MANIFEST_NAME} in {directory}")
    return Manifest.from_json(path.read_text(), source=str(path))


def write(directory: Path, manifest: Manifest) -> None:
    (directory / MANIFEST_NAME).write_text(manifest.to_json())
