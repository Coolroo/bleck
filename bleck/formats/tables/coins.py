"""Placed coins as a CSV table.

    # mods/my-mod/tables/coins.csv
    map,x,y,z
    he1_03,-300,0,0

**Coins, not "items", because the engine itself says so.** The setup file's
section is `SetupItem[]`, but `setupItemTemplates` holds exactly one entry and
the spawner branches on `itemTemplateId == 1` -- a world coin -- taking a wholly
different code path from every other item (D130). All 299 across the 14 maps
that place any are coins. So there is no `type` column: there is nothing else to
put there, and calling the file `items.csv` invited authors to try.

⚠️ **A coin is not an enemy, and the columns say so.** Enemies live in 100 fixed
slots addressed by `slot`; this section is a *variable-length list* with an
explicit count, so the column is `index` and it is **optional** -- a row with no
`index` adds a coin, which is the common case. Reusing the word `slot` here
would tell a reader the number means something it does not.

Two consequences of the list being counted and dense:

- There is no orphan rule. D79's trap is that the game stops reading enemies at
  the first empty slot; a counted array cannot have a hole, so removing a middle
  coin is ordinary.
- `clear` needs an `index`. There is no empty coin to clear.

⛔ **A map that places no coins cannot be given one -- it HANGS** (D127, D130).
A coin is persistent, so each owns a save flag drawn from a fixed per-map budget
in `assign_tbl`. The budget is spent by coins in *blocks* as well as floating
ones, and those never appear in a setup file -- so a map with none has typically
already spent it, and the game asserts `コインのフラグが溢れました`, "the coin
flags have overflowed". `bleck/mods/build/edits.py` refuses it.
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

OPTIONAL = ("index", "x", "y", "z", "flags", "clear")

COLUMNS = REQUIRED + OPTIONAL

SCHEMA = Schema(columns=COLUMNS, required=REQUIRED, required_bound=REQUIRED_BOUND)


@dataclass(frozen=True)
class Row:
    """One row: which coin of which map, and what to do to it."""

    map_name: str
    line: int
    """1-based, counting comments and blank lines, so it matches an editor."""

    index: int | None = None
    """Which existing coin, or `None` for a row that adds one."""

    position: setup.Position | None = None
    flags: int | None = None
    clear: bool = False

    @property
    def is_add(self) -> bool:
        return self.index is None and not self.clear

    def describe(self) -> str:
        where = "a new coin" if self.index is None else f"coin {self.index}"
        if self.clear:
            return f"{where} of {self.map_name}: removed"
        parts = []
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        if self.flags is not None:
            parts.append(f"flags 0x{self.flags:02x}")
        return f"{where} of {self.map_name}: {', '.join(parts)}"


@dataclass(frozen=True)
class Table:
    """One coin table file's rows, and where they came from."""

    source: str
    rows: list[Row]
    map_name: str = ""


def read(path: Path, source: str = "", map_name: str = "") -> Table:
    """Read a coin table from disk."""
    where = source or path.name
    return parse(text_of(path, where), where, map_name)


def parse(text: str, source: str, map_name: str = "") -> Table:
    """Read a coin table from text. Raises `TableError` on anything unexpected."""
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
    flags = _flags(header.cell(record, "flags"), where)

    _check(index, clear, at is not None, flags is not None, where)
    return Row(
        map_name=map_name,
        line=line,
        index=index,
        position=at,
        flags=flags,
        clear=clear,
    )


def _check(index: int | None, clear: bool, placed: bool, tuned: bool, where: str) -> None:
    """What a row must say to mean anything.

    ⚠️ `placed` and `tuned` are separate because **adding needs a position and
    editing does not**. An added coin with no coordinates would land at the
    origin, which is off the map in most rooms -- and a coin nobody can reach
    looks exactly like a coin that never spawned.
    """
    if clear:
        if index is None:
            raise TableError(
                f"{where}: 'clear' needs an 'index'. Coins are a counted list "
                f"rather than fixed slots, so there is no empty coin to clear"
            )
        if placed or tuned:
            raise TableError(
                f"{where}: coin {index} both clears and sets something. "
                f"Removing it discards the rest"
            )
        return
    if index is None:
        if placed:
            return
        if tuned:
            raise TableError(
                f"{where}: an added coin needs a position -- 'flags' alone "
                f"does not say where it goes"
            )
        raise TableError(
            f"{where}: this row changes nothing. Give 'index' to move a coin "
            f"the map already places, or x, y and z to add one"
        )
    if not placed and not tuned:
        raise TableError(
            f"{where}: coin {index} changes nothing. Give a position, 'flags', or 'clear'"
        )


def _index(text: str, where: str) -> int | None:
    if not text:
        return None
    index = whole(text, where, "index")
    if index < 0:
        raise TableError(f"{where}: 'index' {index} is negative")
    return index


def _flags(text: str, where: str) -> int | None:
    """Base-prefixed, because these are read as a bit pattern: `0x11`, not 17."""
    if not text:
        return None
    try:
        value = int(text, 0)
    except ValueError as exc:
        raise TableError(
            f"{where}: 'flags' must be a whole number, got {text!r} "
            f"(0x{setup.Item.SPAWNS:02x} is what every shipped coin has)"
        ) from exc
    if not 0 <= value <= 0xFFFF:
        raise TableError(f"{where}: 'flags' {text!r} does not fit in 16 bits")
    return value
