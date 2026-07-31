"""Texture edits as a CSV table.

    # mods/my-mod/tables/textures.csv
    file,member,image,op,arg
    files/lyt/title.bin.uk,arc/timg/koopa.tpl,,invert,
    files/lyt/title.bin.uk,arc/timg/mario.tpl,0,tint,#8800ff

**Why this exists at all.** Every other edit in `bleck` is a declaration
rebuilt against the recipient's own disc. A texture edit was the one that
shipped as bytes — `tex-koopa` carried a modified Nintendo texture, which is
why it could not be shared, and why on a fresh clone it does nothing (its
overlay is git-ignored). A row here says what to *do* to a texture the user
already owns.

⚠️ **`file` and `member` are the pair `bleck mod vendor` already understands**,
so the addressing is not new. `member` is empty for a standalone `.tpl`.

⚠️ **`image` is optional and means "this one image".** A TPL is a container;
`effdata.tpl` holds 219. Empty means every image in it, which is what a mod
editing a single-image file wants and should not have to say.

⛔ **Only colour-map operations.** They rewrite a CMPR block's endpoints and
leave its indices untouched (D187), so the result is exact and a rebuild costs
nothing. Anything spatial, or replacing artwork outright, needs a real encoder
and is deliberately absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.formats.tables.common import (
    Header,
    Schema,
    TableError,
    split,
    text_of,
    too_wide,
)
from bleck.formats.tpl import OPERATIONS, Colour, ColourMap, brightness, tint

COLUMNS = ("file", "member", "image", "op", "arg")

#: ⚠️ A textures table is never *bound* to a map -- it addresses disc paths, not
#: maps -- so both requirement sets are the same.
REQUIRED = ("file", "op")

SCHEMA = Schema(columns=COLUMNS, required=REQUIRED, required_bound=REQUIRED)

#: Operations taking no argument.
PLAIN = ("invert", "greyscale")

#: Operations that require one, and what it looks like.
WITH_ARG = {
    "tint": "a colour like #8800ff",
    "brightness": "a number like 0.5 or 2.0",
}


class TextureRowError(TableError):
    """A row does not describe an operation that can be applied."""


@dataclass(frozen=True)
class TextureEdit:
    """One declared change to one texture."""

    disc_path: str
    member: str
    image: int | None
    """None means every image in the container."""

    operation: ColourMap
    source: str
    """Where the row was written, for error messages."""

    def describe(self) -> str:
        inside = f"/{self.member}" if self.member else ""
        which = "all images" if self.image is None else f"image {self.image}"
        return f"{self.disc_path}{inside} [{which}] {self.operation.name}"


def _colour(text: str, where: str) -> Colour:
    """`#rrggbb`, the one spelling. Accepted without the hash too."""
    cleaned = text.strip().lstrip("#")
    if len(cleaned) != 6:
        raise TextureRowError(
            f"{where}: {text!r} is not a colour. Write six hex digits, like '#8800ff'."
        )
    try:
        value = int(cleaned, 16)
    except ValueError as exc:
        raise TextureRowError(
            f"{where}: {text!r} is not a colour. Write six hex digits, like '#8800ff'."
        ) from exc
    return Colour((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def operation_of(name: str, argument: str, where: str) -> ColourMap:
    """Turn an `op` cell and its `arg` into a colour map.

    ⚠️ An operation needing an argument and given none is **refused**, never
    defaulted. A `tint` with no colour that quietly became a no-op would be a
    declared edit that does nothing and reports success -- this repo's
    most-repeated bug (D126).
    """
    key = name.strip().lower()
    if key in PLAIN:
        if argument.strip():
            raise TextureRowError(
                f"{where}: '{key}' takes no argument, but 'arg' says "
                f"{argument.strip()!r}."
            )
        return OPERATIONS[key]

    if key not in WITH_ARG:
        known = ", ".join(sorted((*PLAIN, *WITH_ARG)))
        raise TextureRowError(f"{where}: unknown operation {name!r}. Known: {known}.")

    if not argument.strip():
        raise TextureRowError(f"{where}: '{key}' needs {WITH_ARG[key]} in 'arg'.")

    if key == "tint":
        return tint(_colour(argument, where))

    try:
        factor = float(argument)
    except ValueError as exc:
        raise TextureRowError(f"{where}: 'brightness' needs {WITH_ARG[key]}.") from exc
    return brightness(factor)


def _image_index(cell: str, where: str) -> int | None:
    text = cell.strip()
    if not text:
        return None
    try:
        index = int(text, 0)
    except ValueError as exc:
        raise TextureRowError(
            f"{where}: 'image' must be a number or empty for every image."
        ) from exc
    if index < 0:
        raise TextureRowError(f"{where}: 'image' cannot be negative.")
    return index


@dataclass(frozen=True)
class Table:
    """One textures table file's rows, and where they came from."""

    source: str
    edits: list[TextureEdit]


def read(path: Path, source: str = "") -> Table:
    where = source or path.name
    return parse(text_of(path, where), where)


def parse(text: str, source: str) -> Table:
    """Read a textures table. Every row is validated; none is skipped."""
    body = split(text, source, SCHEMA, "")
    return Table(
        source=source,
        edits=[
            _edit(body.header, record, f"{source}:{line.number}")
            for line, record in body.numbered()
        ],
    )


def _edit(header: Header, record: list[str], where: str) -> TextureEdit:
    too_wide(header, record, where)
    disc_path = header.cell(record, "file").strip()
    if not disc_path:
        raise TextureRowError(f"{where}: 'file' is required.")
    return TextureEdit(
        disc_path=disc_path,
        member=header.cell(record, "member").strip(),
        image=_image_index(header.cell(record, "image"), where),
        operation=operation_of(
            header.cell(record, "op"), header.cell(record, "arg"), where
        ),
        source=where,
    )
