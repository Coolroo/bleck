"""The list of maps on the disc, and what they are called.

A map's name is not written down anywhere in this toolkit — it is the name of
its archive. `files/map/aa4_01.bin` *is* the map `aa4_01`, and that is exactly
the string `mapDataPtr` takes and the one a manifest puts in `code.maps`.

So this reads the base build rather than shipping a table. The disc cannot go
stale, needs no licence, and covers whichever region is extracted; a vendored
list would manage none of those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bleck.common.errors import BleckError

#: Maps live here, one archive each.
MAP_DIR = "files/map"

MAP_SUFFIX = ".bin"

#: Names are `<area><chapter>_<number>`, e.g. `aa4_01`, `mac_01`, `dan_01`.
#: The trailing number is the room within an area.
_ROOM = re.compile(r"_\d+$")


@dataclass(frozen=True)
class MapEntry:
    """One map, as the disc names it."""

    name: str
    archive: Path

    @property
    def area(self) -> str:
        """The name with its room number removed, e.g. `aa4_01` -> `aa4`."""
        return _ROOM.sub("", self.name)

    @property
    def size(self) -> int:
        return self.archive.stat().st_size if self.archive.exists() else 0


@dataclass(frozen=True)
class AreaCount:
    """How many maps an area has. Named, because a bare pair says nothing."""

    area: str
    maps: int


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

    def areas(self) -> list[AreaCount]:
        """Areas, largest first — the shape of the game at a glance."""
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.area] = counts.get(entry.area, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [AreaCount(area=area, maps=total) for area, total in ordered]


def load(base: Path) -> MapIndex:
    """Read the map list out of an extracted build."""
    directory = base / MAP_DIR
    if not directory.is_dir():
        raise BleckError(
            f"no map directory at {directory}\n"
            f"  Extract a disc first:  bleck extract <image>"
        )
    found = [
        MapEntry(name=path.stem, archive=path)
        for path in sorted(directory.glob(f"*{MAP_SUFFIX}"))
    ]
    return MapIndex(entries=found, source=directory)
