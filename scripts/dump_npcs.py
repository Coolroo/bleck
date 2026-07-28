"""Dump the game's NPC template and tribe tables, so setup entries can be named.

A setup entry says `type 250`. That is an index into `npcEnemyTemplates`, and
nothing on the disc says what template 250 *is* — the names live in the game's
own tables, behind pointers, so they only exist at runtime.

So this reads them out of a running game, the same way `dump_maps.py` does, and
writes a catalog that is committed rather than recomputed.

    uv run python scripts/dump_npcs.py --out bleck/formats/npccatalog.json

⚠️ A setup entry's `type` is a **template** index, not an `NPC_*` constant from
`npcdrv.h` — those are *tribe* ids. There are 435 templates and 535 tribes, and
a template points at its tribe. Both are dumped here so the chain
`setup.type -> template.tribeId -> tribe.animPoseName` can be followed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402
from bleck import platforms  # noqa: E402

from ingame import Session  # noqa: E402

#: eu0. Both structs are 0x68 bytes (spm-headers, npcdrv.h).
TEMPLATES = 0x80449888
TEMPLATE_COUNT = 435
TRIBES = 0x8043BF30
TRIBE_COUNT = 535
STRUCT_SIZE = 0x68

#: NPCEnemyTemplate
#: A per-template gate. If it returns false the enemy does not spawn, which is
#: one candidate explanation for a declared enemy simply not appearing.
TEMPLATE_CAN_SPAWN = 0x0C
TEMPLATE_FLAGS = 0x2C
TEMPLATE_TRIBE_ID = 0x14
TEMPLATE_INSTANCE_NAME = 0x18
TEMPLATE_JAPANESE_NAME = 0x1C

#: NPCTribe. The internal model name, e.g. "kuribo".
TRIBE_ANIM_POSE_NAME = 0x00

LOW = 0x80000000
HIGH = 0x94000000


#: ⚠️ Scoped to `enum NPCTribeId` deliberately. `npcdrv.h` has other `NPC_`
#: prefixed enums -- `NPCMoveMode` starts at `NPC_MOVE_WALK_NO_HIT = 0` -- and a
#: bare `NPC_(\w+) = (\d+)` sweeps those up too, silently overwriting tribe 0's
#: name with "Move Walk No Hit" instead of "Goomba". Caught only because Goomba
#: was recognisable; a subtler collision would have shipped.
_BLOCK = re.compile(r"enum\s+NPCTribeId\s*\{(.*?)\n\}", re.DOTALL)
_MEMBER = re.compile(r"^\s*NPC_([A-Z0-9_]+)\s*=\s*(\d+)", re.MULTILINE)


def english_names(header: Path) -> dict:  # pylint: disable=container-return
    """Tribe id -> English name, parsed from spm-headers' `npcdrv.h`."""
    block = _BLOCK.search(header.read_text(encoding="utf-8"))
    if not block:
        raise SystemExit(f"no `enum NPCTribeId` in {header}; has it been renamed?")
    return {
        int(value): name.replace("_", " ").title()
        for name, value in _MEMBER.findall(block.group(1))
    }


def _string(dme, pointer: int, limit: int = 48) -> str:
    if not LOW <= pointer < HIGH:
        return ""
    try:
        raw = dme.read_bytes(pointer, limit)
    except RuntimeError:
        return ""
    end = raw.find(b"\0")
    raw = raw[: end if end >= 0 else limit]
    # Model names are ASCII; the Japanese debug names are Shift-JIS. Try the
    # strict reading first, so a mangled decode never silently wins.
    for encoding in ("ascii", "shift_jis"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("ascii", "replace").strip()


def dump(dme) -> dict:  # pylint: disable=container-return
    templates = []
    for index in range(TEMPLATE_COUNT):
        at = TEMPLATES + index * STRUCT_SIZE
        entry = {
            "id": index,
            "tribe": dme.read_word(at + TEMPLATE_TRIBE_ID),
            "can_spawn": dme.read_word(at + TEMPLATE_CAN_SPAWN),
            "flags": dme.read_word(at + TEMPLATE_FLAGS),
            "name": _string(dme, dme.read_word(at + TEMPLATE_INSTANCE_NAME)),
            "japanese": _string(dme, dme.read_word(at + TEMPLATE_JAPANESE_NAME)),
        }
        if entry["tribe"] >= 0x80000000:  # unsigned read of a negative s32
            entry["tribe"] -= 0x100000000
        templates.append(entry)

    tribes = [
        {
            "id": index,
            "name": _string(
                dme,
                dme.read_word(TRIBES + index * STRUCT_SIZE + TRIBE_ANIM_POSE_NAME),
            ),
        }
        for index in range(TRIBE_COUNT)
    ]
    return {"templates": templates, "tribes": tribes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mod", default="map-hook", help="a built image to boot")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument(
        "--headers",
        help="path to spm-headers/include/spm/npcdrv.h, to merge English names",
    )
    args = parser.parse_args()

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not image.exists():
        raise SystemExit(f"no image at {image}; build one first")
    try:
        dolphin = find_tool(platforms.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    import dolphin_memory_engine as dme  # noqa: PLC0415

    tables = None
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
                tables = dump(dme)
            except RuntimeError:
                continue
            named = sum(1 for t in tables["tribes"] if t["name"])
            if named:
                print(
                    f"[t+{int(time.time() - start):>3}s] "
                    f"{len(tables['templates'])} templates, {named} named tribes"
                )
                break

    if not tables or not any(t["name"] for t in tables["tribes"]):
        raise SystemExit("the NPC tables never became readable")

    if args.headers:
        names = english_names(Path(args.headers))
        for tribe in tables["tribes"]:
            tribe["english"] = names.get(tribe["id"], "")
        print(f"merged {sum(1 for t in tables['tribes'] if t['english'])} English names")

    tables["attribution"] = (
        "Table addresses and field offsets from SeekyCt/spm-headers "
        "(npcdrv.h), MIT licensed. Values read from a running game; "
        "regenerate with scripts/dump_npcs.py."
    )
    body = json.dumps(tables, indent=1)
    if args.out:
        Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(body[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
