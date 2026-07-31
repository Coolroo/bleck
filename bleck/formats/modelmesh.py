"""A character model's geometry: the vertex arrays, read the way GX reads it.

Split out of `model`, which decodes the *container* -- the model's name, its
bounding box, the section table and the name blocks. This decodes the vertex
arrays the section table points at. Neither half needs the other, which is the
seam: a caller that only wants to know what a file is never pays for the
geometry, and the two were found by different means at different times.

`modelrebase` is the other half of the geometry: it decides which slice of these
arrays each shape indexes into.

✅ **The slot meanings are read off the draw code, not guessed** (D207). The
function at `0x80048520` loads the equivalent runtime pointers from
`+0x158`/`+0x160`/`+0x168`/`+0x16C` and feeds them to `GXSetArray`, so what
each section holds is stated by the game rather than inferred from the bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import (
    FIELD,
    SHAPE_SECTIONS,
    SHAPE_SECTIONS_AT,
    Face,
    ModelError,
    Shape,
    text,
)
from bleck.formats.modelrebase import (
    GROUP_STRIDE,
    GROUP_TABLE_AT,
    SHAPE_RECORD_STRIDE,
    Group,
    Held,
    Plan,
    Slice,
    batches,
    group_table,
    rebase,
    spans,
)

__all__ = [
    "AREA_EPSILON",
    "FACE_SLOT",
    "FACE_STRIDE",
    "FULL_SECTIONS",
    "GROUP_STRIDE",
    "GROUP_TABLE_AT",
    "NORMAL_INDEX_SLOT",
    "NORMAL_SLOT",
    "POSITION_INDEX_SLOT",
    "POSITION_SLOT",
    "SHAPE_RECORD_STRIDE",
    "SHAPE_SECTIONS",
    "SHAPE_SECTIONS_AT",
    "TEXCOORD_INDEX_SLOT",
    "TEXCOORD_SLOT",
    "TRIPLE",
    "UNIT_TOLERANCE",
    "UV_PAIR",
    "Corner",
    "Face",
    "Group",
    "Mesh",
    "Shape",
    "Slice",
    "mesh",
]

#: Which slot holds what. Named from the draw code at `0x80048520`, which
#: loads the equivalent runtime pointers from `+0x158`/`+0x160`/`+0x168`/
#: `+0x16C` and feeds them to `GXSetArray` (D207).
FACE_SLOT = 0
POSITION_SLOT = 1
POSITION_INDEX_SLOT = 2
NORMAL_SLOT = 3
NORMAL_INDEX_SLOT = 4

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

#: Below this a triangle covers no pixels. Dropping them costs nothing and
#: saves a depth test each; `e_genjin_b` alone carries 18 of 104.
AREA_EPSILON = 1e-9


#: A normal is unit length. This is the property that *proves* slot 3 rather
#: than suggesting it, so it is checked rather than assumed.
UNIT_TOLERANCE = 0.02


@dataclass(frozen=True)
class Corner:
    """One corner of a face: which position it uses, which normal, which UV."""

    position: int
    normal: int | None
    """None when the model carries no normal stream for this corner."""
    uv: int | None = None
    """None when the model carries no texture-coordinate stream for this corner."""


@dataclass(frozen=True)
class Mesh:
    """The vertex arrays of a whole model, as the game hands them to GX.

    ✅ **Every shape in the file, not a fragment.** Median coverage across the
    disc is 100% and the mean 99.8%; `groups` says where each shape's faces sit
    and `shapes` how many there are (D224, D240).

    ⛔ D211 called this a fragment at 13.6% median coverage and is superseded —
    that was the per-shape rebasing missing, not the file holding less than it
    looked like.
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
    #: Texture coordinates, indexed by `corner_uvs` rather than by position.
    uvs: list = field(default_factory=list)  # pylint: disable=container-return
    #: One UV index per corner, in draw order. ⚠️ **Read from slot 7, not
    #: derived.** `e_bara_tib_p` has 64 positions and 96 UVs, so pairing a UV to
    #: a position index drops the texture on 26% of the disc's models (D234).
    corner_uvs: list = field(  # pylint: disable=container-return
        default_factory=list
    )
    #: Lengths of the `u16`-in-`u32` index streams, in table order.
    streams: list = field(default_factory=list)  # pylint: disable=container-return
    #: How many separate shapes the face list describes.
    #:
    #: ⛔ **A model with more than one cannot be textured** (D229). Each shape
    #: has its own image -- every group's UVs span the whole [0,1] square, so
    #: they are not regions of one atlas -- and which image goes with which
    #: shape is not decoded. Painting image 0 across all of them draws the
    #: whole sprite sheet onto every limb.
    shapes: int = 1
    #: Where each shape's faces sit in `faces`, in draw order.
    #:
    #: ⚠️ **May be shorter than `shapes`.** A shape whose every face rebased
    #: past the end of the position array leaves no span, and `shapes` counts
    #: what the file describes rather than what survived the read.
    groups: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def is_textured(self) -> bool:
        """Whether every corner in the whole mesh resolves to a real UV.

        ⚠️ **Usually the wrong question** (D240). A shape carries texture
        coordinates or it does not, and 269 models mix the two — asking about
        the whole mesh throws the texture away from the shapes that have one.
        Ask `textured` per shape instead; this stays for callers that really do
        mean the whole thing.
        """
        return self.textured()

    def textured(self, faces: list | None = None) -> bool:
        """Whether every corner these faces draw resolves to a real UV.

        ⚠️ **Not a count comparison.** UVs are indexed per corner and there are
        more of them than positions on 26% of the disc — `e_bara_tib_p` has 64
        positions against 96 UVs — so requiring the counts to match dropped the
        texture from every one of those models (D234).
        """
        if not self.uvs or not self.corner_uvs:
            return False
        return all(
            corner.uv is not None and corner.uv < len(self.uvs)
            for triangle in self.corner_triangles(faces)
            for corner in triangle
        )

    @property
    def corners(self) -> int:
        return sum(face.corners for face in self.faces)

    @property
    def coverage(self) -> float:
        """The fraction of `positions` any face actually reaches.

        ✅ **Usually 100%**, and short of it for a real reason: a file may carry
        points no face draws. The median across the disc is 100% and the mean
        99.8% (D240).

        Read this before trusting a mesh. `is_drawable` only says the indices
        resolve; this says how much of the model they resolve *to*, so a fall
        back to the older base-counting reading shows up here as a drop.
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

    def shape_spans(self) -> list:  # pylint: disable=container-return
        """Each shape's faces, or one span over all of them.

        ⚠️ **The fallback is what keeps a hand-built `Mesh` working.** Nothing
        outside `mesh()` fills `groups`, and a caller that got an empty list
        back would write a file with no geometry in it.
        """
        if self.groups:
            return list(self.groups)
        return [Shape(first=0, count=len(self.faces))] if self.faces else []

    def shape_faces(self, span: Shape) -> list:  # pylint: disable=container-return
        """The faces one span covers."""
        return self.faces[span.first : span.first + span.count]

    def triangles(self, faces: list | None = None) -> list:
        # pylint: disable=container-return
        """Every face cut into triangles, as indices into `positions`.

        ⚠️ **Ear clipping, not a fan.** 14% of the disc's 4-corner faces are not
        convex and a fan turns one into a bow-tie (D223); see `_cut`. The faces
        are **planar** -- 98% of 4-corner ones are, against 16% for shuffled
        indices -- which is what made the reading trustworthy (D209).
        """
        return [tuple(c.position for c in tri) for tri in self.corner_triangles(faces)]

    def corner_triangles(self, faces: list | None = None) -> list:
        # pylint: disable=container-return
        """The same triangles, keeping each corner's normal and UV alongside it.

        ⚠️ A corner's normal comes from `corner_normals` and its UV from
        `corner_uvs`; neither is reliably the identity -- 104 of 870 models
        would be mis-shaded by assuming it for normals, and the UV stream is a
        different length from the position stream on 26% of them.

        `faces` narrows this to one shape's span; the default is every face.
        """
        out = []
        for face in self.faces if faces is None else faces:
            span = slice(face.first, face.first + face.corners)
            positions = self.corner_positions[span]
            normals = self.corner_normals[span]
            uvs = self.corner_uvs[span]
            corners = [
                Corner(
                    position=p,
                    normal=normals[i] if i < len(normals) else None,
                    uv=uvs[i] if i < len(uvs) else None,
                )
                for i, p in enumerate(positions)
            ]
            out += self._cut(corners)
        return out

    def _cut(self, corners: list) -> list:  # pylint: disable=container-return
        """One polygon into triangles, without fanning across a reflex corner.

        ⛔ **A fan is only correct for a convex polygon**, and 14% of the disc's
        4-corner faces are not convex — 182 models carry at least one. Fanning
        one produces a bow-tie: two corners open into a triangle that crosses
        the middle of the shape and drags the texture with it, which is exactly
        how it was reported (D223).

        Ear clipping instead: repeatedly take a corner whose triangle stays
        inside the polygon. ⚠️ Zero-area triangles are dropped as they appear —
        18 of `e_genjin_b`'s 104 were degenerate, and they render nothing while
        still costing a depth test.
        """
        if len(corners) < 3:
            return []
        plane = self._plane(corners)
        pool = list(corners)
        out = []
        guard = len(pool) * len(pool)
        while len(pool) > 3 and guard > 0:
            guard -= 1
            for i, _ in enumerate(pool):
                # ⚠️ Negative indices are deliberate: `i - 2` and `i - 1` wrap
                # to the end of the list, so the corner before the first one is
                # the last one, as a closed polygon requires.
                trio = (pool[i - 2], pool[i - 1], pool[i])
                if self._is_ear(pool, trio, plane):
                    if self._area(trio) > AREA_EPSILON:
                        out.append(trio)
                    pool.pop(i - 1)
                    break
            else:
                # ⚠️ No ear found: the polygon is degenerate or self-crossing,
                # so fall back to a fan rather than dropping it silently.
                break
        for i in range(1, len(pool) - 1):
            trio = (pool[0], pool[i], pool[i + 1])
            if self._area(trio) > AREA_EPSILON:
                out.append(trio)
        return out

    def _plane(self, corners: list) -> tuple:  # pylint: disable=container-return
        """A normal for the polygon, summed over its corners so that one
        degenerate triple cannot decide the winding for the whole face."""
        total = (0.0, 0.0, 0.0)
        points = [self.positions[c.position] for c in corners]
        for i, point in enumerate(points):
            nxt = points[(i + 1) % len(points)]
            total = (
                total[0] + (point[1] - nxt[1]) * (point[2] + nxt[2]),
                total[1] + (point[2] - nxt[2]) * (point[0] + nxt[0]),
                total[2] + (point[0] - nxt[0]) * (point[1] + nxt[1]),
            )
        return total

    def _area(self, trio: tuple) -> float:
        a, b, c = (self.positions[corner.position] for corner in trio)
        edge = [b[i] - a[i] for i in range(3)]
        other = [c[i] - a[i] for i in range(3)]
        cross = (
            edge[1] * other[2] - edge[2] * other[1],
            edge[2] * other[0] - edge[0] * other[2],
            edge[0] * other[1] - edge[1] * other[0],
        )
        return sum(v * v for v in cross) ** 0.5

    def _is_ear(self, pool: list, trio: tuple, plane: tuple) -> bool:
        """Whether the corner turns the same way as the polygon and encloses
        no other corner."""
        a, b, c = (self.positions[corner.position] for corner in trio)
        edge = [b[i] - a[i] for i in range(3)]
        other = [c[i] - b[i] for i in range(3)]
        cross = (
            edge[1] * other[2] - edge[2] * other[1],
            edge[2] * other[0] - edge[0] * other[2],
            edge[0] * other[1] - edge[1] * other[0],
        )
        if sum(cross[i] * plane[i] for i in range(3)) < 0:
            return False
        inside = {corner.position for corner in trio}
        for corner in pool:
            if corner.position in inside:
                continue
            if _within(self.positions[corner.position], a, b, c, plane):
                return False
        return True

    def describe(self) -> str:
        return (
            f"{self.name}: {len(self.positions)} position(s), "
            f"{len(self.normals)} normal(s), {len(self.faces)} face(s) / "
            f"{self.corners} corner(s), {self.coverage * 100:.1f}% covered"
        )


def _within(point: tuple, a: tuple, b: tuple, c: tuple, plane: tuple) -> bool:
    """Whether a point falls inside a triangle, measured in the face's plane.

    Barycentric sign tests against the polygon's own normal, so a face lying in
    any orientation is handled without projecting to a chosen axis pair.
    """
    for start, end in ((a, b), (b, c), (c, a)):
        edge = [end[i] - start[i] for i in range(3)]
        arm = [point[i] - start[i] for i in range(3)]
        cross = (
            edge[1] * arm[2] - edge[2] * arm[1],
            edge[2] * arm[0] - edge[0] * arm[2],
            edge[0] * arm[1] - edge[1] * arm[0],
        )
        if sum(cross[i] * plane[i] for i in range(3)) < 0:
            return False
    return True


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
    groups = spans([owner for _, owner in kept], rebased.names)
    corner_uvs = _corner_uvs(
        rebased.uvs,
        corner_positions,
        Extent(uvs=len(uvs), positions=len(positions), corners=_reach(faces)),
    )
    return Mesh(
        corner_positions=corner_positions,
        corner_normals=_stream(data, table, edges, NORMAL_INDEX_SLOT),
        corner_uvs=corner_uvs,
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


@dataclass(frozen=True)
class Extent:
    """How much of each array a file holds, in the terms that pick a reading."""

    uvs: int
    positions: int
    corners: int


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
