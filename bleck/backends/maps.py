"""The list of maps on the disc, and what they are called.

A map's name is not written down anywhere in this toolkit — it is the name of
its archive. `files/map/aa4_01.bin` *is* the map `aa4_01`, and that is exactly
the string `mapDataPtr` takes and the one a manifest puts in `code.maps`.

So this reads the base build rather than shipping a table. The disc cannot go
stale, needs no licence, and covers whichever region is extracted; a vendored
list would manage none of those.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError

#: Maps live here, one archive each.
MAP_DIR = "files/map"

MAP_SUFFIX = ".bin"

#: Map ids, dumped from the game's own `mapData[]` by `scripts/dump_maps.py`.
#: Committed rather than recomputed: it needs a running emulator to produce and
#: never changes for a given build.
CATALOG = Path(__file__).with_name("mapcatalog.json")

#: Names are `<area><sublevel>_<room>`, e.g. `he1_01`. The trailing number is
#: the room; the digit before it is the sub-level, as in the game's own "1-1".
_ROOM = re.compile(r"_\d+$")
_SUBLEVEL = re.compile(r"\d+$")


@dataclass(frozen=True)
class Area:
    """A named part of the game, and the chapter it belongs to."""

    prefix: str
    label: str
    chapter: int = 0
    """0 for anything outside the eight numbered chapters."""

    @property
    def is_chapter(self) -> bool:
        return self.chapter > 0


#: ✅ The eight chapters, in `mapData[]` order, which is the game's progression
#: order. Two independent anchors fix the sequence, and the runs between them
#: are contiguous with no gaps:
#:
#:   - `he1_01_tippi_tutorial_evt` (spm-headers) -- Tippi's tutorial is 1-1,
#:     so `he` is chapter 1.
#:   - `sammerDefsCh6` in `wa1_02.h` (spm-headers) -- `wa` is chapter 6, and it
#:     holds 103 maps, matching Sammer's 100 duel rooms.
#:
#: Everything between those two is therefore fixed by position. Labels come
#: from the game's own text: `msg/UK/stg<N>.txt` names the locations, and
#: `machi.txt` (Japanese *machi*, town) is Flipside/Flopside.
#:
#: ⚠️ `sp` is **chapter 5, not "space"**. The obvious reading of the prefix is
#: wrong, and was believed here until the anchors were checked.
AREAS: list[Area] = [
    Area("he", "Lineland", 1),
    Area("mi", "Gloam Valley", 2),
    Area("ta", "The Bitlands", 3),
    Area("gn", "Outer Space", 4),
    Area("sp", "Land of the Cragnons", 5),
    Area("wa", "Sammer's Kingdom", 6),
    Area("an", "The Underwhere", 7),
    Area("ls", "Castle Bleck", 8),
    Area("mac", "Flipside / Flopside"),
    Area("dan", "Pit of 100 Trials"),
    # 🔶 Named from their contents and position, not from any citable source.
    Area("aa", "Prologue / intro"),
    Area("bos", "Boss"),
    Area("mg", "Minigames"),
    Area("tst", "Test maps"),
]

_UNKNOWN = Area("", "unknown")


@dataclass(frozen=True)
class MapEntry:
    """One map: what the disc calls it, and what the game calls it."""

    name: str
    archive: Path
    map_id: int = -1
    """Index into the game's `mapData[]`. -1 if the catalog does not list it."""

    @property
    def area(self) -> str:
        """The name with its room number removed, e.g. `he1_01` -> `he1`."""
        return _ROOM.sub("", self.name)

    @property
    def prefix(self) -> str:
        """The area on its own, e.g. `he1_01` -> `he`."""
        return _SUBLEVEL.sub("", self.area)

    @property
    def sublevel(self) -> int:
        """The game's own second number, as in chapter "3-2". 0 if absent."""
        found = _SUBLEVEL.search(self.area)
        return int(found.group()) if found else 0

    @property
    def region(self) -> Area:
        for area in AREAS:
            if area.prefix == self.prefix:
                return area
        return _UNKNOWN

    @property
    def where(self) -> str:
        """Where this map is, in words a player would recognise."""
        area = self.region
        if area.is_chapter:
            return f"Ch {area.chapter}-{self.sublevel}  {area.label}"
        return area.label

    @property
    def size(self) -> int:
        return self.archive.stat().st_size if self.archive.exists() else 0


@dataclass(frozen=True)
class AreaCount:
    """How many maps an area has. Named, because a bare pair says nothing."""

    area: str
    maps: int
    label: str = ""
    chapter: int = 0

    def describe(self) -> str:
        prefix = f"Ch {self.chapter}" if self.chapter else "   "
        return f"{self.area:<5} {prefix:<5} {self.maps:>3} maps  {self.label}"


@dataclass(frozen=True)
class MapIndex:
    """Every map on one extracted build."""

    entries: list[MapEntry]
    source: Path

    def search(self, text: str) -> list[MapEntry]:
        """Maps whose name contains `text`, case-insensitively."""
        needle = text.lower()
        return [entry for entry in self.entries if needle in entry.name.lower()]

    def find(self, name: str) -> MapEntry | None:
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def chapter(self, number: int) -> list[MapEntry]:
        """Every map in one numbered chapter, in the game's own order."""
        found = [e for e in self.entries if e.region.chapter == number]
        return sorted(found, key=lambda e: (e.sublevel, e.name))

    def areas(self) -> list[AreaCount]:
        """Areas in the game's own order — the shape of the game at a glance.

        Ordered by map id rather than by size, so the listing reads as a
        playthrough: intro, hub, chapters 1-8, then the extras.
        """
        counts: dict[str, int] = {}
        first: dict[str, int] = {}
        for position, entry in enumerate(self.entries):
            key = entry.prefix
            counts[key] = counts.get(key, 0) + 1
            ident = entry.map_id if entry.map_id >= 0 else position
            first[key] = min(first.get(key, ident), ident)
        return [
            AreaCount(
                area=prefix,
                maps=counts[prefix],
                label=next(
                    (a.label for a in AREAS if a.prefix == prefix), _UNKNOWN.label
                ),
                chapter=next((a.chapter for a in AREAS if a.prefix == prefix), 0),
            )
            for prefix in sorted(counts, key=lambda p: first[p])
        ]


def _catalog_ids() -> dict[str, int]:  # pylint: disable=container-return
    """Map name -> map id, from the committed catalog. Empty if absent."""
    if not CATALOG.is_file():
        return {}
    body = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {entry["name"]: entry["id"] for entry in body.get("maps", [])}


def load(base: Path) -> MapIndex:
    """Read the map list out of an extracted build.

    Names come from the disc, which is authoritative for what exists; ids come
    from the committed catalog, because nothing on the disc records them.
    """
    directory = base / MAP_DIR
    if not directory.is_dir():
        raise BleckError(
            f"no map directory at {directory}\n"
            f"  Extract a disc first:  bleck extract <image>"
        )
    ids = _catalog_ids()
    found = [
        MapEntry(name=path.stem, archive=path, map_id=ids.get(path.stem, -1))
        for path in sorted(directory.glob(f"*{MAP_SUFFIX}"))
    ]
    # By id where known, so listings read in the game's own progression order.
    found.sort(key=lambda e: (e.map_id if e.map_id >= 0 else 1 << 20, e.name))
    return MapIndex(entries=found, source=directory)
