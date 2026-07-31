"""Character models: the `/a/<name>` half of each pair in `files/a/`.

⚠️ **Partially decoded.** What this reads is real and checked; the geometry is
not here yet. Saying so precisely matters more than usual, because a model
reader that quietly returns nothing for the vertices would look like a working
model reader.

| | |
|---|---|
| ✅ name, build stamp | read |
| ✅ bounding box | read, and sane — Mario is 58.7 units tall |
| ✅ shape names | read, in file order |
| ✅ texture references | read, and **counted against the TPL bank** |
| ✅ joint names | 176 for Mario |
| ✅ animation clip names | 94 for Mario -- `mario_N_1`, `mario_W_1` |
| ✅ section table | 26 entries, found by structure |
| ⛔ vertices, indices, weights | **not decoded** |
| ⛔ animation keyframes | not decoded -- only the clip names |

## What the file looks like

`files/a/` holds 1,687 files in pairs: `name` (this) and `name-` (a TPL bank,
D-verified). The model half opens with a `u32` pointing at a second header near
the end, then its own name and a build stamp — `p_wii_mario` is a Maya export
from **Mon Jan 29 2007**.

⛔ **It is not `map.dat`'s format.** Rooms announce their sections in a string
table (`mesh`, `material_name_table`, `animation_table`, D167); none of those
markers appears in a character file. Two containers, decoded separately.

## 🟢 The texture link, which is exact

A model names its textures by their **original TGA source paths** —
`ara/playar/mario/w_tex/R_arem.1.tga`. `p_wii_mario` carries **126** of them and
`p_wii_mario-` holds **126** images.

Across all 787 pairs on the disc:

| | |
|---|---|
| references == bank images | 773 |
| references < bank images | 14 |
| **references > bank images** | **0** |

⛔ **That zero is the invariant**, and it is what makes the pairing a reading
rather than a coincidence: a bank may carry images nothing references, but a
model never names an image its bank does not have. ⚠️ Checked, not assumed —
the first version deduplicated the paths, which would have hidden a model that
reuses one, and the counts were re-measured without it.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from bleck.common.errors import BleckError

#: The section table is a run of ascending in-file offsets near the start.
#: ⚠️ Located by *structure*, not a fixed offset -- `scripts/modelscan.py
#: offsets` is what found it, and every one of the 870 models has 26 entries.
#: The last two sections are the joint names and the animation clip names.
TABLE_SEARCH = 0x400
TABLE_LEAST = 6
JOINTS_FROM_END = 2
ANIMS_FROM_END = 1

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

#: A model's own name and its build stamp sit at fixed offsets in the opening
#: record, each in a 32-byte field.
NAME_AT = 0x44
STAMP_AT = 0x84
FIELD = 32

#: Maya writes every shape's name with this suffix, which is what makes them
#: findable without decoding the node table first.
SHAPE_SUFFIX = b"Shape"

#: Source-art paths, kept verbatim by the exporter.
TEXTURE_RE = re.compile(rb"[A-Za-z0-9_./]+\.tga")

_NAME_RE = re.compile(rb"[A-Za-z0-9_]{2,31}Shape\x00")


class ModelError(BleckError):
    """A character model could not be read."""


@dataclass(frozen=True)
class Bounds:
    """The model's axis-aligned bounding box, in game units."""

    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    def describe(self) -> str:
        return (
            f"({self.min_x:.1f}, {self.min_y:.1f}, {self.min_z:.1f}) .. "
            f"({self.max_x:.1f}, {self.max_y:.1f}, {self.max_z:.1f})"
        )


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


#: A shape record lists eight data sections here, as file-absolute offsets,
#: and names itself through the word just before them.
SHAPE_SECTIONS_AT = 0x150
SHAPE_SECTIONS = 8
SHAPE_NAME_AT = 0x14C

#: Which slot holds what. Named from the draw code at `0x80048520`, which
#: loads the equivalent runtime pointers from `+0x158`/`+0x160`/`+0x168`/
#: `+0x16C` and feeds them to `GXSetArray` (D207).
POSITION_SLOT = 1
NORMAL_SLOT = 3

#: `GXSetVtxAttrFmt` is called with `GX_F32`, `GX_POS_XYZ` and a stride of 12
#: for both positions and normals, so a triple is three big-endian floats.
TRIPLE = 12

#: A normal is unit length. This is the property that *proves* slot 3 rather
#: than suggesting it, so it is checked rather than assumed.
UNIT_TOLERANCE = 0.02


@dataclass(frozen=True)
class Mesh:
    """The vertex arrays of one shape, as the game hands them to GX.

    ⚠️ **Vertices, not triangles.** The four parallel index streams are read
    and counted, but which primitive they assemble into is not known, so
    nothing here can be drawn as a surface yet (D207).
    """

    name: str
    positions: list = field(default_factory=list)  # pylint: disable=container-return
    #: Unit-length float triples, one per normal index. Verified on read.
    normals: list = field(default_factory=list)  # pylint: disable=container-return
    #: Lengths of the four `u16`-in-`u32` index streams, in table order.
    streams: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def is_drawable(self) -> bool:
        """⛔ Always False, and deliberately. Positions exist; the triangle
        list does not, and a viewer handed loose points would draw nothing."""
        return False

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.positions)} position(s), "
            f"{len(self.normals)} normal(s), streams {self.streams}"
        )


@dataclass(frozen=True)
class Model:
    """What a character file says about itself, short of its geometry."""

    name: str
    stamp: str
    """The Maya export date, e.g. `Mon Jan 29 10:30:46 2007`."""

    bounds: Bounds
    shapes: list[str] = field(default_factory=list)
    """Mesh names in file order -- `zentaiShape`, `R_Arm_skinShape`."""

    textures: list[str] = field(default_factory=list)
    """Original TGA source paths. ⚠️ These name the images in the `-` bank
    beside this file, and the counts match."""

    joints: list[str] = field(default_factory=list)
    """Skeleton node names -- `R_Arm_skin`, `zentai`, `mario_arm`.

    ⚠️ **Approximate.** Unlike the clip table these records are *not* a fixed
    stride -- the first two are 0x58 apart and the next is 0x59 -- so these are
    scanned rather than indexed, and a name may be missed or carry a stray
    leading byte. Do not count them and conclude anything."""

    animations: list[Clip] = field(default_factory=list)
    """Clips, each with a name and a pointer to its own data. ⚠️ The pointer is
    real and checked; **what it points at is not decoded**, so nothing here can
    play one."""

    @property
    def has_geometry(self) -> bool:
        """⛔ Always False. Vertices are not decoded, and a caller asking this
        is better served by a plain no than by an empty list it might render."""
        return False

    @property
    def can_animate(self) -> bool:
        """⛔ Also always False. `animations` holds names; a name is not a
        curve, and a viewer offered one would have nothing to play."""
        return False

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.shapes)} shape(s), "
            f"{len(self.textures)} texture(s), {len(self.joints)} joint(s), "
            f"{len(self.animations)} clip(s), bounds {self.bounds.describe()}"
        )


def _text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()


def is_model(data: bytes) -> bool:
    """Whether this looks like the model half of an `files/a/` pair.

    ⚠️ Checked by structure, not by a magic number -- the format has none. The
    leading word must point inside the file, and a name must follow it.
    """
    if len(data) < NAME_AT + FIELD:
        return False
    head = struct.unpack_from(">I", data, 0)[0]
    if not 0 < head < len(data):
        return False
    return bool(_text(data[NAME_AT : NAME_AT + FIELD]))


#: In the record the file's leading word points at. The model's own box lives
#: there, not in the opening record.
BOUNDS_AT = 0x44


def _bounds(data: bytes) -> Bounds:
    """The whole model's bounding box.

    ⛔ **Not the opening record's.** A first version scanned that record for six
    plausible floats and found a box — a *sub-object's*, giving Mario a height
    of 17.9 where the model is 58.7. Six numbers that are all individually
    reasonable is exactly what a wrong offset produces here, which is why the
    test asserts a height known independently rather than merely a positive one.

    The real box is at +0x44 of the record the file's leading word points at.
    """
    head = struct.unpack_from(">I", data, 0)[0]
    at = head + BOUNDS_AT
    if at + 24 > len(data):
        raise ModelError(f"the record at {head:#x} runs past the end of the file")
    values = struct.unpack_from(">6f", data, at)
    if any(values[i] > values[i + 3] for i in range(3)):
        raise ModelError(
            f"the six floats at {at:#x} are not a bounding box: "
            f"{values[:3]} is not below {values[3:]}"
        )
    return Bounds(*values)


_ANY_NAME = re.compile(rb"[A-Za-z][A-Za-z0-9_.]{1,31}\x00")


def _triples(data: bytes, start: int, stop: int) -> list:
    # pylint: disable=container-return
    """One section read as big-endian float XYZ, the way `GXSetArray` reads it."""
    count = (stop - start) // TRIPLE
    return [struct.unpack_from(">3f", data, start + i * TRIPLE) for i in range(count)]


def _is_index_stream(data: bytes, start: int, stop: int) -> bool:
    """A stream the draw loop copies into the GX FIFO a halfword at a time.

    The loop reads `lhz 0(rN)` then steps by 4, so every entry is a `u32`
    whose value fits in `u16`. That is the whole signature, and it is what
    separates an index array from a float array without decoding either.
    """
    span = stop - start
    if span < 4 or span % 4:
        return False
    words = struct.unpack_from(f">{span // 4}I", data, start)
    return all(value < 0x10000 for value in words)


def mesh(data: bytes) -> Mesh:
    """The first shape's vertex arrays, from the section table at `0x150`.

    ⚠️ **The normals are checked, not trusted.** Slot 3 is claimed to hold
    normals; if its triples are not unit length the claim is wrong and this
    raises rather than handing back plausible nonsense.
    """
    if len(data) < SHAPE_SECTIONS_AT + SHAPE_SECTIONS * 4:
        raise ModelError("too short to hold a shape record")
    table = struct.unpack_from(f">{SHAPE_SECTIONS}I", data, SHAPE_SECTIONS_AT)
    if list(table) != sorted(table) or not all(0 < at < len(data) for at in table):
        raise ModelError(f"the words at {SHAPE_SECTIONS_AT:#x} are not a section table")

    name_at = struct.unpack_from(">I", data, SHAPE_NAME_AT)[0]
    name = _text(data[name_at : name_at + FIELD]) if name_at < len(data) else ""

    edges = [*table, len(data)]
    positions = _triples(data, table[POSITION_SLOT], edges[POSITION_SLOT + 1])
    normals = _triples(data, table[NORMAL_SLOT], edges[NORMAL_SLOT + 1])

    stray = [n for n in normals if abs(_length(n) - 1.0) > UNIT_TOLERANCE]
    if stray:
        raise ModelError(
            f"slot {NORMAL_SLOT} at {table[NORMAL_SLOT]:#x} is not a normal array: "
            f"{len(stray)} of {len(normals)} triples are not unit length"
        )

    streams = [
        (edges[i + 1] - at) // 4
        for i, at in enumerate(table)
        if _is_index_stream(data, at, edges[i + 1])
    ]
    return Mesh(name=name, positions=positions, normals=normals, streams=streams)


def _length(triple: tuple) -> float:
    x, y, z = triple
    return (x * x + y * y + z * z) ** 0.5


def section_table(data: bytes) -> tuple:  # pylint: disable=container-return
    """Where the section table starts and how many entries it has.

    ⚠️ Found as the longest run of ascending in-file offsets near the start,
    because no fixed offset works: the run begins at 0x148 in `p_wii_mario` and
    a naive look at 0x170 finds only its tail. `scripts/modelscan.py offsets`
    is the tool that showed the fuller table.
    """
    runs: list[tuple[int, int]] = []
    words = min(len(data) // 4, TABLE_SEARCH // 4)
    start = None
    previous = -1
    for index in range(words):
        value = struct.unpack_from(">I", data, index * 4)[0]
        if 0 < value < len(data) and value >= previous:
            if start is None:
                start = index
            previous = value
            continue
        if start is not None and index - start >= TABLE_LEAST:
            runs.append((start * 4, index - start))
        start = None
        previous = -1
    if start is not None and words - start >= TABLE_LEAST:
        runs.append((start * 4, words - start))
    if not runs:
        raise ModelError("no section table found in the first 1 KB")
    return max(runs, key=lambda run: run[1])


def _names_between(data: bytes, start: int, end: int) -> list[str]:
    """Null-terminated names in a padded block.

    ⚠️ Each must be **preceded by a null or the block edge**. Without that the
    tail of the previous entry gets picked up whenever its last byte happens to
    be printable, and `mario_S_3` reads as `Tmario_S_3` -- wrong in a way that
    looks like a real name.
    """
    # pylint: disable=container-return
    if not 0 <= start < end <= len(data):
        return []
    block = data[start:end]
    found = []
    for match in _ANY_NAME.finditer(block):
        if match.start() and block[match.start() - 1] != 0:
            continue
        found.append(match.group()[:-1].decode("ascii", "replace"))
    return found


def _clips(data: bytes, start: int, end: int) -> list[Clip]:
    """The animation table: fixed-stride records of name plus data pointer.

    ⚠️ A record whose pointer falls outside the file ends the table. The block
    is padded, so reading to `end` blindly yields empty trailing entries.
    """
    # pylint: disable=container-return
    found: list[Clip] = []
    if not 0 <= start < end <= len(data):
        return found
    for at in range(start, end - CLIP_STRIDE + 1, CLIP_STRIDE):
        name = _text(data[at : at + CLIP_POINTER_AT])
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


def read(data: bytes) -> Model:
    """Everything this reader can establish about a character model."""
    if not is_model(data):
        raise ModelError(
            "not a character model: expected a leading offset into the file "
            "and a name at 0x44"
        )
    shapes = [_text(m.group()) for m in _NAME_RE.finditer(data)]
    textures = [m.group().decode("ascii", "replace") for m in TEXTURE_RE.finditer(data)]

    joints: list[str] = []
    animations: list[str] = []
    try:
        at, count = section_table(data)
        ends = struct.unpack_from(f">{count}I", data, at)
        head = struct.unpack_from(">I", data, 0)[0]
        joints = _names_between(data, ends[-JOINTS_FROM_END], ends[-ANIMS_FROM_END])
        animations = _clips(data, ends[-ANIMS_FROM_END], head)
    except (ModelError, struct.error):
        # ⚠️ Absent, not fatal: 11 of 870 models do not yield both lists, and a
        # model with no clips is still worth reading for everything else.
        pass

    return Model(
        name=_text(data[NAME_AT : NAME_AT + FIELD]),
        stamp=_text(data[STAMP_AT : STAMP_AT + FIELD]),
        bounds=_bounds(data),
        shapes=shapes,
        # ⚠️ Order preserved and duplicates kept: the count is compared
        # against the bank's image count, and deduplicating would hide a
        # model that legitimately reuses one.
        textures=textures,
        joints=joints,
        animations=animations,
    )


def bank_for(path: Path) -> Path:
    """The TPL bank beside a model: the same name with a trailing `-`."""
    return path.with_name(path.name + "-")
