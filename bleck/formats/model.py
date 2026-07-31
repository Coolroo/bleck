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
FACE_SLOT = 0
POSITION_SLOT = 1
POSITION_INDEX_SLOT = 2
NORMAL_SLOT = 3
NORMAL_INDEX_SLOT = 4

#: A face is `(first corner, corner count)`, eight bytes. The draw code reads
#: the pair as `lwz 0(r23)` and `lwz 4(r23)`, indexing `r23` by `idx * 8`.
FACE_STRIDE = 8

#: The eight texture-coordinate channels. All eight slots hold the same offset
#: when only one channel is used, so a channel's length runs to the next
#: *different* entry -- which is why the table has to be read past 16 (D208).
TEXCOORD_SLOT = 8
FULL_SECTIONS = 24

#: A UV pair is two floats. ✅ 79% of models keep every pair inside [0,1] and
#: 74% have exactly one pair per position; values above 1 are texture tiling,
#: not a misread (D215).
UV_PAIR = 8

#: `GXSetVtxAttrFmt` is called with `GX_F32`, `GX_POS_XYZ` and a stride of 12
#: for both positions and normals, so a triple is three big-endian floats.
TRIPLE = 12

#: A normal is unit length. This is the property that *proves* slot 3 rather
#: than suggesting it, so it is checked rather than assumed.
UNIT_TOLERANCE = 0.02


@dataclass(frozen=True)
class Face:
    """One polygon: where its corners start, and how many it has."""

    first: int
    corners: int


@dataclass(frozen=True)
class Corner:
    """One corner of a face: which position it uses, and which normal."""

    position: int
    normal: int | None
    """None when the model carries no normal stream for this corner."""


@dataclass(frozen=True)
class Mesh:
    """The vertex arrays of one shape, as the game hands them to GX.

    ⛔ **A fragment, not a model.** The table holds 24 slots describing one
    shape, and a character file names dozens; `p_wii_mario` carries 88 shape
    names and 200 KB of data this record does not reach. Median coverage across
    the disc is **13.6%** (D211). Check `coverage` before drawing anything.
    """

    name: str
    positions: list = field(default_factory=list)  # pylint: disable=container-return
    #: Unit-length float triples. Verified on read; see `UNIT_TOLERANCE`.
    normals: list = field(default_factory=list)  # pylint: disable=container-return
    #: Polygons in draw order. `first` indexes `corner_positions`.
    faces: list = field(default_factory=list)  # pylint: disable=container-return
    #: One position index per corner, in draw order.
    corner_positions: list = field(  # pylint: disable=container-return
        default_factory=list
    )
    #: One normal index per corner. ⚠️ **Read, never assumed.** It is the plain
    #: identity in 766 of 870 models, a permutation in 101, and neither in 3 --
    #: so treating it as `corner == normal` would mis-shade 104 models.
    corner_normals: list = field(  # pylint: disable=container-return
        default_factory=list
    )
    #: Texture coordinates, one pair per position where the counts agree.
    uvs: list = field(default_factory=list)  # pylint: disable=container-return
    #: Lengths of the `u16`-in-`u32` index streams, in table order.
    streams: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def is_textured(self) -> bool:
        """Whether a UV can be found for every position.

        ⚠️ Checked, not assumed: 26% of models have a different number of UVs
        than positions, and pairing them by index there would smear a texture
        across the wrong triangles.
        """
        return bool(self.uvs) and len(self.uvs) == len(self.positions)

    @property
    def corners(self) -> int:
        return sum(face.corners for face in self.faces)

    @property
    def coverage(self) -> float:
        """The fraction of `positions` any face actually reaches.

        ⛔ **Usually small, and that is the honest headline.** The median across
        the disc is 13.6%: `p_big_kuppa` has 3,401 positions and its faces touch
        three of them. A shape record describes one shape, and a character file
        holds many, so what this reads is a *fragment* (D211).

        Read this before trusting a mesh. `is_drawable` only says the indices
        resolve; this says how much of the model they resolve *to*.
        """
        if not self.positions:
            return 0.0
        used = {index for triangle in self.triangles() for index in triangle}
        return len(used) / len(self.positions)

    @property
    def is_drawable(self) -> bool:
        """Whether every face resolves to a real position.

        ⚠️ **This is not "the mesh is complete".** It is a bounds check, and it
        passes on a fragment that reaches 0.1% of the model. Ask `coverage` for
        that, and see D211 for why the two came apart.
        """
        if not self.faces or not self.positions:
            return False
        return all(
            face.first + face.corners <= len(self.corner_positions)
            and max(
                self.corner_positions[face.first : face.first + face.corners],
                default=0,
            )
            < len(self.positions)
            for face in self.faces
        )

    def triangles(self) -> list:  # pylint: disable=container-return
        """Every face fanned into triangles, as indices into `positions`.

        A fan is correct for these faces because they are **planar** -- 98% of
        4-corner faces on the disc are, against 16% for shuffled indices, which
        is what made the reading trustworthy in the first place (D209).
        """
        return [tuple(c.position for c in tri) for tri in self.corner_triangles()]

    def corner_triangles(self) -> list:  # pylint: disable=container-return
        """The same triangles, but keeping each corner's normal alongside it.

        ⚠️ A corner's normal comes from `corner_normals`, which is *not*
        reliably the identity -- 104 of 870 models would be mis-shaded by
        assuming it is.
        """
        out = []
        for face in self.faces:
            span = slice(face.first, face.first + face.corners)
            positions = self.corner_positions[span]
            normals = self.corner_normals[span]
            corners = [
                Corner(position=p, normal=normals[i] if i < len(normals) else None)
                for i, p in enumerate(positions)
            ]
            for i in range(1, len(corners) - 1):
                out.append((corners[0], corners[i], corners[i + 1]))
        return out

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.positions)} position(s), "
            f"{len(self.normals)} normal(s), {len(self.faces)} face(s) / "
            f"{self.corners} corner(s), {self.coverage * 100:.1f}% covered"
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
    faces = _faces(data, table[FACE_SLOT], edges[FACE_SLOT + 1])
    corners = sum(face.corners for face in faces)
    if streams and corners not in streams:
        raise ModelError(
            f"slot {FACE_SLOT} at {table[FACE_SLOT]:#x} is not a face list: "
            f"{len(faces)} faces cover {corners} corners, but the index "
            f"streams are {streams} long"
        )
    return Mesh(
        corner_positions=_stream(data, table, edges, POSITION_INDEX_SLOT),
        corner_normals=_stream(data, table, edges, NORMAL_INDEX_SLOT),
        uvs=_uvs(data),
        name=name,
        positions=positions,
        normals=normals,
        faces=faces,
        streams=streams,
    )


def _uvs(data: bytes) -> list:  # pylint: disable=container-return
    """Texture coordinates from the first texture-coordinate channel.

    ⚠️ Its length runs to the next **different** table entry, not the next
    entry. All eight channel slots carry the same offset when one channel is in
    use, so `table[slot + 1] - table[slot]` is zero and reads as no data.
    """
    need = SHAPE_SECTIONS_AT + FULL_SECTIONS * 4
    if len(data) < need:
        return []
    table = struct.unpack_from(f">{FULL_SECTIONS}I", data, SHAPE_SECTIONS_AT)
    start = table[TEXCOORD_SLOT]
    later = [at for at in table[TEXCOORD_SLOT + 1 :] if start < at <= len(data)]
    if not later:
        return []
    span = min(later) - start
    if span < UV_PAIR or span % UV_PAIR or start + span > len(data):
        return []
    count = span // UV_PAIR
    return [struct.unpack_from(">2f", data, start + i * UV_PAIR) for i in range(count)]


def _stream(data: bytes, table: tuple, edges: list, slot: int) -> list:
    # pylint: disable=container-return
    """One index stream, as the `u16`-in-`u32` words the draw loop reads."""
    start, stop = table[slot], edges[slot + 1]
    if stop <= start or (stop - start) % 4:
        return []
    return list(struct.unpack_from(f">{(stop - start) // 4}I", data, start))


def _faces(data: bytes, start: int, stop: int) -> list:
    # pylint: disable=container-return
    """The face list, trusted because its corner counts add up.

    ⚠️ This is the check that makes the reading more than a shape that fits:
    the counts sum to exactly the length of the index streams. A wrong stride
    or a wrong slot gives a sum that misses, and `mesh` would rather refuse.
    """
    count = (stop - start) // FACE_STRIDE
    pairs = [
        struct.unpack_from(">II", data, start + i * FACE_STRIDE) for i in range(count)
    ]
    return [Face(first=first, corners=size & 0xFFFF) for first, size in pairs]


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

#: A key's value is signed 8.8 fixed point, so an accumulated total is divided
#: by this to reach model space. ✅ Track 5 of `mario_S_1` accumulates to 15052,
#: and 15052/256 = 58.8 -- the model's Y bound is 58.7 (D216).
KEY_SCALE = 256.0


@dataclass(frozen=True)
class Morph:
    """One pose: a sparse set of per-vertex offsets, and when it applies.

    ⛔ **Not skeletal.** `animPoseMain` at `0x800457e4` copies the model's
    positions into a working buffer and adds these offsets to it directly --
    there is no joint, no matrix and nothing to bind (D217). A key is
    `[u8 vertex stride, s8 dx, s8 dy, s8 dz]`, and `lfsux` *advances* the
    destination pointer by the stride, which is why byte 0 is almost always 1.
    """

    time: float
    offsets: list = field(default_factory=list)  # pylint: disable=container-return
    """`(vertex, dx, dy, dz)`, in model units."""

    @property
    def reach(self) -> int:
        return max((v for v, *_ in self.offsets), default=-1)


def morphs(data: bytes, clip: Clip) -> list:  # pylint: disable=container-return
    """A clip's poses, decoded the way the game applies them.

    ✅ Verified against `p_wii_mario`: all 1,152 keys of `mario_S_1` resolve to
    vertices inside its 324-position array, and every `dz` is zero -- which is
    what a flat character should produce (D217).
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
    for index in range(count):
        at = tracks_at + index * CLIP_TRACK_STRIDE
        if at + CLIP_TRACK_STRIDE > len(data):
            break
        time = struct.unpack_from(">f", data, at)[0]
        first, length = struct.unpack_from(">2I", data, at + 4)
        if length < 1 or first + length > keys:
            continue
        offsets = []
        vertex = 0
        for step in range(length):
            key = keys_at + (first + step) * CLIP_KEY_STRIDE
            vertex += data[key]
            offsets.append((vertex, *struct.unpack_from(">3b", data, key + 1)))
        found.append(Morph(time=time, offsets=offsets))
    return found


@dataclass(frozen=True)
class Curve:
    """One track of a clip: times, and the values they carry.

    ⚠️ **The encoding is verified; what the curve *drives* is not.** Which node
    or property a track belongs to is unknown, so these are real numbers with
    no established meaning (D216).
    """

    index: int
    mark: float
    """Field 0 of the track record. Ascends across a clip's tracks, so it is a
    position on the timeline rather than a duration."""

    times: list = field(default_factory=list)  # pylint: disable=container-return
    values: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def span(self) -> float:
        return max(self.values) - min(self.values) if self.values else 0.0


def curves(data: bytes, clip: Clip) -> list:  # pylint: disable=container-return
    """A clip's tracks, decoded from their delta-compressed keys.

    Each key is four bytes: a time step, a **signed 16-bit delta**, and a zero.
    Accumulating the deltas is what makes a curve; reading them as absolute
    values does not.

    ✅ Verified by smoothness against a shuffled control: accumulated keys score
    0.0112 where shuffled ones score 0.155, a fourteen-fold separation (D216).
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
    for index in range(count):
        at = tracks_at + index * CLIP_TRACK_STRIDE
        if at + CLIP_TRACK_STRIDE > len(data):
            break
        first, length = struct.unpack_from(">2I", data, at + 4)
        if length < 2 or first + length > keys:
            continue
        mark = struct.unpack_from(">f", data, at)[0]
        span = Span(at=keys_at + first * CLIP_KEY_STRIDE, length=length)
        found.append(_curve(data, index, mark, span))
    return found


@dataclass(frozen=True)
class Span:
    """Where one track's keys start, and how many there are."""

    at: int
    length: int


def _curve(data: bytes, index: int, mark: float, span: Span) -> Curve:
    """One track's keys, accumulated into times and values."""
    times, values = [], []
    clock = 0
    total = 0
    for step in range(span.length):
        key = span.at + step * CLIP_KEY_STRIDE
        clock += data[key]
        total += struct.unpack_from(">h", data, key + 1)[0]
        times.append(float(clock))
        values.append(total / KEY_SCALE)
    return Curve(index=index, mark=mark, times=times, values=values)


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
