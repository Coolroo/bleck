"""Reading a model's vertex arrays out of the section table at `0x150`.

Split from `modelmesh`, which is the value those arrays land in. This is the
byte-level half: which slot holds what, how long each span is, and the checks
that make each reading a reading rather than a shape that happens to fit.
`modelmesh` needs nothing from here — it is a mesh, however it was obtained —
which is the seam, and it means a hand-built `Mesh` in a test never goes
through any of this.

✅ **The slot meanings are read off the draw code, not guessed** (D207). The
function at `0x80048520` loads the equivalent runtime pointers from
`+0x158`/`+0x160`/`+0x168`/`+0x16C` and feeds them to `GXSetArray`, so what
each section holds is stated by the game rather than inferred from the bytes.

`modelrebase` is the other half of the geometry: it decides which slice of
these arrays each shape indexes into.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from bleck.formats import modelmat
from bleck.formats.modelbase import (
    FIELD,
    SHAPE_SECTIONS,
    SHAPE_SECTIONS_AT,
    Face,
    ModelError,
    text,
)
from bleck.formats.modelmesh import Mesh
from bleck.formats.modelrebase import (
    GROUP_TABLE_AT,
    Held,
    Plan,
    batches,
    group_table,
    rebase,
    spans,
)

#: Which slot holds what. Named from the draw code at `0x80048520`, which
#: loads the equivalent runtime pointers from `+0x158`/`+0x160`/`+0x168`/
#: `+0x16C` and feeds them to `GXSetArray` (D207).
FACE_SLOT = 0
POSITION_SLOT = 1
POSITION_INDEX_SLOT = 2
NORMAL_SLOT = 3
NORMAL_INDEX_SLOT = 4

#: Per-vertex colour, and the index stream that reaches it. ✅ Named from the
#: same draw code, which sets `GXSetVtxDesc(GX_VA_CLR0, GX_INDEX16)`,
#: `GXSetVtxAttrFmt(fmt0, GX_VA_CLR0, GX_CLR_RGBA, GX_RGBA8, 0)` and
#: `GXSetArray(GX_VA_CLR0, table[5], 4)` at `0x80048594` (D251).
COLOUR_SLOT = 5
COLOUR_INDEX_SLOT = 6

#: One colour is four bytes, `GX_RGBA8`.
COLOUR_STRIDE = 4

#: One texture-coordinate index per corner, in the same `u16`-in-`u32` form as
#: slots 2 and 4. ⚠️ Its stop edge is `table[8]`, so reading it needs the wider
#: table rather than the eight-entry shape record.
TEXCOORD_INDEX_SLOT = 7

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

    name_at = struct.unpack_from(">I", data, GROUP_TABLE_AT)[0]
    name = text(data[name_at : name_at + FIELD]) if name_at < len(data) else ""

    edges = [*table, len(data)]
    positions = _triples(data, table[POSITION_SLOT], edges[POSITION_SLOT + 1])
    normals = _checked_normals(data, table, edges)
    streams = [
        (edges[i + 1] - at) // 4
        for i, at in enumerate(table)
        if _is_index_stream(data, at, edges[i + 1])
    ]
    faces = _checked_faces(data, table, edges, streams)
    split = batches(data, faces)
    shapes = len(split)
    uvs = _uvs(data)
    rebased = rebase(
        split,
        _stream(data, table, edges, POSITION_INDEX_SLOT),
        _uv_indices(data),
        Plan(
            groups=group_table(data, shapes),
            held=Held(positions=len(positions), uvs=len(uvs)),
        ),
    )
    corner_positions = rebased.positions
    # ⚠️ 22 faces across the disc rebase past the end, against 1,250 for a
    # shuffled control -- so the bases are right and these few are not. Dropped
    # rather than clamped, since a clamped face stretches to the last vertex.
    kept = [
        (face, owner)
        for face, owner in zip(rebased.faces, rebased.groups, strict=True)
        if face.first + face.corners <= len(corner_positions)
        and max(corner_positions[face.first : face.first + face.corners], default=0)
        < len(positions)
    ]
    faces = [face for face, _ in kept]
    palette = modelmat.read(data)
    groups = spans([owner for _, owner in kept], rebased.names, palette.shapes)
    corner_uvs = _corner_uvs(
        rebased.uvs,
        corner_positions,
        Extent(uvs=len(uvs), positions=len(positions), corners=_reach(faces)),
    )
    return Mesh(
        materials=palette.images,
        corner_positions=corner_positions,
        corner_normals=_stream(data, table, edges, NORMAL_INDEX_SLOT),
        corner_uvs=corner_uvs,
        colours=_colours(data, table, edges),
        corner_colours=_stream(data, table, edges, COLOUR_INDEX_SLOT),
        uvs=uvs,
        name=name,
        positions=positions,
        normals=normals,
        faces=faces,
        streams=streams,
        shapes=shapes,
        groups=groups,
    )


def _checked_normals(data: bytes, table: tuple, edges: list) -> list:
    # pylint: disable=container-return
    """Slot 3, refused unless every triple is unit length.

    Six files on the disc fail this, and a reader that shrugged would hand a
    viewer numbers that look like data.
    """
    found = _triples(data, table[NORMAL_SLOT], edges[NORMAL_SLOT + 1])
    stray = [n for n in found if abs(_length(n) - 1.0) > UNIT_TOLERANCE]
    if stray:
        raise ModelError(
            f"slot {NORMAL_SLOT} at {table[NORMAL_SLOT]:#x} is not a normal array: "
            f"{len(stray)} of {len(found)} triples are not unit length"
        )
    return found


def _checked_faces(data: bytes, table: tuple, edges: list, streams: list) -> list:
    # pylint: disable=container-return
    """Slot 0, refused unless its corner counts sum to an index stream's length.

    That sum is what makes the face list a reading rather than a shape that
    fits: a wrong stride or a wrong slot gives a total that misses.
    """
    found = _faces(data, table[FACE_SLOT], edges[FACE_SLOT + 1])
    corners = sum(face.corners for face in found)
    if streams and corners not in streams:
        raise ModelError(
            f"slot {FACE_SLOT} at {table[FACE_SLOT]:#x} is not a face list: "
            f"{len(found)} faces cover {corners} corners, but the index "
            f"streams are {streams} long"
        )
    return found


def _reach(faces: list) -> int:
    """The last corner any face draws, which is as far as a stream must go."""
    return max((face.first + face.corners for face in faces), default=0)


@dataclass(frozen=True)
class Extent:
    """How much of each array a file holds, in the terms that pick a reading."""

    uvs: int
    positions: int
    corners: int


def _corner_uvs(stream: list, corner_positions: list, extent: Extent) -> list:
    # pylint: disable=container-return
    """One UV index per corner: slot 7 where it reaches, the position index
    where it does not.

    ✅ Slot 7 is the reading that wins where it exists — median UV triangle
    area **0.0407** against 0.0559 for pairing by position and 0.0886 for a
    shuffled control, over 595 models and 57,310 faces (D234).

    ⚠️ Some models carry a slot-7 stream shorter than the corners their faces
    draw, and most of those hold exactly one UV per position — `e_2D_manera`
    and the other paper sprites, whose every shape is a quad spanning the whole
    image. Pairing those by position is the older reading and the only one
    available, so it stands rather than costing them their texture.

    ⛔ The rest resolve no UV at all. Guessing one would smear the bank across
    the model, which reads as a broken renderer rather than as missing data.
    """
    reached = stream[: extent.corners]
    if reached and any(at is not None for at in reached):
        return stream
    if extent.uvs and extent.uvs == extent.positions:
        return list(corner_positions)
    return []


def _uv_indices(data: bytes) -> list:  # pylint: disable=container-return
    """Slot 7, one texture-coordinate index per corner.

    ⚠️ **Needs the 24-entry table.** The eight-entry shape record makes slot 7
    the last one, so its span would run to the end of the file and the stream
    would not read as one. `table[8]` is where it actually stops.
    """
    need = SHAPE_SECTIONS_AT + (TEXCOORD_INDEX_SLOT + 2) * 4
    if len(data) < need:
        return []
    table = struct.unpack_from(f">{TEXCOORD_INDEX_SLOT + 2}I", data, SHAPE_SECTIONS_AT)
    start, stop = table[TEXCOORD_INDEX_SLOT], table[TEXCOORD_INDEX_SLOT + 1]
    if not 0 < start <= stop <= len(data) or not _is_index_stream(data, start, stop):
        return []
    return list(struct.unpack_from(f">{(stop - start) // 4}I", data, start))


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


def _colours(data: bytes, table: tuple, edges: list) -> list:
    # pylint: disable=container-return
    """Slot 5, as `(r, g, b, a)` byte quadruples.

    ✅ **The format is stated, not inferred** (D251). The draw code calls
    `GXSetVtxAttrFmt(fmt0, GX_VA_CLR0, GX_CLR_RGBA, GX_RGBA8, 0)` and hands
    `GXSetArray` a stride of 4, so an entry is four bytes in channel order.

    ⚠️ **No per-group base and no separate corner offset.** Every one of the
    disc's 17,290 group records carries `(0, 0)` for its colour slice, and the
    colour corner offset at shape record `+0x48` equals the position one on all
    18,631 shape records — so this reads like the normal stream rather than
    like the UV one, which does need both (D240).
    """
    start, stop = table[COLOUR_SLOT], edges[COLOUR_SLOT + 1]
    if stop <= start or (stop - start) % COLOUR_STRIDE:
        return []
    count = (stop - start) // COLOUR_STRIDE
    return [
        tuple(data[start + i * COLOUR_STRIDE : start + (i + 1) * COLOUR_STRIDE])
        for i in range(count)
    ]


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
