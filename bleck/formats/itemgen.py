"""Render `bleck/formats/itemids.py` from the item table. Generation, not runtime.

Nothing in a normal `bleck` run calls this: it exists so that `ItemId` is
*derived* from the game's own constants rather than typed out, and so that one
renderer answers both "write the module" and "is the committed module still
right".

It lives in the package rather than in `scripts/` for a concrete reason: the
drift guard in `tests/test_items.py` has to call the **same** renderer
`scripts/dump_items.py` calls, and `dump_items.py` cannot be imported at all on
Linux -- it imports `scripts/ingame.py`, which imports `scripts/keys.py`, which
imports `ctypes.wintypes`, and that module raises on any non-Windows host.

⚠️ **Nothing here may import `bleck.formats.items`**, tempting though its
`ENUM_PREFIX` is. `items` imports the generated module, so an import edge back
this way makes the generator unimportable exactly when `itemids.py` is missing
or broken -- which is when it is needed.

⚠️ The output must be byte-for-byte what `ruff format` would produce. `bleck` is
a lint target, so `scripts/lint.py --fix` reformats the committed module in
place, and any disagreement shows up as a drift-guard failure with no obvious
cause.
"""

from __future__ import annotations

import keyword
from dataclasses import dataclass

#: The same string as `items.ENUM_PREFIX`, deliberately not imported -- see the
#: module docstring. Every constant in `item_data_ids.h` carries it, and a
#: member name is what is left after it.
ENUM_PREFIX = "ITEM_ID_"

#: Names `Enum` itself owns. A member called `name` or `value` would shadow the
#: property that reads it, and `_sunder_` names are reserved by the enum
#: machinery outright.
RESERVED = frozenset({"name", "value", "mro"})


class GenerationError(Exception):
    """The catalog cannot become a valid enum, so no module is written.

    Raised rather than warned: a silently aliased member would make two
    different items the same object, and every lookup after it would be wrong
    in a way no test downstream could attribute.
    """


@dataclass(frozen=True)
class EnumMember:
    """One line of the generated class body."""

    name: str
    """The `ITEM_ID_*` constant without its prefix, e.g. `USE_HONOO_SAKURETU`."""

    value: int
    """The item's id: its position in `itemDataTable`."""


def member_name(constant: str) -> str:
    """The member name a constant becomes. `ITEM_ID_NULL` -> `NULL`."""
    return constant.removeprefix(ENUM_PREFIX)


def from_constants(constants: dict[int, str]) -> list[EnumMember]:
    """Members from `dump_items.enum_names` output: id -> `ITEM_ID_*`."""
    return [
        EnumMember(name=member_name(constant), value=item_id)
        for item_id, constant in sorted(constants.items())
    ]


def from_catalog(rows: list[dict]) -> list[EnumMember]:
    """Members from `itemcatalog.json`'s `items` array.

    The same projection as `from_constants`, from the other artifact the dump
    writes. That both exist is what lets a test regenerate the module in a
    clone that has no spm-headers checkout.
    """
    return [
        EnumMember(name=member_name(str(row.get("enum", ""))), value=int(row["id"]))
        for row in sorted(rows, key=lambda row: int(row["id"]))
    ]


def check(members: list[EnumMember]) -> None:
    """Refuse anything that would not be 1:1. Raises `GenerationError`."""
    if not members:
        raise GenerationError("no members: an empty ItemId would resolve nothing")

    seen_names: dict[str, int] = {}
    seen_values: dict[int, str] = {}
    for member in members:
        if not member.name.isidentifier() or keyword.iskeyword(member.name):
            raise GenerationError(
                f"{member.name!r} (id {member.value}) is not a valid Python "
                f"identifier, so it cannot be an enum member"
            )
        if member.name.startswith("_"):
            raise GenerationError(
                f"{member.name!r} (id {member.value}) starts with an underscore; "
                f"Enum reserves those names"
            )
        if member.name in RESERVED:
            raise GenerationError(
                f"{member.name!r} (id {member.value}) shadows Enum's own {member.name!r}"
            )
        if member.name in seen_names:
            raise GenerationError(
                f"{member.name!r} names both id {seen_names[member.name]} and id "
                f"{member.value}; the second would silently become an alias of "
                f"the first"
            )
        if member.value in seen_values:
            raise GenerationError(
                f"id {member.value} is named both {seen_values[member.value]!r} "
                f"and {member.name!r}; the second would silently become an alias"
            )
        seen_names[member.name] = member.value
        seen_values[member.value] = member.name


#: ⚠️ Two details of this template are load-bearing, and both were pylint
#: failures first (D119):
#:
#: - the generated docstring is **raw**, so the `\` continuations in the
#:   regeneration command stay shell continuations. In a normal docstring
#:   Python would read each one as a line continuation and eat the newline,
#:   and writing the command on one line trips `line-too-long` instead.
#: - `invalid-name` is disabled for the file. `ITEM_ID_WORLD_COIN_x3` really
#:   is spelled with a lowercase `x` in `item_data_ids.h` (D114), and a member
#:   must be its constant exactly -- "correcting" it would break the 1:1 that
#:   makes the enum checkable against the header.
_HEADER = r'''r"""Every id in `itemDataTable`, by name. **Generated -- do not edit.**

A member name is the `ITEM_ID_*` constant from spm-headers' `item_data_ids.h`
with its prefix stripped, and its value is the item's id -- which is its
position in the table (D114). This module is data; the names that resolve to it
live in `bleck/formats/items.py` (D119).

Regenerate it, and `itemcatalog.json` beside it, with:

    uv run python scripts/dump_items.py \
        --out bleck/formats/itemcatalog.json \
        --enum-out bleck/formats/itemids.py \
        --headers work/upstream/spm-headers/include/spm/item_data_ids.h

⚠️ A member is an `int`. `f"{ItemId.NULL}"` is `"0"`, not `"NULL"`, and
`ItemId.NULL` is **falsy** -- test presence with `is not None` and print
`.name`.
"""

from __future__ import annotations

from enum import IntEnum

# `WORLD_COIN_x3` is the header's own spelling, and a member must match it.
# pylint: disable=invalid-name


class ItemId(IntEnum):
    """An item the game has, named after its `ITEM_ID_*` constant."""
'''


def render(members: list[EnumMember]) -> str:
    """The text of `itemids.py`. Checked first: a broken module is never written."""
    check(members)
    body = "\n".join(f"    {member.name} = {member.value}" for member in members)
    return f"{_HEADER}\n{body}\n"
