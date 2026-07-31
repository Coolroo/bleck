"""A character model's geometry: one shape record, read the way GX reads it.

Split out of `model`, which decodes the *container* -- the model's name, its
bounding box, the section table and the name blocks. This decodes the vertex
arrays a shape record points at. Neither half needs the other, which is the
seam: a caller that only wants to know what a file is never pays for the
geometry, and the two were found by different means at different times.

✅ **The slot meanings are read off the draw code, not guessed** (D207). The
function at `0x80048520` loads the equivalent runtime pointers from
`+0x158`/`+0x160`/`+0x168`/`+0x16C` and feeds them to `GXSetArray`, so what
each section holds is stated by the game rather than inferred from the bytes.

⛔ **What comes back is a fragment.** A shape record describes one shape and a
character file holds dozens; median coverage across the disc is 13.6% (D211).
`Mesh.coverage` is the number to read before drawing anything.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import FIELD, ModelError, text

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

#: Below this a triangle covers no pixels. Dropping them costs nothing and
#: saves a depth test each; `e_genjin_b` alone carries 18 of 104.
AREA_EPSILON = 1e-9


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

    name_at = struct.unpack_from(">I", data, SHAPE_NAME_AT)[0]
    name = text(data[name_at : name_at + FIELD]) if name_at < len(data) else ""

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

    faces, corner_positions = _rebase(
        faces, _stream(data, table, edges, POSITION_INDEX_SLOT)
    )
    # ⚠️ 22 faces across the disc rebase past the end, against 1,250 for a
    # shuffled control -- so the bases are right and these few are not. Dropped
    # rather than clamped, since a clamped face stretches to the last vertex.
    faces = [
        face
        for face in faces
        if face.first + face.corners <= len(corner_positions)
        and max(corner_positions[face.first : face.first + face.corners], default=0)
        < len(positions)
    ]
    return Mesh(
        corner_positions=corner_positions,
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


def _rebase(faces: list, stream: list) -> tuple:  # pylint: disable=container-return
    """Fold each shape's corner and position bases into flat, absolute values.

    ✅ **This is what takes coverage from 13% to 100%** (D224). A file's faces
    are grouped by shape, and a group restarts its `first` at zero — so both
    the corner offset *and* the position index are relative to the shape, not
    the file. The draw code says so outright: `GXSetArray` is handed
    `add r16, r4, r0`, a position array **plus a per-shape offset**, which is
    why the index stream never exceeds 22 while the array holds 324 points.

    Both bases accumulate: corners by the span a group covers, positions by how
    many distinct points it used.
    """
    rebased = list(stream)
    out: list[Face] = []
    corner_base = 0
    position_base = 0
    for group in _groups(faces):
        span = max((f.first + f.corners for f in group), default=0)
        seen = set()
        for face in group:
            low = corner_base + face.first
            for at in range(low, min(low + face.corners, len(rebased))):
                seen.add(rebased[at])
                rebased[at] += position_base
            out.append(Face(first=low, corners=face.corners))
        corner_base += span
        position_base += len(seen)
    return out, rebased


def _groups(faces: list) -> list:  # pylint: disable=container-return
    """Faces split where `first` restarts at zero, which is where one shape
    ends and the next begins."""
    found: list[list] = []
    current: list = []
    for face in faces:
        if face.first == 0 and current:
            found.append(current)
            current = []
        current.append(face)
    if current:
        found.append(current)
    return found


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
