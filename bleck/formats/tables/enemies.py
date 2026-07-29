"""Enemy placements as a CSV table.

    # mods/my-mod/tables/enemies.csv
    map,slot,template,x,y,z,copy_from
    he1_01,3,Squiglet,-300,0,0,0

A map has **100 fixed enemy slots**, so every row names one and `slot` is
required. An empty slot is a real thing -- it is what most of the 100 are -- and
`clear` puts one back.

⛔ **Clearing a middle slot orphans every slot after it** (D79): the game stops
reading setup entries at the first empty one. `bleck/mods/build/edits.py`
refuses that at build time, where the whole file is in view; a single row cannot
see it.
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

#: Without these a row does not say what it edits. `map` drops out when the
#: manifest already binds the table to one map.
REQUIRED = ("map", "slot")

#: What a bound table needs instead.
REQUIRED_BOUND = ("slot",)

#: Everything else. Column *order* is free; the header decides it.
OPTIONAL = ("template", "x", "y", "z", "copy_from", "clear")

COLUMNS = REQUIRED + OPTIONAL

SCHEMA = Schema(columns=COLUMNS, required=REQUIRED, required_bound=REQUIRED_BOUND)


@dataclass(frozen=True)
class Row:
    """One row: which slot of which map, and what to do to it.

    Deliberately the same vocabulary as an inline edit, plus `copy_from` and the
    line it came from. The conversion to a `PlacementEdit` lives in
    `bleck/mods/build/edits.py` -- `bleck.formats` does not import `bleck.mods`.
    """

    map_name: str
    slot: int
    line: int
    """1-based, counting comments and blank lines, so it matches an editor."""

    template: int | None = None
    position: setup.Position | None = None
    copy_from: int | None = None
    """A slot whose whole entry is copied before anything else is applied."""

    clear: bool = False

    def describe(self) -> str:
        if self.clear:
            return f"slot {self.slot} of {self.map_name}: cleared"
        parts = []
        if self.copy_from is not None:
            parts.append(f"copied from slot {self.copy_from}")
        if self.template is not None:
            parts.append(f"template {self.template}")
        if self.position is not None:
            parts.append(f"at {self.position.describe()}")
        return f"slot {self.slot} of {self.map_name}: {', '.join(parts)}"


@dataclass(frozen=True)
class Table:
    """One enemy table file's rows, and where they came from."""

    source: str
    """Posix-style and relative to the mod root: it goes into error messages."""

    rows: list[Row]

    map_name: str = ""
    """The map the manifest bound this table to, or empty when its rows say."""


def read(path: Path, source: str = "", map_name: str = "") -> Table:
    """Read an enemy table from disk. `source` is what messages should call it,
    and `map_name` binds every row to one map."""
    where = source or path.name
    return parse(text_of(path, where), where, map_name)


def parse(text: str, source: str, map_name: str = "") -> Table:
    """Read an enemy table from text. Raises `TableError` on anything unexpected."""
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
    where = f"{source}:{line}"
    too_wide(header, record, where)

    map_name = map_of(header, record, bound, where)
    slot = _slot(header.cell(record, "slot"), where, "slot")
    clear = flag(header.cell(record, "clear"), where)
    template = _template(header.cell(record, "template"), where)
    at = position(header, record, where)
    copy_from = _copy_from(header.cell(record, "copy_from"), slot, where)

    if clear and (template is not None or at is not None or copy_from is not None):
        raise TableError(
            f"{where}: slot {slot} both clears and sets something. "
            f"Clearing empties the slot, so the rest would be discarded"
        )
    if not clear and template is None and at is None and copy_from is None:
        raise TableError(
            f"{where}: slot {slot} changes nothing. "
            f"Give 'template', a position, 'copy_from', or 'clear'"
        )
    return Row(
        map_name=map_name,
        slot=slot,
        line=line,
        template=template,
        position=at,
        copy_from=copy_from,
        clear=clear,
    )


def _slot(text: str, where: str, column: str) -> int:
    if not text:
        raise TableError(f"{where}: '{column}' is empty; it needs a slot number")
    slot = whole(text, where, column)
    if not 0 <= slot < setup.ENEMY_SLOTS:
        raise TableError(
            f"{where}: '{column}' {slot} is out of range (a setup file has "
            f"exactly {setup.ENEMY_SLOTS} slots, 0-{setup.ENEMY_SLOTS - 1})"
        )
    return slot


def _copy_from(text: str, slot: int, where: str) -> int | None:
    if not text:
        return None
    source = _slot(text, where, "copy_from")
    if source == slot:
        raise TableError(
            f"{where}: 'copy_from' names slot {slot}, which is this row's own "
            f"slot, so it copies nothing"
        )
    return source


def _template(text: str, where: str) -> int | None:
    """A template id, written as a number or as the enemy's name."""
    if not text:
        return None
    if text.lstrip("+-").isdigit():
        return whole(text, where, "template")

    names = setup.catalog()
    if not names:
        raise TableError(
            f"{where}: cannot look up the name {text!r} -- this build has no NPC "
            f"catalog, so 'template' must be a number here"
        )

    match = names.resolve(text)
    if match.found:
        return match.species.template
    if match.ambiguous:
        raise TableError(
            f"{where}: {text!r} names {len(match.ambiguous)} templates "
            f"({match.candidates}), so which one is meant is not decidable.\n"
            f"  Write the number instead -- e.g. "
            f"'template' {match.ambiguous[0].template}.\n"
            f"  `bleck setup show <map>` lists the templates a map actually uses."
        )
    hint = f" Did you mean: {', '.join(match.near)}?" if match.near else ""
    raise TableError(
        f"{where}: no enemy named {text!r}.{hint}\n"
        f"  Write a template number instead, or run "
        f"`bleck setup show <map>` to see what a map places."
    )
