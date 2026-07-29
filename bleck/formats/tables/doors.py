"""Door script patches as a CSV table.

    # mods/my-mod/tables/doors.csv
    map,index,script,at,expect,call
    he1_01,0,interact,0,MULF,on_door
    he1_01,0,init,0,0x0002001A,on_door_init

⚠️ **This is not a placement table.** Enemies and coins are *data* in a map's
setup file; a door row is a **code patch** -- one instruction of a script the
game already ships, replaced by a call into the mod. It reaches
`code.patches`, not `setup`, and a mod declaring one needs a `code` block whose
sources define the `call` (D134).

The columns are the four fields of a patch, with the selector split into the
two parts an author actually varies:

    door:he1_01:0:interact  ->  map=he1_01  index=0  script=interact

`script` defaults to `interact` -- the one that runs when the player uses the
door -- matching the selector's own default.

⚠️ **`index` is a position in the list the map registers, not an id**, and
cannot be bounds-checked at build time: how many doors a map has is in the
game's data. One past the end resolves to nothing and reports status 4 at run
time rather than writing anywhere (D103).

⚠️ **`expect` is the guard, not decoration.** Nothing is written unless the word
at `at` matches, so a wrong value means the patch silently does not apply. It
takes an opcode name (`MULF`), a name with its argument count for a variadic
one (`USER_FUNC 4`), or a raw header word (`0x0002001A`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.formats.tables.common import (
    Header,
    Schema,
    TableError,
    map_of,
    split,
    text_of,
    too_wide,
    whole,
)

#: Which door, and what to write into it. Every one is load-bearing: a patch
#: with no `expect` cannot guard, and one with no `call` has nothing to call.
REQUIRED = ("map", "index", "at", "expect", "call")

#: `map` drops out when the manifest binds the table to one map.
REQUIRED_BOUND = ("index", "at", "expect", "call")

OPTIONAL = ("script",)

COLUMNS = ("map", "index", "script", "at", "expect", "call")

SCHEMA = Schema(columns=COLUMNS, required=REQUIRED, required_bound=REQUIRED_BOUND)

#: A `DoorDesc` holds three scripts. The selector's default is the one the
#: player triggers, and so is this.
SCRIPTS = ("interact", "init", "move")
DEFAULT_SCRIPT = "interact"


@dataclass(frozen=True)
class Row:
    """One row: which door's which script, and what to patch into it."""

    map_name: str
    index: int
    at: int
    expect: str
    call: str
    line: int
    """1-based, counting comments and blank lines, so it matches an editor."""

    script: str = DEFAULT_SCRIPT

    @property
    def selector(self) -> str:
        """The `door:` selector this row means, as `mod.json` would spell it."""
        return f"door:{self.map_name}:{self.index}:{self.script}"

    def describe(self) -> str:
        return f"{self.selector} at word {self.at}: {self.expect} -> {self.call}"


@dataclass(frozen=True)
class Table:
    """One door table file's rows, and where they came from."""

    source: str
    rows: list[Row]
    map_name: str = ""


def read(path: Path, source: str = "", map_name: str = "") -> Table:
    """Read a door table from disk."""
    where = source or path.name
    return parse(text_of(path, where), where, map_name)


def parse(text: str, source: str, map_name: str = "") -> Table:
    """Read a door table from text. Raises `TableError` on anything unexpected."""
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

    return Row(
        map_name=map_of(header, record, bound, where),
        index=_count(header.cell(record, "index"), where, "index"),
        script=_script(header.cell(record, "script"), where),
        at=_count(header.cell(record, "at"), where, "at"),
        expect=_text(header.cell(record, "expect"), where, "expect"),
        call=_text(header.cell(record, "call"), where, "call"),
        line=line,
    )


def _count(text: str, where: str, column: str) -> int:
    if not text:
        raise TableError(f"{where}: '{column}' is empty; it needs a number")
    value = whole(text, where, column)
    if value < 0:
        raise TableError(f"{where}: '{column}' {value} cannot be negative")
    return value


def _text(text: str, where: str, column: str) -> str:
    if not text:
        raise TableError(f"{where}: '{column}' is empty")
    return text


def _script(text: str, where: str) -> str:
    """Which of the door's three scripts. Empty means the interact script."""
    if not text:
        return DEFAULT_SCRIPT
    lowered = text.lower()
    if lowered not in SCRIPTS:
        raise TableError(
            f"{where}: 'script' {text!r} is not one of a door's scripts. "
            f"Use one of {', '.join(SCRIPTS)}, or leave it blank for "
            f"{DEFAULT_SCRIPT!r} -- the one that runs when the player uses it."
        )
    return lowered
