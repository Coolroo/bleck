"""Read the animation driver's live pose table out of a running game.

    uv run python scripts/dump_anim.py --mod nop --seconds 120

Answers one question: does the game's own animation state *change* between
frames for a model whose clips `bleck` reads as holding a single pose? The
export writes one morph target at constant weight for 67 models (673 clips),
which is faithful to the file only if a zero-length track really is a hold
(D252). Nothing has ever checked that reading against the game.

⚠️ **Reads only, and no hook.** The layout below is read out of
`animPoseGetAnimPosePtr` (`0x8004c660`) and `animPoseGetAnimBaseDataPtr`
(`0x8004c828`), which index the table in the clear, so no handler prototype has
to be guessed and nothing is patched. `animGetPtr` at `0x8004158c` is two
instructions and names the global outright.

⚠️ **A field that never changes is the finding**, so the sampler reports which
byte offsets moved between samples rather than only their values -- a table
read once cannot tell a static pose from a stationary one.
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from ingame import Session  # noqa: E402

from bleck import platforms  # noqa: E402
from bleck.backends.disc import DiscError, find_tool  # noqa: E402
from bleck.mods import registry  # noqa: E402

#: `animGetPtr` is `lwz r3,-32680(r13); blr`, and r13 is `0x805B5F00` (D218),
#: so the animation driver's work pointer lives here.
ANIMDRV_WP = 0x805ADF58

#: The work struct, as both accessors index it.
BASE_TABLE_AT = 0x00
POSE_ARRAY_AT = 0x10
POSE_COUNT_AT = 0x14

#: One `AnimPose`. `mulli r31,r30,392` gives the stride; `clrlwi. r0,r0,31`
#: tests bit 0 of the first word, and the assert fires when it is clear.
POSE_STRIDE = 392
POSE_FLAGS_AT = 0x00
POSE_BASE_INDEX_AT = 0x10

#: `animPoseGetAnimBaseDataPtr` computes `wp[0x00] + entry[0x10] * 16`.
BASE_STRIDE = 16

#: The base record's third word points at a loader record, which carries the
#: model's **disc path** here as `a/<name>` -- measured, by dumping the record.
#: ⚠️ Not the model file's own `+0x04` name; this is the path it was loaded by.
LOADER_PATH_AT = 0x20

#: Where `animPoseMain` copies the model's slot 20 to, and the sibling copies
#: that fix the stride. ✅ Read at `0x80045744`: `lwz r4,416(r28)` is slot 20
#: (`0x150 + 20*4`), `r5` is the count with **no size multiplier**, so one byte
#: an element, and the destination is `r29 + 0x60`.
#:
#: ⚠️ **The copy is the point.** The file's flag is an *initial* state the game
#: then owns and may change; reading it here is the only way to see what is
#: actually drawn.
POSE_VISIBILITY_AT = 0x60

LOW = 0x80000000
HIGH = 0x94000000


def _valid(pointer: int) -> bool:
    return LOW <= pointer < HIGH


def _string(dme, pointer: int, limit: int = 48) -> str:
    """A NUL-terminated ASCII name, or empty when the pointer is not one."""
    if not _valid(pointer):
        return ""
    try:
        raw = dme.read_bytes(pointer, limit)
    except RuntimeError:
        return ""
    end = raw.find(b"\0")
    raw = raw[: end if end >= 0 else limit]
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        return ""


@dataclass(frozen=True)
class Pose:
    """One live `AnimPose`: where it sits, and the bytes it held when read."""

    index: int
    at: int
    base_index: int
    name: str
    raw: bytes
    base_raw: bytes = b""
    #: The live per-node visibility bytes, read through the pose's own pointer.
    visibility: bytes = b""
    blob: bytes = b""
    blob_at: int = 0


@dataclass(frozen=True)
class Sample:
    """Every in-use pose at one instant, plus the table that produced them."""

    count: int
    poses: list = field(default_factory=list)  # pylint: disable=container-return


@dataclass(frozen=True)
class Named:
    """A model name, the record it was read out of, and what it pointed at."""

    name: str
    raw: bytes = b""
    blob: bytes = b""
    blob_at: int = 0


def _name_for(dme, base_table: int, base_index: int) -> Named:
    """The model name behind a pose, via the 16-byte base-data record.

    ⚠️ **Two hops, and the second was measured rather than guessed.** The
    record's third word points at a loader record whose `+0x20` holds the disc
    path, `a/p_wii_mario`. Six probe offsets on the pointer itself all returned
    nothing, which read as "the table has no names" until the bytes were dumped.
    """
    record = base_table + base_index * BASE_STRIDE
    if not _valid(record):
        return Named(name="")
    try:
        raw = dme.read_bytes(record, BASE_STRIDE)
    except RuntimeError:
        return Named(name="")
    blob, blob_at = b"", 0
    for offset in range(0, BASE_STRIDE, 4):
        word = int.from_bytes(raw[offset : offset + 4], "big")
        if not _valid(word):
            continue
        if not blob:
            try:
                blob, blob_at = dme.read_bytes(word, 0x60), word
            except RuntimeError:
                blob = b""
        found = _string(dme, word + LOADER_PATH_AT)
        if found and found.isprintable() and len(found) >= 3:
            return Named(name=found, raw=raw, blob=blob, blob_at=blob_at)
    return Named(name="", raw=raw, blob=blob, blob_at=blob_at)



def _visibility(dme, raw: bytes) -> bytes:
    """The pose's live copy of slot 20, through the pointer at `+0x60`.

    ⚠️ The length is not stored beside the pointer, so a fixed window is read
    and the caller compares it against the model's own node count. Reading too
    far is harmless -- the bytes past the end are simply not 0 or 1.
    """
    at = int.from_bytes(raw[POSE_VISIBILITY_AT : POSE_VISIBILITY_AT + 4], "big")
    if not _valid(at):
        return b""
    try:
        found = dme.read_bytes(at, 512)
    except RuntimeError:
        return b""
    end = 0
    while end < len(found) and found[end] in (0, 1):
        end += 1
    return found[:end]


def sample(dme) -> Sample:
    """Every in-use pose in the driver's table, right now."""
    work = dme.read_word(ANIMDRV_WP)
    if not _valid(work):
        return Sample(count=0)
    base_table = dme.read_word(work + BASE_TABLE_AT)
    array = dme.read_word(work + POSE_ARRAY_AT)
    count = dme.read_word(work + POSE_COUNT_AT)
    if not _valid(array) or not 0 < count < 4096:
        return Sample(count=0)

    found = []
    for index in range(count):
        at = array + index * POSE_STRIDE
        try:
            raw = dme.read_bytes(at, POSE_STRIDE)
        except RuntimeError:
            continue
        flags = int.from_bytes(raw[POSE_FLAGS_AT : POSE_FLAGS_AT + 4], "big")
        if not flags & 1:
            continue
        base_index = int.from_bytes(
            raw[POSE_BASE_INDEX_AT : POSE_BASE_INDEX_AT + 4], "big"
        )
        named = _name_for(dme, base_table, base_index)
        seen = _visibility(dme, raw)
        found.append(
            Pose(
                index=index,
                at=at,
                base_index=base_index,
                name=named.name,
                raw=raw,
                base_raw=named.raw,
                blob=named.blob,
                blob_at=named.blob_at,
                visibility=seen,
            )
        )
    return Sample(count=count, poses=found)


def _moved(first: bytes, second: bytes) -> list:  # pylint: disable=container-return
    """Which word offsets differ between two readings of one pose."""
    return [
        offset
        for offset in range(0, POSE_STRIDE, 4)
        if first[offset : offset + 4] != second[offset : offset + 4]
    ]


def report(samples: list) -> None:
    """What changed, per pose, across every sample taken."""
    if len(samples) < 2:
        print("fewer than two samples; nothing to compare")
        return
    first = {pose.index: pose for pose in samples[0].poses}
    last = {pose.index: pose for pose in samples[-1].poses}
    shared = sorted(set(first) & set(last))
    print(f"\n{len(shared)} pose(s) present in both the first and last sample")
    print(f"{'slot':>5} {'base':>5}  {'name':<22} {'words changed':>14}  offsets")
    print("-" * 78)
    for index in shared:
        moved = _moved(first[index].raw, last[index].raw)
        shown = " ".join(f"0x{offset:03x}" for offset in moved[:12])
        extra = f" (+{len(moved) - 12} more)" if len(moved) > 12 else ""
        print(
            f"{index:>5} {first[index].base_index:>5}  "
            f"{first[index].name[:21]:<22} {len(moved):>14}  {shown}{extra}"
        )
    still = [i for i in shared if not _moved(first[i].raw, last[i].raw)]
    print(
        f"\n{len(shared) - len(still)} of {len(shared)} pose(s) changed; "
        f"{len(still)} identical across the whole run"
    )
    print("\nbase-data record, and 0x60 at the first pointer it carries:")
    for index in shared[:4]:
        pose = first[index]
        print(f"  slot {index} base {pose.base_index}: {pose.base_raw.hex(' ')}")
        for line in range(0, len(pose.blob), 16):
            chunk = pose.blob[line : line + 16]
            text = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            print(f"    {pose.blob_at + line:08x}  {chunk.hex(' '):<47}  {text}")
    print("\nthe live visibility array at pose +0x60 (slot 20, after the copy):")
    for index in shared:
        pose = first[index]
        if not pose.visibility:
            continue
        off = [at for at, byte in enumerate(pose.visibility) if byte == 0]
        print(
            f"  slot {index} {pose.name or '(unnamed)'}: "
            f"{len(pose.visibility)} byte(s), {len(off)} off"
        )
        print(f"    off at: {off[:24]}")

    print("\nwhat moved, first sample -> last (u32, then the same bits as f32):")
    for index in shared:
        moved = _moved(first[index].raw, last[index].raw)
        if not moved:
            continue
        print(f"  slot {index} {first[index].name or '(unnamed)'}")
        for offset in moved:
            before = first[index].raw[offset : offset + 4]
            after = last[index].raw[offset : offset + 4]
            print(
                f"    +{offset:03x}  {before.hex()} -> {after.hex()}   "
                f"{struct.unpack('>f', before)[0]:>14.4f} -> "
                f"{struct.unpack('>f', after)[0]:.4f}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mod", default="nop", help="a built image to boot")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--gap", type=float, default=1.0, help="seconds between samples")
    parser.add_argument(
        "--after",
        type=float,
        default=50.0,
        help="wait this long before the first sample; gameplay is reached ~45s in",
    )
    args = parser.parse_args()

    image = registry.build_root() / f"{args.mod}.wbfs"
    if not image.exists():
        raise SystemExit(f"no image at {image}; build one first")
    try:
        dolphin = find_tool(platforms.ToolKey.DOLPHIN)
    except DiscError as exc:
        raise SystemExit(str(exc)) from exc

    import dolphin_memory_engine as dme  # noqa: PLC0415

    taken: list = []
    print(f"booting {image.name} ...")
    with Session(image, dolphin) as session:
        start = time.time()
        while time.time() - start < args.seconds and len(taken) < args.samples:
            time.sleep(args.gap if taken else 3.0)
            if session.exited:
                print("dolphin exited on its own")
                break
            if not dme.is_hooked():
                dme.hook()
                continue
            if not taken and time.time() - start < args.after:
                continue
            try:
                here = sample(dme)
            except RuntimeError:
                continue
            if not here.poses:
                continue
            taken.append(here)
            names = sum(1 for pose in here.poses if pose.name)
            print(
                f"[t+{int(time.time() - start):>3}s] table of {here.count}, "
                f"{len(here.poses)} in use, {names} named"
            )

    if not taken:
        raise SystemExit("the animation table never became readable")
    report(taken)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
