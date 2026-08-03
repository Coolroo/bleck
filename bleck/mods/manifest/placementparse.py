"""Reading the `setup`, `tables` and `levels` blocks out of a `mod.json`.

Split from `placements`, which is the values this produces. Everything here is
document validation: the shapes a key may take, and the message when it takes
another. `manifest/code/parse.py` makes the same split for the `code` block, and
for the same reason -- a parse error has to name the key and the file, and none
of that reasoning belongs beside the value it eventually builds.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from bleck.formats import setup
from bleck.mods.errors import ManifestError
from bleck.mods.manifest.placements import (
    PLANNED_KINDS,
    CoinEdit,
    LevelRef,
    MapPlacements,
    PlacementEdit,
    TableKind,
    TableRef,
)

#: What a map name looks like on this disc. Used by the `levels` shorthand,
#: which reads a map name out of a directory name.
_MAP_NAME = re.compile(r"^[a-z]{2,4}\d?_\d{2}$")


def parse_levels(raw: object, source: str) -> list[LevelRef]:
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
    """Group refs back under their kind, the inverse of `parse_tables`.

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


def parse_tables(raw: object, source: str) -> list[TableRef]:
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


def parse_setup(raw: object, source: str) -> list[MapPlacements]:
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
