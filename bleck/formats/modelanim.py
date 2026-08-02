"""A character model's animation: the clip table and its morph poses.

Split out of `model`, which finds the clip block's bounds in the section table
and hands them here. `Clip` lives with the decoders that consume it rather than
beside `Model`, so the dependency runs one way -- the container imports this,
and this imports nothing back.

⛔ **Morph targets, not skeletal animation** (D217). `animPoseMain` at
`0x800457e4` copies the model's positions into a working buffer and adds these
offsets to it directly; there is no joint, no matrix and nothing to bind.

⚠️ **A track is one keyframe's *increment*, not a whole pose** (D252). The draw
loop applies every track from the first up to the current frame into one
buffer, so a pose is the running total. `morphs` returns the total, which is
what a glTF morph target holds.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import text

#: An animation clip record: a 60-byte name field, then a `u32` file offset to
#: that clip's data. ⚠️ Measured, not guessed -- `mario_Z_1` at +0x00 points at
#: 0x15F5C and `mario_S_1` at +0x40 points at 0x15FFC, which is immediately
#: past it.
CLIP_STRIDE = 0x40
CLIP_POINTER_AT = 0x3C

#: A clip's own record: its byte size, four counts, then seven sub-section
#: offsets relative to the record start.
#:
#: ✅ Record sizes chain -- `offset + size` lands on the next clip's offset --
#: and the 94 sizes sum to exactly the 201,580-byte region, so not one byte is
#: unaccounted for.
#:
#: ⚠️ **Sections 1, 2 and 4 are the counted ones**, dividing by one of the
#: record's counts 94, 88 and 91 times out of 94 with no exceptions. Sections 0,
#: 5 and 6 are fixed-size or padded and do *not* -- an earlier claim that every
#: section divides was wrong, and the test that asserts this is what caught it
#: (D205).
COUNTED_SECTIONS = (1, 2, 4)
RECORD_SIZE_AT = 0x00
RECORD_COUNTS_AT = (0x08, 0x0C, 0x14, 0x1C)
RECORD_SECTIONS_AT = 0x24
RECORD_SECTIONS = 7

#: A clip record's own layout. Its section offsets are **relative to the
#: record**, not file-absolute, which is why every absolute-offset scan walked
#: straight past them (D212).
CLIP_SECTIONS_AT = 0x24
CLIP_SECTIONS = 8
CLIP_TRACK_STRIDE = 44
CLIP_KEY_STRIDE = 4

#: Sections within a clip, by index into its own table.
TRACK_SECTION = 1
KEY_SECTION = 2

#: What the game multiplies a key's `s8` delta by before adding it to a vertex.
#: ✅ **Measured, not inferred** (D252). `animPoseMain` loads it once at
#: `0x80045798` -- `lfs f0,-30780(r2)`, and `_SDA2_BASE_` is `0x805B7260`, so
#: the float is the `3d800000` at `0x805AFA24`. Every `fmadds` in the key loop
#: scales by it, so a delta of 1 moves a vertex a sixteenth of a unit.
DELTA_SCALE = 1.0 / 16.0


@dataclass(frozen=True)
class Clip:
    """One clip: its name, where its record is, and that record's shape.

    ⚠️ **The structure is decoded; the payloads are not.** Sizes, counts and
    sub-section boundaries all check out exactly, and none of that says what a
    sub-section *means*. A caller can walk this safely and still cannot draw
    anything from it.
    """

    name: str
    offset: int
    size: int = 0
    counts: tuple = ()
    """The four counts in the record header. Each sub-section's length divides
    by one of them."""

    sections: tuple = ()
    """Sub-section offsets, relative to `offset`."""

    def section_bounds(self) -> list:  # pylint: disable=container-return
        """Each sub-section as (start, length), relative to the record."""
        edges = [*self.sections, self.size]
        return [(edges[i], edges[i + 1] - edges[i]) for i in range(len(edges) - 1)]

    def describe(self) -> str:
        return f"{self.name}: {self.size:,} bytes, counts {self.counts}"


@dataclass(frozen=True)
class Span:
    """Where one track's keys start, and how many there are."""

    at: int
    length: int


@dataclass(frozen=True)
class Morph:
    """One pose: where the vertices it moves sit relative to the rest pose.

    ⛔ **Not skeletal.** `animPoseMain` at `0x800457e4` copies the model's
    positions into a working buffer and adds these offsets to it directly --
    there is no joint, no matrix and nothing to bind (D217). A key is
    `[u8 vertex stride, s8 dx, s8 dy, s8 dz]`, and `lfsux` *advances* the
    destination pointer by the stride, which is why byte 0 is almost always 1.
    """

    time: float
    offsets: list = field(default_factory=list)  # pylint: disable=container-return
    """`(vertex, dx, dy, dz)` displacements from the rest pose, in model units.

    ⚠️ **A total, not one track's own keys** (D252). The track this pose came
    from carries only what changed since the one before it."""

    @property
    def reach(self) -> int:
        return max((v for v, *_ in self.offsets), default=-1)


def morphs(data: bytes, clip: Clip) -> list:  # pylint: disable=container-return
    """A clip's poses, decoded the way the game applies them.

    ✅ **A pose is every track up to it, added together** (D252). The rebuild
    loop at `0x800457ac` walks tracks `0..frame` into one buffer that was
    copied from the model's own positions, and the *incremental* path at
    `0x80045d34` applies only `cached+1..frame` on top of what is already
    there, without re-copying. Two paths that must agree, and they only can if
    a track is an increment.

    ✅ Verified against `p_wii_mario`: all 1,152 keys of `mario_S_1` resolve to
    vertices inside its 324-position array, and every `dz` is zero -- which is
    what a flat character should produce (D217).

    ⚠️ **A zero-length track is a keyframe too**, and 13,115 of the disc's
    35,190 tracks are ones. It holds the pose where the previous track left it,
    so dropping it loses a beat rather than a movement.
    """
    base = clip.offset
    if base + CLIP_SECTIONS_AT + CLIP_SECTIONS * 4 > len(data):
        return []
    table = struct.unpack_from(f">{CLIP_SECTIONS}I", data, base + CLIP_SECTIONS_AT)
    tracks_at, keys_at = base + table[TRACK_SECTION], base + table[KEY_SECTION]
    count = (table[TRACK_SECTION + 1] - table[TRACK_SECTION]) // CLIP_TRACK_STRIDE
    keys = (table[KEY_SECTION + 1] - table[KEY_SECTION]) // CLIP_KEY_STRIDE
    if count <= 0 or keys <= 0:
        return []

    found = []
    running: dict[int, list[float]] = {}
    for index in range(count):
        at = tracks_at + index * CLIP_TRACK_STRIDE
        if at + CLIP_TRACK_STRIDE > len(data):
            break
        time = struct.unpack_from(">f", data, at)[0]
        first, length = struct.unpack_from(">2I", data, at + 4)
        if first + length > keys:
            continue
        _apply(data, Span(at=keys_at + first * CLIP_KEY_STRIDE, length=length), running)
        found.append(
            Morph(
                time=time,
                offsets=[(v, *total) for v, total in sorted(running.items())],
            )
        )
    return found


def _apply(data: bytes, span: Span, running: dict) -> None:
    """Add one track's keys to the running displacement of each vertex.

    ⚠️ The vertex index restarts at zero for every track: the draw loop
    reloads the buffer pointer from `80(r29)` before each one and then walks it
    forward with `lfsux`.
    """
    vertex = 0
    for step in range(span.length):
        key = span.at + step * CLIP_KEY_STRIDE
        vertex += data[key]
        deltas = struct.unpack_from(">3b", data, key + 1)
        total = running.setdefault(vertex, [0.0, 0.0, 0.0])
        for axis in range(3):
            total[axis] += deltas[axis] * DELTA_SCALE


def clips(data: bytes, start: int, end: int) -> list[Clip]:
    """The animation table: fixed-stride records of name plus data pointer.

    ⚠️ A record whose pointer falls outside the file ends the table. The block
    is padded, so reading to `end` blindly yields empty trailing entries.
    """
    # pylint: disable=container-return
    found: list[Clip] = []
    if not 0 <= start < end <= len(data):
        return found
    for at in range(start, end - CLIP_STRIDE + 1, CLIP_STRIDE):
        name = text(data[at : at + CLIP_POINTER_AT])
        offset = struct.unpack_from(">I", data, at + CLIP_POINTER_AT)[0]
        if not name or not 0 < offset < len(data):
            break
        found.append(_clip_record(data, name, offset))
    return found


def _clip_record(data: bytes, name: str, offset: int) -> Clip:
    """Read a clip's record header, or return the bare pointer if it will not.

    ⚠️ Degrades rather than raises. A record that does not parse is still a
    real clip with a real offset, and losing the whole list over one is worse
    than carrying one with empty counts.
    """
    if offset + RECORD_SECTIONS_AT + RECORD_SECTIONS * 4 > len(data):
        return Clip(name=name, offset=offset)
    size = struct.unpack_from(">I", data, offset + RECORD_SIZE_AT)[0]
    if not 0 < size <= len(data) - offset:
        return Clip(name=name, offset=offset)
    counts = tuple(
        struct.unpack_from(">I", data, offset + at)[0] for at in RECORD_COUNTS_AT
    )
    sections = struct.unpack_from(
        f">{RECORD_SECTIONS}I", data, offset + RECORD_SECTIONS_AT
    )
    return Clip(name=name, offset=offset, size=size, counts=counts, sections=sections)
