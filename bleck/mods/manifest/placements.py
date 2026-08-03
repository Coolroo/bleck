"""Declared changes to a map's placements, as the values a manifest holds.

⚠️ Edits are *declared*, never shipped as bytes; `bleck` derives the file at
build time so the change stays reviewable and undoable (`docs/vision.md`).

⚠️ **Nothing here reads JSON.** `placementparse` does that and builds these;
the split is the same one `manifest/code/` already makes between `specs` and
`parse`, and it means a value can be constructed in a test, an API response or
`bleck setup apply` without going near a manifest document. The imports run one
way: `placementparse` reads this, never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from bleck.formats import setup


@dataclass(frozen=True)
class PlacementEdit:
    """One change to one enemy slot, as declared rather than as bytes."""

    slot: int
    template: int | None = None
    position: setup.Position | None = None
    clear: bool = False
    """Empty the slot. Mutually exclusive with the others."""

    copy_from: int | None = None
    """A slot whose whole entry is copied in before anything else is applied.

    ✅ **This is how an added enemy gets the bytes nobody has named** (D123). A
    declared edit otherwise builds on whatever the slot holds, and an unused
    slot holds zeros -- where every shipped enemy carries three undocumented
    values that reach the live NPC. Absent means today's behaviour: build on
    whatever is there.
    """

    def describe(self) -> str:
        if self.clear:
            return f"slot {self.slot}: cleared"
        parts = []
        if self.copy_from is not None:
            parts.append(f"copied from slot {self.copy_from}")
        if self.template is not None:
            parts.append(f"template {self.template}")
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        return f"slot {self.slot}: {', '.join(parts)}"

    def to_json(self) -> dict[str, object]:  # pylint: disable=container-return
        body: dict[str, object] = {"slot": self.slot}
        if self.clear:
            body["clear"] = True
        if self.copy_from is not None:
            body["copy_from"] = self.copy_from
        if self.template is not None:
            body["template"] = self.template
        if self.position is not None:
            body["position"] = list(self.position.as_tuple())
        return body


# Re-exported from the format layer, which owns what the bytes mean.
COIN = setup.Item.COIN
SPAWN_FLAGS = setup.Item.SPAWNS


@dataclass(frozen=True)
class CoinEdit:
    """One change to one placed item.

    ⚠️ **An item has no slot.** Enemies live in 100 fixed slots and are addressed
    by number; the item section is a *variable-length list* with an explicit
    count, so there is no such thing as an empty item slot. `index` is a position
    in that list, and **absent means append** -- which is how a map gains an item
    it never had. That is also why there is no orphan rule here: the D79 trap is
    that the game stops reading enemies at the first empty slot, and a dense
    counted array cannot have a hole.
    """

    index: int | None = None
    """Which existing item, or `None` to add one."""

    position: setup.Position | None = None
    flags: int | None = None
    clear: bool = False
    """Remove the coin. Needs an `index`; there is nothing else to remove."""

    @property
    def is_add(self) -> bool:
        return self.index is None and not self.clear

    def describe(self) -> str:
        where = "new item" if self.is_add else f"item {self.index}"
        if self.clear:
            return f"{where}: removed"
        parts = []
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        if self.flags is not None:
            parts.append(f"flags 0x{self.flags:02x}")
        return f"{where}: {', '.join(parts)}"

    def to_json(self) -> dict[str, object]:  # pylint: disable=container-return
        body: dict[str, object] = {}
        if self.index is not None:
            body["index"] = self.index
        if self.clear:
            body["clear"] = True
        if self.position is not None:
            body["position"] = list(self.position.as_tuple())
        if self.flags is not None:
            body["flags"] = self.flags
        return body


@dataclass(frozen=True)
class MapPlacements:
    """Every declared change to one map's placements."""

    map_name: str
    edits: list[PlacementEdit]
    coins: list[CoinEdit] = field(default_factory=list)
    """Changes to the item section. Separate from `edits` because an item is
    addressed differently from an enemy, but carried on the same object because
    both end up in **one** generated `.dat`."""


# `StrEnum` rather than `str, Enum`: the latter still inherits `Enum.__str__`,
# so an f-string renders `TableKind.ENEMIES` instead of `enemies` -- and this one
# goes straight into error messages (D99).
class TableKind(StrEnum):
    """What a table's rows describe. **This is the key in `mod.json`.**

    ⚠️ A closed set on purpose. The first cut of this feature let the key be any
    label -- `"lineland"`, `"my-enemies"` -- and read *every* declared table as a
    placement table regardless of what it was called. That reads like a keyword
    and is not one, and it had no answer at all for the item and door tables the
    design calls for. The key now says what a table *is*, so nothing has to
    guess (D125).
    """

    ENEMIES = "enemies"
    COINS = "coins"
    DOORS = "doors"
    TEXTURES = "textures"


#: Kinds the design calls for that nothing reads yet. Named apart from a plain
#: typo so a mod declaring one is told it is unbuilt rather than misspelled --
#: the alternative, accepting it and reading nothing, is a table that looks
#: applied and is not.
#:
#: ⚠️ Empty since D134. Keep the machinery: the next kind wants this message,
#: not "unknown table kind".
PLANNED_KINDS: tuple[str, ...] = ()

#: Kinds that change a map's setup file, and therefore make a mod something the
#: placement build has to visit.
#:
#: ⚠️ **A kind missing from here is skipped by the entire build, silently** --
#: `has_placements` gates `mods_with_placements`, and a mod that generates
#: nothing still reports "chain OK" (D126).
#:
#: ⛔ `DOORS` is deliberately absent: a door row is a **code patch**, not setup
#: content, and it reaches `code.patches` through
#: `bleck/mods/code/patches.py` instead (D134).
#:
#: ⛔ `TEXTURES` likewise: a texture row rewrites a *file in the overlay*, not a
#: map's setup, and reaches the build through `mods/build/textures.py` (D193).
PLACEMENT_KINDS = (TableKind.ENEMIES, TableKind.COINS)


@dataclass(frozen=True)
class TableRef:
    """A CSV table of placements: what its rows describe, and where it lives.

    ⚠️ **The manifest holds the declared path and nothing more.** Reading the
    file happens at build time, where the mod's directory is known --
    `Manifest.from_json` takes text and has no idea where it came from.
    """

    kind: TableKind
    path: str
    """Relative to the mod root, posix-style, so it survives a Windows round
    trip (`.as_posix()` at parse time)."""

    map_name: str = ""
    """The map every row belongs to, or empty when each row names its own.

    A mod reworking one level wants a file per map and no column repeating the
    filename; a mod sprinkling enemies across ten maps wants the column. Both
    are ordinary, so both are spellable.
    """

    @property
    def is_bound(self) -> bool:
        return bool(self.map_name)

    def to_json(self) -> str | dict[str, str]:  # pylint: disable=container-return
        """The shorthand string when unbound, the object form when bound."""
        if not self.is_bound:
            return self.path
        return {"path": self.path, "map": self.map_name}


@dataclass(frozen=True)
class LevelRef:
    """A directory holding one map's tables, declared under `levels`.

    ⚠️ **Sugar over `tables`, not a second mechanism** (D145). A level expands
    into exactly the `TableRef`s the long form would have declared, bound to the
    same map -- see `bleck/mods/levels.py`. The manifest holds the path and the
    map, and nothing about what is inside: that is on disk, and reading it needs
    the mod's directory.
    """

    path: str
    """Relative to the mod root, posix-style."""

    map_name: str
    """The map every table inside is bound to. Defaults to the directory's own
    name, so `levels/he1_01` needs saying only once."""

    @property
    def named_for_its_map(self) -> bool:
        return self.path.rsplit("/", 1)[-1] == self.map_name

    def to_json(self) -> str | dict[str, str]:  # pylint: disable=container-return
        """A bare path when the directory is named after its map, which is the
        point of the shorthand; the object form otherwise."""
        if self.named_for_its_map:
            return self.path
        return {"path": self.path, "map": self.map_name}
