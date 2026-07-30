"""Dump every map's doors, for `bleck doors <map>` and for build-time checks.

A `door:` selector's index is a **position in the array a map registers**, not
an id and nothing visible in game (D103). Until now the only way to learn a
map's count was to guess and read a status word at run time — which is how
a since-deleted probe came to carry a `door:he1_01:9` patch that addressed
nothing (D137).

⚠️ **A map has TWO door tables and they are not interchangeable** (D138):

    DoorDesc     0x58  interact/init/move scripts.  `door:` reaches these
    MapDoorDesc  0x20  destMapName/destDoorName.    NO scripts at all

Reporting only the first makes a map look emptier than it is; reporting them
together is the point.

    uv run python scripts/dump_doors.py --out bleck/backends/doorcatalog.json

Read from a running game rather than the disc because the descriptor arrays are
reached through `MapData.initScript`, whose address is a constant *inside* the
init script's bytecode. `mapDataPtr` is populated by the REL prolog for every
map, loaded or not (D88), so one boot covers the whole game — no per-map load.
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
MAP_ID_MAX = 0x1D4
MAP_NAME = 0x00
MAP_INIT_SCRIPT = 0x18

#: The two setters, from the eu0 symbol list.
SET_DOOR_DESCS = 0x800E2610
SET_MAP_DOOR_DESCS = 0x800E4118

#: `evt_door_set_event(door, which, script)` -- attaches a script to a LOADING
#: ZONE, which has no script fields of its own. Recorded per map so "can a mod
#: use this" is answerable from the catalog rather than by guessing (D143).
SET_EVENT = 0x800E45C8

#: `DoorDesc`, 0x58 (spm-headers `evt_door.h`, MIT).
DOORDESC_SIZE = 0x58
DOOR_NAME = 0x0C
DOOR_MAPGRP = 0x2C
DOOR_INTERACT = 0x40
DOOR_INIT = 0x50
DOOR_MOVE = 0x54

#: `MapDoorDesc`, 0x20.
MAPDOOR_SIZE = 0x20
MAPDOOR_NAME_L = 0x04
MAPDOOR_DEST_MAP = 0x14
MAPDOOR_DEST_DOOR = 0x18

EVT_USER_FUNC = 0x5C
EVT_END_SCRIPT = 0x01
EVT_MAX_OPCODE = 0x77
EVT_MAX_ARGC = 16

#: An init script that has not ended by here has desynced; stop rather than
#: walk into unrelated memory. D93 nearly recorded a truncated walk as a finding.
WALK_LIMIT = 4096

#: Anything outside MEM1/MEM2 is not a pointer worth chasing.
LOW = 0x80000000
HIGH = 0x94000000

#: A descriptor count this large means the read landed on something that is not
#: a table. The game's own assert caps door descs at 16 (`evt_door.c:1944`).
SANE_COUNT = 64


def _string(dme, address: int, limit: int = 32) -> str:
    if not LOW <= address < HIGH:
        return ""
    raw = dme.read_bytes(address, limit)
    end = raw.find(b"\0")
    return raw[: end if end >= 0 else limit].decode("ascii", "replace")


def _setter_arrays(dme, script: int) -> dict:  # pylint: disable=container-return
    """Walk an init script, collecting each door setter's (array, count).

    ⚠️ Matched on the **function pointer**, not a header word. The door setter's
    argc was measured at 3 against a header declaring 1 (D102), so assuming an
    argc would repeat that mistake.
    """
    found: dict[int, dict] = {}
    at = 0
    while at < WALK_LIMIT:
        try:
            header = dme.read_word(script + at * 4)
        except (RuntimeError, OSError):
            return found
        argc, opcode = header >> 16, header & 0xFFFF
        if opcode == EVT_END_SCRIPT:
            return found
        if opcode > EVT_MAX_OPCODE or argc > EVT_MAX_ARGC:
            return found
        if opcode == EVT_USER_FUNC and argc >= 3:
            target = dme.read_word(script + (at + 1) * 4)
            if target == SET_EVENT:
                found[SET_EVENT] = {"array": 0, "count": found.get(
                    SET_EVENT, {"count": 0})["count"] + 1}
            if target in (SET_DOOR_DESCS, SET_MAP_DOOR_DESCS):
                found[target] = {
                    "array": dme.read_word(script + (at + 2) * 4),
                    "count": dme.read_word(script + (at + 3) * 4),
                }
        at += 1 + argc
    return found


def _doors(dme, array: int, count: int) -> list[dict]:  # pylint: disable=container-return
    out = []
    for index in range(count):
        desc = array + index * DOORDESC_SIZE
        out.append(
            {
                "index": index,
                "name": _string(dme, dme.read_word(desc + DOOR_NAME)),
                "group": _string(dme, dme.read_word(desc + DOOR_MAPGRP)),
                "scripts": {
                    "interact": dme.read_word(desc + DOOR_INTERACT) != 0,
                    "init": dme.read_word(desc + DOOR_INIT) != 0,
                    "move": dme.read_word(desc + DOOR_MOVE) != 0,
                },
            }
        )
    return out


def _zones(dme, array: int, count: int) -> list[dict]:  # pylint: disable=container-return
    out = []
    for index in range(count):
        desc = array + index * MAPDOOR_SIZE
        out.append(
            {
                "index": index,
                "name": _string(dme, dme.read_word(desc + MAPDOOR_NAME_L)),
                "to_map": _string(dme, dme.read_word(desc + MAPDOOR_DEST_MAP)),
                "to_door": _string(dme, dme.read_word(desc + MAPDOOR_DEST_DOOR)),
            }
        )
    return out


def dump(dme) -> list[dict]:  # pylint: disable=container-return
    """Every map that registers a door of either kind."""
    found = []
    for index in range(MAP_ID_MAX):
        pointer = dme.read_word(MAP_DATA + 4 * index)
        if not LOW <= pointer < HIGH:
            continue
        name = _string(dme, dme.read_word(pointer + MAP_NAME))
        script = dme.read_word(pointer + MAP_INIT_SCRIPT)
        if not name or not LOW <= script < HIGH:
            continue

        arrays = _setter_arrays(dme, script)
        doors: list[dict] = []
        zones: list[dict] = []
        for target, entry in arrays.items():
            array, count = entry["array"], entry["count"]
            if not LOW <= array < HIGH or not 0 < count <= SANE_COUNT:
                continue
            if target == SET_DOOR_DESCS:
                doors = _doors(dme, array, count)
            else:
                zones = _zones(dme, array, count)
        events = arrays.get(SET_EVENT, {}).get("count", 0)
        if doors or zones:
            found.append(
                {"map": name, "doors": doors, "zones": zones, "zone_events": events}
            )
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mod", default="nop", help="a built image to boot")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not image.exists():
        raise SystemExit(f"no image at {image}; build one first")
    try:
        dolphin = find_tool(platforms.ToolKey.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    import dolphin_memory_engine as dme  # pylint: disable=import-outside-toplevel

    found: list[dict] = []
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
                found = dump(dme)
            except RuntimeError:
                continue
            # `mapData` is filled by the REL prolog, so this settles early --
            # stop as soon as it is populated rather than waiting out the clock.
            if found:
                print(f"[t+{int(time.time() - start):>3}s] {len(found)} map(s)")
                break

    if not found:
        raise SystemExit("mapData never became readable")

    body = {
        "attribution": (
            "Door descriptors read from a running game. Struct layouts from "
            "SeekyCt/spm-headers (MIT); see THIRD-PARTY-NOTICES.md."
        ),
        "maps": found,
    }
    text = json.dumps(body, indent=1) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        doors = sum(len(m["doors"]) for m in found)
        zones = sum(len(m["zones"]) for m in found)
        print(f"{len(found)} map(s), {doors} door(s), {zones} zone(s) -> {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
