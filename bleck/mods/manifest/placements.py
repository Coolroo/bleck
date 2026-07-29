"""Declared changes to a map's enemy placement.

⚠️ Edits are *declared*, never shipped as bytes; `bleck` derives the file at
build time so the change stays reviewable and undoable (`docs/vision.md`).
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class MapPlacements:
    """Every declared change to one map's placements."""

    map_name: str
    edits: list[PlacementEdit]


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


#: Kinds the design calls for that nothing reads yet. Named apart from a plain
#: typo so a mod declaring one is told it is unbuilt rather than misspelled --
#: the alternative, accepting it and reading nothing, is a table that looks
#: applied and is not.
PLANNED_KINDS = ("items", "doors")


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


def _parse_setup(raw: object, source: str) -> list[MapPlacements]:
    """Read the `setup` block: map name -> a list of slot edits."""
    if raw is None:
        return []
    if not isinstance(raw, dict):
        raise ManifestError(
            f"{source}: 'setup' must be an object of map name -> list of edits"
        )

    placements = []
    for map_name, edits in raw.items():
        if not isinstance(edits, list):
            raise ManifestError(f"{source}: 'setup.{map_name}' must be a list of edits")
        placements.append(
            MapPlacements(
                map_name=map_name,
                edits=[_parse_edit(e, f"{source}: setup.{map_name}") for e in edits],
            )
        )
    return placements


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
