"""Dump the game's own `mapData[]` table, for map id -> map name.

A map's *name* is its archive filename, which the disc gives us for free. Its
*id* is only knowable from the game: `mapData` is an array of `MapData *`
indexed by map id, and nothing on the disc records that ordering.

So this reads it out of a running game, the same way everything else here is
verified. The result is written as JSON and becomes `bleck`'s map catalog --
generated once and committed, not recomputed, because it takes a two-minute
boot and never changes for a given build.

    uv run python scripts/dump_maps.py --out bleck/backends/mapcatalog.json

⚠️ `mapData` is populated by the game's own REL prolog, very early -- long
before gameplay -- so this does not need to wait for a map to load.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingame import Session  # noqa: E402

from bleck import platforms  # noqa: E402
from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402

#: `mapData` (eu0): MAP_ID_MAX pointers to MapData.
MAP_DATA = 0x804031B8

#: spm/map_data.h
MAP_ID_MAX = 0x1D4
MAP_NAME_OFFSET = 0x00

#: Anything outside MEM1/MEM2 is not a pointer we should chase.
LOW = 0x80000000
HIGH = 0x94000000


def _read_string(dme, address: int, limit: int = 32) -> str:
    if not LOW <= address < HIGH:
        return ""
    raw = dme.read_bytes(address, limit)
    end = raw.find(b"\0")
    return raw[: end if end >= 0 else limit].decode("ascii", "replace")


def dump(dme) -> list[dict]:  # pylint: disable=container-return
    """Every populated slot of `mapData`, as {id, name}."""
    found = []
    for index in range(MAP_ID_MAX):
        pointer = dme.read_word(MAP_DATA + 4 * index)
        if not LOW <= pointer < HIGH:
            continue
        name = _read_string(dme, dme.read_word(pointer + MAP_NAME_OFFSET))
        if name:
            found.append({"id": index, "name": name})
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mod", default="map-hook", help="a built image to boot")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not image.exists():
        raise SystemExit(f"no image at {image}; build one first")
    try:
        dolphin = find_tool(platforms.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    import dolphin_memory_engine as dme

    entries: list[dict] = []
    print(f"booting {image.name} ...")
    with Session(image, dolphin) as session:
        start = time.time()
        while time.time() - start < args.seconds:
            time.sleep(3)
            if session.exited:
                break
            if not dme.is_hooked():
                dme.hook()
                continue
            try:
                entries = dump(dme)
            except RuntimeError:
                continue
            if entries:
                print(f"[t+{int(time.time() - start):>3}s] {len(entries)} maps")
                break

    if not entries:
        raise SystemExit("mapData never became readable")

    body = json.dumps({"maps": entries}, indent=1)
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"wrote {len(entries)} entries to {args.out}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
