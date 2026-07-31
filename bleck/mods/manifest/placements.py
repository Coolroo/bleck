"""Declared changes to a map's enemy placement.

⚠️ Edits are *declared*, never shipped as bytes; `bleck` derives the file at
build time so the change stays reviewable and undoable (`docs/vision.md`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath

from bleck.formats import setup
from bleck.mods.errors import ManifestError


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


#: What a map name looks like on this disc. Used by the `levels` shorthand,
#: which reads a map name out of a directory name.
_MAP_NAME = re.compile(r"^[a-z]{2,4}\d?_\d{2}$")

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
#: `bleck/mods/code/parts.py` instead (D134).
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


def _parse_levels(raw: object, source: str) -> list[LevelRef]:
    """Read the `levels` block: a list of directories, or {path, map} objects."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ManifestError(
            f"{source}: 'levels' must be a list of directories, e.g. [\"levels/he1_01\"]"
        )
    return [
        _parse_level(item, f"{source}: levels[{index}]") for index, item in enumerate(raw)
    ]


def _parse_level(raw: object, where: str) -> LevelRef:
    if isinstance(raw, str):
        path = _table_path(raw, where)
        name = path.rsplit("/", 1)[-1]
        _check_level_map(name, path, where)
        return LevelRef(path=path, map_name=name)
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{where}: must be a directory, or an object like "
            f'{{"path": "levels/lineland", "map": "he1_01"}}'
        )
    unknown = sorted(set(raw) - _TABLE_KEYS)
    if unknown:
        raise ManifestError(
            f"{where}: unknown key(s) {', '.join(unknown)}; "
            f"a level takes {', '.join(sorted(_TABLE_KEYS))}"
        )
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ManifestError(f"{where}: needs a 'path' to a directory")
    map_name = raw.get("map", "")
    if not isinstance(map_name, str) or not map_name.strip():
        raise ManifestError(
            f"{where}: needs a 'map'. Only a directory named after its map can "
            f"leave it out."
        )
    return LevelRef(path=_table_path(path, where), map_name=map_name.strip())


def _check_level_map(name: str, path: str, where: str) -> None:
    """⚠️ The shorthand reads the map name out of the path, so a directory
    called `lineland` would bind every table to a map that does not exist and
    the tables would then be refused one by one with a confusing message."""
    if not _MAP_NAME.match(name):
        raise ManifestError(
            f"{where}: {path!r} takes its map name from the directory, and "
            f"{name!r} is not one -- they look like 'he1_01'.\n"
            f'  Say it explicitly: {{"path": "{path}", "map": "he1_01"}}.'
        )


#: What the object form of a table declaration may say. Anything else is a typo
#: worth naming rather than ignoring.
_TABLE_KEYS = {"path", "map"}


def tables_to_json(refs: list[TableRef]) -> dict[str, object]:  # pylint: disable=container-return
    """Group refs back under their kind, the inverse of `_parse_tables`.

    One table stays the scalar it was written as; several become a list. Round
    tripping a single table into a one-element list would rewrite a hand-edited
    `mod.json` for no reason, and `bleck setup apply` writes that file back.
    """
    grouped: dict[str, list[TableRef]] = {}
    for ref in refs:
        grouped.setdefault(str(ref.kind), []).append(ref)
    return {
        kind: found[0].to_json() if len(found) == 1 else [ref.to_json() for ref in found]
        for kind, found in grouped.items()
    }


def _parse_tables(raw: object, source: str) -> list[TableRef]:
    """Read the `tables` block: a kind -> one table, or -> a list of them."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'tables' must be an object of kind -> path, e.g. "
            f'{{"enemies": "tables/enemies.csv"}}. '
            f"Known kinds: {', '.join(TableKind)}"
        )

    out: list[TableRef] = []
    for key, body in raw.items():
        kind = _parse_kind(key, source)
        if isinstance(body, list):
            out += [
                _parse_table(kind, item, f"{source}: tables.{kind}[{index}]")
                for index, item in enumerate(body)
            ]
            continue
        out.append(_parse_table(kind, body, f"{source}: tables.{kind}"))
    return out


def _parse_kind(raw: object, source: str) -> TableKind:
    """The `tables` key, which names what the rows describe.

    ⚠️ The error is the whole point of this function: an author who wrote a
    label needs to be told the key is not one, because a label parses fine and
    then means nothing.
    """
    if not isinstance(raw, str):
        raise ManifestError(
            f"{source}: 'tables' keys name what a table describes, "
            f"one of {', '.join(TableKind)} -- got {raw!r}"
        )

    key = raw.strip().lower()
    if key in tuple(TableKind):
        return TableKind(key)
    if key in PLANNED_KINDS:
        raise ManifestError(
            f"{source}: '{key}' tables are designed but not built yet, so "
            f"declaring one would read nothing and look like it had.\n"
            f"  Kinds that work today: {', '.join(TableKind)}"
        )
    raise ManifestError(
        f"{source}: unknown table kind {raw!r}.\n"
        f"  The key says what a table's rows describe, not what to call the "
        f"file -- so use {', '.join(TableKind)}, and put the label in the "
        f"filename or a '#' comment.\n"
        f"  To bind a table to one map, write "
        f'{{"enemies": {{"path": "tables/he1_01.csv", "map": "he1_01"}}}}.'
    )


def _parse_table(kind: TableKind, body: object, where: str) -> TableRef:
    if isinstance(body, str):
        return TableRef(kind=kind, path=_table_path(body, where))
    if not isinstance(body, dict):
        raise ManifestError(
            f"{where}: must be a path, an object like "
            f'{{"path": "tables/he1_01.csv", "map": "he1_01"}}, '
            f"or a list of either"
        )

    unknown = sorted(set(body) - _TABLE_KEYS)
    if unknown:
        raise ManifestError(
            f"{where}: unknown key(s) {', '.join(unknown)}; "
            f"a table declaration takes {', '.join(sorted(_TABLE_KEYS))}"
        )
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ManifestError(f"{where}: needs a 'path' to a CSV file")

    map_name = body.get("map", "")
    if not isinstance(map_name, str):
        raise ManifestError(f"{where}: 'map' must be a map name, e.g. 'he1_01'")
    return TableRef(kind=kind, path=_table_path(path, where), map_name=map_name.strip())


def _table_path(path: str, where: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ManifestError(f"{where}: must be a path to a CSV file, relative to the mod")
    pure = PurePosixPath(path.strip().replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ManifestError(
            f"{where}: {path!r} must stay inside the mod -- a table is part "
            f"of the mod, so it travels with it"
        )
    return pure.as_posix()


#: What the long form of a `setup.<map>` block may say.
_SETUP_KEYS = {"enemies", "coins"}


def _parse_setup(raw: object, source: str) -> list[MapPlacements]:
    """Read the `setup` block: map name -> enemy edits, or -> both kinds.

    ⚠️ **Two shapes, and the bare list is not deprecated.** A list of enemy
    edits is what every existing manifest says and stays exactly as valid; the
    object form exists only because items had nowhere to go. Rewriting the short
    form into the long one on every save would churn hand-edited files for a
    feature most mods do not use.
    """
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'setup' must be an object of map name -> list of edits"
        )

    placements = []
    for map_name, body in raw.items():
        placements.append(_parse_map(map_name, body, f"{source}: setup.{map_name}"))
    return placements


def _parse_map(map_name: str, body: object, where: str) -> MapPlacements:
    if isinstance(body, list):
        return MapPlacements(
            map_name=map_name, edits=[_parse_edit(e, where) for e in body]
        )
    if not isinstance(body, dict):
        raise ManifestError(
            f"{where}: must be a list of enemy edits, or an object like "
            f'{{"enemies": [...], "coins": [...]}}'
        )

    unknown = sorted(set(body) - _SETUP_KEYS)
    if unknown:
        raise ManifestError(
            f"{where}: unknown key(s) {', '.join(unknown)}; "
            f"a map declares {', '.join(sorted(_SETUP_KEYS))}"
        )
    return MapPlacements(
        map_name=map_name,
        edits=[
            _parse_edit(e, f"{where}.enemies") for e in _listed(body, "enemies", where)
        ],
        coins=[_parse_coin(e, f"{where}.coins") for e in _listed(body, "coins", where)],
    )


def _listed(body: dict, key: str, where: str) -> list:  # pylint: disable=container-return
    found = body.get(key, [])
    if not isinstance(found, list):
        raise ManifestError(f"{where}: '{key}' must be a list of edits")
    return found


def _parse_coin(raw: object, where: str) -> CoinEdit:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: each item edit must be an object")

    index = _parse_index(raw.get("index"), where)
    clear = raw.get("clear", False)
    if not isinstance(clear, bool):
        raise ManifestError(f"{where}: 'clear' must be true or false")

    position = _parse_position(raw.get("position"), where)
    flags = _parse_flags(raw.get("flags"), where)
    _check_coin(
        CoinEdit(index=index, position=position, flags=flags, clear=clear),
        where,
    )
    return CoinEdit(index=index, position=position, flags=flags, clear=clear)


def _check_coin(edit: CoinEdit, where: str) -> None:
    """The rules an item edit must satisfy, shared with the CSV reader.

    ⚠️ **Adding needs a position and editing does not.** An added item with no
    coordinates would land at the origin, which is off the map in most rooms --
    an item nobody can reach looks exactly like an item that did not spawn.
    """
    given = edit.position is not None or edit.flags is not None
    if edit.clear:
        if edit.index is None:
            raise ManifestError(
                f"{where}: 'clear' needs an 'index' -- coins are a list, not "
                f"fixed slots, so there is no empty item to clear"
            )
        if given:
            raise ManifestError(
                f"{where}: item {edit.index} both clears and sets something. "
                f"Removing it discards the rest"
            )
        return
    if edit.index is None and edit.position is None:
        raise ManifestError(
            f"{where}: an added item needs a position. Give 'index' to change "
            f"an item the map already places, or a position to add one"
        )
    if not given:
        raise ManifestError(
            f"{where}: item {edit.index} changes nothing. "
            f"Give a position, 'flags', or 'clear'"
        )


def _parse_index(raw: object, where: str) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ManifestError(f"{where}: 'index' must be a whole number")
    if raw < 0:
        raise ManifestError(f"{where}: 'index' {raw} is negative")
    return raw


def _parse_flags(raw: object, where: str) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ManifestError(f"{where}: 'flags' must be a whole number")
    if not 0 <= raw <= 0xFFFF:
        raise ManifestError(f"{where}: 'flags' 0x{raw:x} does not fit in 16 bits")
    return raw


def _parse_edit(raw: object, where: str) -> PlacementEdit:
    if not isinstance(raw, dict):
        raise ManifestError(f"{where}: each edit must be an object")

    slot = raw.get("slot")
    if not isinstance(slot, int) or isinstance(slot, bool):
        raise ManifestError(f"{where}: every edit needs a numeric 'slot'")
    if not 0 <= slot < setup.ENEMY_SLOTS:
        raise ManifestError(
            f"{where}: slot {slot} is out of range "
            f"(a setup file has exactly {setup.ENEMY_SLOTS} slots, 0-"
            f"{setup.ENEMY_SLOTS - 1})"
        )

    clear = raw.get("clear", False)
    if not isinstance(clear, bool):
        raise ManifestError(f"{where}: 'clear' must be true or false")

    template = raw.get("template")
    if template is not None and (
        not isinstance(template, int) or isinstance(template, bool)
    ):
        raise ManifestError(f"{where}: 'template' must be a whole number")

    position = _parse_position(raw.get("position"), where)
    copy_from = _parse_copy_from(raw.get("copy_from"), slot, where)

    if clear and (template is not None or position is not None or copy_from is not None):
        raise ManifestError(
            f"{where}: slot {slot} both clears and sets something. "
            f"Clearing empties the slot, so the rest would be discarded"
        )
    if not clear and template is None and position is None and copy_from is None:
        raise ManifestError(
            f"{where}: slot {slot} changes nothing. "
            f"Give 'template', 'position', 'copy_from', or 'clear'"
        )
    return PlacementEdit(
        slot=slot,
        template=template,
        position=position,
        clear=clear,
        copy_from=copy_from,
    )


def _parse_copy_from(raw: object, slot: int, where: str) -> int | None:
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ManifestError(f"{where}: 'copy_from' must be a slot number")
    if not 0 <= raw < setup.ENEMY_SLOTS:
        raise ManifestError(
            f"{where}: 'copy_from' {raw} is out of range (0-{setup.ENEMY_SLOTS - 1})"
        )
    if raw == slot:
        raise ManifestError(
            f"{where}: 'copy_from' names slot {slot}, which is the slot being "
            f"edited, so it copies nothing"
        )
    return raw


def _parse_position(raw: object, where: str) -> setup.Position | None:
    if raw is None:
        return None
    numbers = isinstance(raw, list) and len(raw) == 3
    if not numbers or not all(isinstance(v, (int, float)) for v in raw):
        raise ManifestError(
            f"{where}: 'position' must be three numbers, e.g. [100, 0, -50]"
        )
    return setup.Position(float(raw[0]), float(raw[1]), float(raw[2]))
