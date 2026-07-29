"""Placed items as a CSV table.

    # mods/my-mod/tables/items.csv
    map,x,y,z
    he1_03,-300,0,0

⚠️ **An item is not an enemy, and the columns say so.** Enemies live in 100
fixed slots addressed by `slot`; the item section is a *variable-length list*
with an explicit count, so the column is `index` and it is **optional** -- a row
with no `index` adds an item, which is the common case. Reusing the word `slot`
here would tell a reader the number means something it does not.

Two consequences of the list being counted and dense:

- There is no orphan rule. D79's trap is that the game stops reading enemies at
  the first empty slot; a counted array cannot have a hole, so removing a middle
  item is ordinary.
- `clear` needs an `index`. There is no empty item to clear.

⚠️ **Only type 0 exists.** `setupItemTemplates` holds exactly one entry -- a
coin -- and all 1,299 items across the 14 maps that place any are type 0 with
flags 0x11. Any other `type` is refused rather than written, because it would
index past the end of that array.

🔶 **Adding items to a map that ships none is not verified in game.** 213 of the
227 maps have no item section at all, and the game reads `itemCount` from
offset 0x2BC4 unconditionally -- past the end of those files, where upstream
notes it "reads uninitialised memory that happens to be 0 because of disc
alignment". Writing a real count there should therefore be read normally, but
"should" is doing the work: nothing has watched a coin appear in such a map.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.formats import setup
from bleck.formats.tables.common import (
    Header,
    Schema,
    TableError,
    flag,
    map_of,
    position,
    split,
    text_of,
    too_wide,
    whole,
)

#: `map` alone: every other column is optional, because a row that gives only a
#: position is the add.
REQUIRED = ("map",)

#: A bound table needs nothing -- the manifest already said the map.
REQUIRED_BOUND: tuple[str, ...] = ()

OPTIONAL = ("index", "x", "y", "z", "type", "flags", "clear")

COLUMNS = REQUIRED + OPTIONAL

SCHEMA = Schema(columns=COLUMNS, required=REQUIRED, required_bound=REQUIRED_BOUND)


@dataclass(frozen=True)
class Row:
    """One row: which item of which map, and what to do to it."""

    map_name: str
    line: int
    """1-based, counting comments and blank lines, so it matches an editor."""

    index: int | None = None
    """Which existing item, or `None` for a row that adds one."""

    position: setup.Position | None = None
    type: int | None = None
    flags: int | None = None
    clear: bool = False

    @property
    def is_add(self) -> bool:
        return self.index is None and not self.clear

    def describe(self) -> str:
        where = "a new item" if self.index is None else f"item {self.index}"
        if self.clear:
            return f"{where} of {self.map_name}: removed"
        parts = []
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        if self.type is not None:
            parts.append(f"type {self.type}")
        if self.flags is not None:
            parts.append(f"flags 0x{self.flags:02x}")
        return f"{where} of {self.map_name}: {', '.join(parts)}"


@dataclass(frozen=True)
class Table:
    """One item table file's rows, and where they came from."""

    source: str
    rows: list[Row]
    map_name: str = ""


def read(path: Path, source: str = "", map_name: str = "") -> Table:
    """Read an item table from disk."""
    where = source or path.name
    return parse(text_of(path, where), where, map_name)


def parse(text: str, source: str, map_name: str = "") -> Table:
    """Read an item table from text. Raises `TableError` on anything unexpected."""
    body = split(text, source, SCHEMA, map_name)
    return Table(
        source=source,
        map_name=map_name,
        rows=[
            _row(body.header, record, source, line.number, map_name)
            for line, record in body.numbered()
        ],
    )


def _row(
    header: Header, record: list[str], source: str, line: int, bound: str = ""
) -> Row:
    """One data row.

    ⚠️ **An empty `index` is not an error, it is the add.** That is the opposite
    of the enemy table, where an empty `slot` means the row says nothing.
    """
    where = f"{source}:{line}"
    too_wide(header, record, where)

    map_name = map_of(header, record, bound, where)
    index = _index(header.cell(record, "index"), where)
    clear = flag(header.cell(record, "clear"), where)
    at = position(header, record, where)
    kind = _type(header.cell(record, "type"), where)
    flags = _flags(header.cell(record, "flags"), where)

    _check(
        index,
        clear,
        at is not None,
        kind is not None or flags is not None,
        where,
    )
    return Row(
        map_name=map_name,
        line=line,
        index=index,
        position=at,
        type=kind,
        flags=flags,
        clear=clear,
    )


def _check(index: int | None, clear: bool, placed: bool, tuned: bool, where: str) -> None:
    """What a row must say to mean anything.

    ⚠️ `placed` and `tuned` are separate because **adding needs a position and
    editing does not**. An added item with no coordinates would land at the
    origin, which is off the map in most rooms -- and an item nobody can reach
    looks exactly like an item that never spawned.
    """
    if clear:
        if index is None:
            raise TableError(
                f"{where}: 'clear' needs an 'index'. Items are a counted list "
                f"rather than fixed slots, so there is no empty item to clear"
            )
        if placed or tuned:
            raise TableError(
                f"{where}: item {index} both clears and sets something. "
                f"Removing it discards the rest"
            )
        return
    if index is None:
        if placed:
            return
        if tuned:
            raise TableError(
                f"{where}: an added item needs a position -- 'type' and 'flags' "
                f"alone do not say where it goes"
            )
        raise TableError(
            f"{where}: this row changes nothing. Give 'index' to change an item "
            f"the map already places, or x, y and z to add one"
        )
    if not placed and not tuned:
        raise TableError(
            f"{where}: item {index} changes nothing. "
            f"Give a position, 'type', 'flags', or 'clear'"
        )


def _index(text: str, where: str) -> int | None:
    if not text:
        return None
    index = whole(text, where, "index")
    if index < 0:
        raise TableError(f"{where}: 'index' {index} is negative")
    return index


def _type(text: str, where: str) -> int | None:
    """⚠️ Refuses anything but a coin, because the game has nothing else."""
    if not text:
        return None
    kind = whole(text, where, "type")
    if kind != setup.Item.COIN:
        raise TableError(
            f"{where}: 'type' {kind} is not a thing the game can place. "
            f"`setupItemTemplates` holds exactly one entry, id {setup.Item.COIN} "
            f"-- a coin -- so any other type indexes past the end of it.\n"
            f"  All 1,299 items the game ships are type {setup.Item.COIN}."
        )
    return kind


def _flags(text: str, where: str) -> int | None:
    """Base-prefixed, because these are read as a bit pattern: `0x11`, not 17."""
    if not text:
        return None
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise TableError(
            f"{where}: 'flags' must be a whole number, got {text!r} "
            f"(0x{setup.Item.SPAWNS:02x} is what every shipped item has)"
        ) from exc
    if not 0 <= value <= 0xFFFF:
        raise TableError(f"{where}: 'flags' {text!r} does not fit in 16 bits")
    return value
