"""How many coins a map is allowed to have, read out of the game's own DOL.

A coin is *persistent* -- collect it and it must stay collected -- so each one
owns a bit in the save file. `swdrv` allocates those from a fixed per-map budget,
and **overflowing it hangs the game** rather than dropping the coin (D130):

    swdrv.c:505   (wp->gameCoinId - 1) < assign_tbl[i].num
                  コインのフラグが溢れました   "the coin flags have overflowed"

⚠️ **The budget counts coins the setup file cannot see.** Coins inside blocks are
map objects and never appear in `setup/*.dat`, yet they draw on the same pool.
`he1_01` has a budget of 4, ships no setup items, and still refused one coin --
its blocks had already taken all four.

⚠️ **A map absent from the table is not out of luck.** The allocator returns -1
rather than asserting, and the collected-check reads -1 as "not collected", so
the coin spawns. 204 of the 227 maps with a setup file are in that position
(D133). 🔶 What is *not* established is whether such a coin stays collected: -1
has nowhere to record it, so it may well reappear on every map load.

Read from the DOL rather than committed, for the same reason the hook guard word
is (D95): the address is version-specific, and a table baked into `bleck` would
silently describe the wrong build.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

from bleck.backends import dol as dolfile

#: `assign_tbl` in `eu0`, found by cross-referencing the `swdrv.c` assert
#: (D128, D130). ⚠️ eu0 only -- another build puts it elsewhere.
ASSIGN_TBL = 0x80326178

#: `{const char *map, s32 num}`.
ENTRY_SIZE = 8
ENTRIES = 32

#: Longest name to read before giving up on a garbage pointer.
_NAME_LIMIT = 16

#: What a map name looks like on this disc, e.g. `he1_01`, `mac_02`.
_MAP_NAME = re.compile(r"^[a-z]{2,4}\d?_\d{2}$")

#: A budget this big means the read landed on something that is not the table.
_SANE_MAX = 4096


@dataclass(frozen=True)
class CoinBudget:
    """One map's coin-flag allowance."""

    map_name: str
    flags: int


@dataclass(frozen=True)
class CoinBudgets:
    """Every map the game reserves coin flags for.

    Empty when the table could not be read -- a different game version, a DOL
    that is not there. **Callers must treat empty as "unknown", never as "no map
    has a budget"**, or a build would cheerfully produce a disc that hangs.
    """

    entries: list[CoinBudget]

    def __bool__(self) -> bool:
        return bool(self.entries)

    def find(self, map_name: str) -> CoinBudget | None:
        """The map's budget, or `None` when it has no entry at all -- which is
        the common case and does *not* mean zero."""
        for entry in self.entries:
            if entry.map_name == map_name:
                return entry
        return None


def read(dol_path: Path) -> CoinBudgets:
    """Read `assign_tbl` from a DOL. Empty on anything unexpected."""
    if not dol_path.is_file():
        return CoinBudgets(entries=[])
    try:
        raw = dol_path.read_bytes()
        image = dolfile.parse(raw, dol_path)
    except Exception:  # pylint: disable=broad-except
        # A DOL this cannot parse is a "do not know" answer, not a crash: the
        # caller falls back to refusing, which is the safe direction.
        return CoinBudgets(entries=[])

    found: list[CoinBudget] = []
    for index in range(ENTRIES):
        row = _at(image, raw, ASSIGN_TBL + index * ENTRY_SIZE, ENTRY_SIZE)
        if row is None:
            return CoinBudgets(entries=[])
        pointer, count = struct.unpack(">Ii", row)
        name = _name(image, raw, pointer)
        if not name or not 0 <= count <= _SANE_MAX:
            return CoinBudgets(entries=[])
        found.append(CoinBudget(map_name=name, flags=count))
    return CoinBudgets(entries=found)


def _at(image, raw: bytes, address: int, size: int) -> bytes | None:
    for section in image.sections:
        if section.size and section.address <= address < section.address + section.size:
            offset = section.offset + (address - section.address)
            return raw[offset : offset + size]
    return None


def _name(image, raw: bytes, address: int) -> str:
    """A map name at `address`, or empty if it does not look like one.

    The shape check is the guard against a wrong `ASSIGN_TBL`: reading 32 plausible
    map names out of an arbitrary address does not happen by accident.
    """
    blob = _at(image, raw, address, _NAME_LIMIT)
    if blob is None:
        return ""
    text = blob.split(b"\x00")[0].decode("ascii", errors="replace")
    return text if _MAP_NAME.match(text) else ""
