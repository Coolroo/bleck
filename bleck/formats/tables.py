"""CSV tables: placements declared in a file rather than inline in `mod.json`.

A mod can say what a map spawns two ways, and they mean exactly the same thing:

    "setup": { "he1_01": [ { "slot": 3, "template": 2 } ] }     inline
    "tables": { "enemies": "tables/enemies.csv" }               a table

Inline is right for a handful of rows. Past that, JSON stops being readable and
starts being punctuation, so a table takes over:

    # mods/my-mod/tables/enemies.csv
    map,slot,template,x,y,z,copy_from
    he1_01,3,Squiglet,-300,0,0,0

⚠️ **The key is the kind, not a label.** `enemies` says what the rows describe;
it is a closed set, and `bleck` refuses anything else rather than reading it as
enemy placements anyway (D125).

**A table can instead be bound to one map**, which is what a mod that reworks a
level actually wants -- one file per map, and no column repeating the filename.
Several tables under one kind is a list:

    "tables": {
      "enemies": [
        { "path": "tables/he1_01.csv", "map": "he1_01" },
        { "path": "tables/he2_01.csv", "map": "he2_01" }
      ]
    }

    # mods/my-mod/tables/he1_01.csv
    slot,template,x,y,z
    3,Squiglet,-300,0,0

⚠️ **A bound table may not also carry a `map` column.** Two places to say the
same thing is two places for them to disagree, and the disagreement would be
invisible; the column is refused rather than checked.

⚠️ **CSV has no comment syntax.** Lines starting with `#` and blank lines are
skipped here, which is a deliberate extension and the format's one real
weakness: the file is no longer strictly CSV, and a quoted field therefore
cannot contain a newline. It buys the ability to say *why* a row exists, which a
table of a hundred bare numbers badly needs (D124).

Every message names the file and the 1-based line, `tables/enemies.csv:4: ...`,
because "unknown column" without a line number is unusable at 200 rows.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError
from bleck.formats import setup

#: A line whose first non-space character is this is a comment.
COMMENT = "#"

#: Without these a row does not say what it edits. `map` drops out when the
#: manifest already binds the table to one map.
REQUIRED = ("map", "slot")

#: What a bound table needs instead.
REQUIRED_BOUND = ("slot",)

#: Everything else. Column *order* is free; the header decides it.
OPTIONAL = ("template", "x", "y", "z", "copy_from", "clear")

COLUMNS = REQUIRED + OPTIONAL

#: All-or-none: one or two of these is an error, never a silent zero.
AXES = ("x", "y", "z")

_WHOLE = re.compile(r"^[+-]?\d+$")

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


class TableError(BleckError):
    """A table file is malformed, or a row in it does not make sense."""


@dataclass(frozen=True)
class TableRow:
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
class Header:
    """The columns this file names, in the order it names them.

    Order is free, so a row is read by column *name*; `names` is the mapping
    from one to the other and there are never more than eight of them.
    """

    names: list[str]

    def has(self, column: str) -> bool:
        return column in self.names

    def cell(self, record: list[str], column: str) -> str:
        """One cell, stripped. Empty for a column this file does not have, and
        for a row that stops before reaching it."""
        if column not in self.names:
            return ""
        index = self.names.index(column)
        return record[index].strip() if index < len(record) else ""


@dataclass(frozen=True)
class Table:
    """One table file's rows, and where they came from."""

    source: str
    """Posix-style and relative to the mod root: it goes into error messages."""

    rows: list[TableRow]

    map_name: str = ""
    """The map the manifest bound this table to, or empty when its rows say."""


@dataclass(frozen=True)
class _Line:
    """A line that survived comment stripping, with its original number."""

    number: int
    text: str


def read(path: Path, source: str = "", map_name: str = "") -> Table:
    """Read a table from disk. `source` is what messages should call it, and
    `map_name` binds every row to one map (see the module docstring)."""
    where = source or path.name
    if not path.is_file():
        raise TableError(f"{where}: no such table file")
    # utf-8-sig: a spreadsheet writing CSV on Windows leads with a BOM, and a
    # BOM on the first header cell would read as an unknown column.
    return parse(path.read_text(encoding="utf-8-sig"), where, map_name)


def parse(text: str, source: str, map_name: str = "") -> Table:
    """Read a table from text. Raises `TableError` on anything unexpected."""
    lines = [
        _Line(number=number, text=raw)
        for number, raw in enumerate(text.splitlines(), start=1)
        if raw.strip() and not raw.lstrip().startswith(COMMENT)
    ]
    if not lines:
        example = [name for name in COLUMNS if not (map_name and name == "map")]
        raise TableError(
            f"{source}: no header row. The first line that is neither blank nor "
            f"a '{COMMENT}' comment must name the columns, e.g. "
            f"'{','.join(example)}'"
        )

    records = list(csv.reader(line.text for line in lines))
    header = _header(records[0], f"{source}:{lines[0].number}", map_name)
    return Table(
        source=source,
        map_name=map_name,
        rows=[
            _row(header, record, source, line.number, map_name)
            for line, record in zip(lines[1:], records[1:], strict=True)
        ],
    )


def _header(cells: list[str], where: str, map_name: str = "") -> Header:
    names = [cell.strip().lower() for cell in cells]
    for index, name in enumerate(names, start=1):
        if not name:
            raise TableError(
                f"{where}: column {index} has no name. Every column needs a "
                f"heading; a trailing comma leaves one blank"
            )
        if name not in COLUMNS:
            raise TableError(
                f"{where}: unknown column {name!r}. Known columns: {', '.join(COLUMNS)}"
            )
        if names.index(name) != index - 1:
            raise TableError(
                f"{where}: column {name!r} appears twice, so which one a row "
                f"means is undefined"
            )

    # ⚠️ Refused rather than checked: a bound table that also carried a `map`
    # column would have two answers to one question, and a row disagreeing with
    # the manifest is exactly the kind of edit that looks applied and is not.
    if map_name and "map" in names:
        raise TableError(
            f"{where}: this table is bound to {map_name!r} in mod.json, so it "
            f"cannot also have a 'map' column. Drop the column, or drop the "
            f"'map' from the declaration and let each row name its own"
        )

    required = REQUIRED_BOUND if map_name else REQUIRED
    missing = [name for name in required if name not in names]
    if missing:
        optional = [name for name in COLUMNS if name not in required and name != "map"]
        raise TableError(
            f"{where}: missing required column(s) {', '.join(missing)}. "
            f"Required: {', '.join(required)}; "
            f"optional: {', '.join(optional)}"
        )

    axes = [axis for axis in AXES if axis in names]
    if axes and len(axes) != len(AXES):
        absent = ", ".join(axis for axis in AXES if axis not in names)
        raise TableError(
            f"{where}: a position needs all three of x, y and z, but this table "
            f"has no {absent} column. Two axes and a silent zero for the third "
            f"is a placement nobody meant"
        )
    return Header(names=names)


def _row(
    header: Header, record: list[str], source: str, line: int, bound: str = ""
) -> TableRow:
    """One data row.

    ⚠️ A row **longer** than the header is refused and a shorter one is not: a
    missing trailing cell is an omitted optional column, but an extra cell is
    data with nowhere to go, and dropping it silently is how a placement ends up
    somewhere nobody asked for.
    """
    where = f"{source}:{line}"
    if len(record) > len(header.names):
        raise TableError(
            f"{where}: {len(record)} values for {len(header.names)} columns "
            f"({', '.join(header.names)})"
        )

    map_name = bound or header.cell(record, "map")
    if not map_name:
        raise TableError(f"{where}: 'map' is empty; every row names the map it edits")

    slot = _slot(header.cell(record, "slot"), where, "slot")
    clear = _flag(header.cell(record, "clear"), where)
    template = _template(header.cell(record, "template"), where)
    position = _position(header, record, where)
    copy_from = _copy_from(header.cell(record, "copy_from"), slot, where)

    if clear and (template is not None or position is not None or copy_from is not None):
        raise TableError(
            f"{where}: slot {slot} both clears and sets something. "
            f"Clearing empties the slot, so the rest would be discarded"
        )
    if not clear and template is None and position is None and copy_from is None:
        raise TableError(
            f"{where}: slot {slot} changes nothing. "
            f"Give 'template', a position, 'copy_from', or 'clear'"
        )
    return TableRow(
        map_name=map_name,
        slot=slot,
        line=line,
        template=template,
        position=position,
        copy_from=copy_from,
        clear=clear,
    )


def _slot(text: str, where: str, column: str) -> int:
    if not text:
        raise TableError(f"{where}: '{column}' is empty; it needs a slot number")
    if not _WHOLE.match(text):
        raise TableError(f"{where}: '{column}' must be a whole number, got {text!r}")
    slot = int(text)
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


def _flag(text: str, where: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise TableError(
        f"{where}: 'clear' must be true or false, got {text!r} "
        f"(accepted: {', '.join(sorted(_TRUE | _FALSE))})"
    )


def _position(header: Header, record: list[str], where: str) -> setup.Position | None:
    given = [header.cell(record, axis) for axis in AXES]
    if not any(given):
        return None
    missing = [axis for axis, value in zip(AXES, given, strict=True) if not value]
    if missing:
        raise TableError(
            f"{where}: a position needs all three of x, y and z, but "
            f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} empty. "
            f"Leave all three blank to keep the slot where it is"
        )
    return setup.Position(
        *[_number(value, where, axis) for axis, value in zip(AXES, given, strict=True)]
    )


def _number(text: str, where: str, column: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise TableError(f"{where}: '{column}' must be a number, got {text!r}") from exc


def _template(text: str, where: str) -> int | None:
    """A template id, written as a number or as the enemy's name."""
    if not text:
        return None
    if _WHOLE.match(text):
        return int(text)

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
