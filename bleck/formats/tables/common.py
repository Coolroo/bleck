"""What every table file has in common: comments, a header, and cells.

Only the *columns* differ between one kind of table and the next, so the file
shape lives here once and each kind supplies its own `Schema` and its own row
reader. Domain rules do not belong here -- a slot range and an item type have
nothing to say to each other.

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

#: All-or-none: one or two of these is an error, never a silent zero.
AXES = ("x", "y", "z")

WHOLE = re.compile(r"^[+-]?\d+$")

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


class TableError(BleckError):
    """A table file is malformed, or a row in it does not make sense."""


@dataclass(frozen=True)
class Schema:
    """Which columns a kind of table has, and which it cannot do without.

    Data rather than a second copy of the reader: the two kinds differ in their
    column lists and in nothing else about the file's shape.
    """

    columns: tuple[str, ...]
    required: tuple[str, ...]
    """Needed when each row names its own map."""

    required_bound: tuple[str, ...]
    """Needed when the manifest already bound the table to one map, which drops
    the `map` column."""

    def needs(self, bound: bool) -> tuple[str, ...]:  # pylint: disable=container-return
        return self.required_bound if bound else self.required


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
class Line:
    """A line that survived comment stripping, with its original number."""

    number: int
    text: str


@dataclass(frozen=True)
class Body:
    """A file split into its header row and its data rows, comments dropped."""

    header: Header
    lines: list[Line]
    records: list[list[str]]

    def numbered(self) -> list[tuple[Line, list[str]]]:  # pylint: disable=container-return
        return list(zip(self.lines, self.records, strict=True))


def text_of(path: Path, where: str) -> str:
    if not path.is_file():
        raise TableError(f"{where}: no such table file")
    # utf-8-sig: a spreadsheet writing CSV on Windows leads with a BOM, and a
    # BOM on the first header cell would read as an unknown column.
    return path.read_text(encoding="utf-8-sig")


def split(text: str, source: str, schema: Schema, map_name: str) -> Body:
    """Strip comments, read the header, and hand back the rows unparsed."""
    lines = [
        Line(number=number, text=raw)
        for number, raw in enumerate(text.splitlines(), start=1)
        if raw.strip() and not raw.lstrip().startswith(COMMENT)
    ]
    if not lines:
        example = [name for name in schema.columns if not (map_name and name == "map")]
        raise TableError(
            f"{source}: no header row. The first line that is neither blank nor "
            f"a '{COMMENT}' comment must name the columns, e.g. "
            f"'{','.join(example)}'"
        )

    records = list(csv.reader(line.text for line in lines))
    header = _header(records[0], f"{source}:{lines[0].number}", schema, map_name)
    return Body(header=header, lines=lines[1:], records=records[1:])


def _header(cells: list[str], where: str, schema: Schema, map_name: str) -> Header:
    names = [cell.strip().lower() for cell in cells]
    for index, name in enumerate(names, start=1):
        if not name:
            raise TableError(
                f"{where}: column {index} has no name. Every column needs a "
                f"heading; a trailing comma leaves one blank"
            )
        if name not in schema.columns:
            raise TableError(
                f"{where}: unknown column {name!r}. "
                f"Known columns: {', '.join(schema.columns)}"
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

    required = schema.needs(bool(map_name))
    missing = [name for name in required if name not in names]
    if missing:
        optional = [
            name for name in schema.columns if name not in required and name != "map"
        ]
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


def too_wide(header: Header, record: list[str], where: str) -> None:
    """⚠️ A row **longer** than the header is refused and a shorter one is not: a
    missing trailing cell is an omitted optional column, but an extra cell is
    data with nowhere to go, and dropping it silently is how a placement ends up
    somewhere nobody asked for."""
    if len(record) > len(header.names):
        raise TableError(
            f"{where}: {len(record)} values for {len(header.names)} columns "
            f"({', '.join(header.names)})"
        )


def map_of(header: Header, record: list[str], bound: str, where: str) -> str:
    map_name = bound or header.cell(record, "map")
    if not map_name:
        raise TableError(f"{where}: 'map' is empty; every row names the map it edits")
    return map_name


def flag(text: str, where: str, column: str = "clear") -> bool:
    if not text:
        return False
    lowered = text.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise TableError(
        f"{where}: '{column}' must be true or false, got {text!r} "
        f"(accepted: {', '.join(sorted(_TRUE | _FALSE))})"
    )


def position(header: Header, record: list[str], where: str) -> setup.Position | None:
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
        *[number(value, where, axis) for axis, value in zip(AXES, given, strict=True)]
    )


def number(text: str, where: str, column: str) -> float:
    try:
        return float(text)
    except ValueError as exc:
        raise TableError(f"{where}: '{column}' must be a number, got {text!r}") from exc


def whole(text: str, where: str, column: str) -> int:
    if not WHOLE.match(text):
        raise TableError(f"{where}: '{column}' must be a whole number, got {text!r}")
    return int(text)
