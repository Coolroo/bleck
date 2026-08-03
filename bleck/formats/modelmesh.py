"""A character model's geometry as a value: the vertex arrays, and how to cut them.

Split out of `model`, which decodes the *container* -- the model's name, its
bounding box, the section table and the name blocks. Neither half needs the
other, which is the seam: a caller that only wants to know what a file is never
pays for the geometry, and the two were found by different means at different
times.

⚠️ **Nothing here reads bytes.** `modelarrays` does that and hands back a
`Mesh`; `modelrebase` decides which slice of the arrays each shape indexes
into. A hand-built `Mesh` in a test is as valid as one off the disc, which is
what the split is for, and the imports run one way: `modelarrays` reads this
and never the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleck.formats.modelbase import Shape

#: Below this a triangle covers no pixels. Dropping them costs nothing and
#: saves a depth test each; `e_genjin_b` alone carries 18 of 104.
AREA_EPSILON = 1e-9


@dataclass(frozen=True)
class Corner:
    """One corner of a face: which position it uses, which normal, which UV."""

    position: int
    normal: int | None
    """None when the model carries no normal stream for this corner."""
    uv: int | None = None
    """None when the model carries no texture-coordinate stream for this corner."""
    colour: int | None = None
    """None when the model carries no vertex-colour stream for this corner."""


@dataclass(frozen=True)
class Mesh:  # pylint: disable=too-many-instance-attributes
    """The vertex arrays of a whole model, as the game hands them to GX.

    ⚠️ **One field per array the file carries, and the count is the format's,
    not a choice.** GX is handed positions, normals, colours and texture
    coordinates, each with its own index stream — grouping them would put a
    reader one indirection away from the section table they come from.

    ✅ **Every shape in the file, not a fragment.** Median coverage across the
    disc is 100% and the mean 99.8%; `groups` says where each shape's faces sit
    and `shapes` how many there are (D224, D240).

    ⛔ D211 called this a fragment at 13.6% median coverage and is superseded —
    that was the per-shape rebasing missing, not the file holding less than it
    looked like.
    """

    name: str
    positions: list = field(default_factory=list)  # pylint: disable=container-return
    #: Unit-length float triples. Verified on read; see `modelarrays`.
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
    #: Slot 5, one `(r, g, b, a)` byte quadruple per entry.
    #:
    #: ⚠️ **The texture is multiplied by this, so leaving it out turns a red
    #: panel white** (D251). The disc stores one greyscale panel and tints it
    #: per shape; 331 of 864 models carry more than one colour and rendered
    #: near-white without it.
    colours: list = field(default_factory=list)  # pylint: disable=container-return
    #: One colour index per corner, in draw order, from slot 6.
    corner_colours: list = field(  # pylint: disable=container-return
        default_factory=list
    )
    #: Lengths of the `u16`-in-`u32` index streams, in table order.
    streams: list = field(default_factory=list)  # pylint: disable=container-return
    #: How many separate shapes the face list describes.
    #:
    #: ⚠️ Each has its **own** image rather than a region of one atlas -- every
    #: group's UVs span the whole [0,1] square (D229). Which image is now read
    #: from the file: see `materials` and `Shape.textures`.
    shapes: int = 1
    #: Every image the file can draw with, in bank order, as `modelmat.Material`.
    #:
    #: ✅ **The binding is decoded** (D243). ⛔ D229 said it was not and that a
    #: model with more than one shape had to export bare; that is superseded.
    #: A shape names its own material through the layer table, and 284 of 286
    #: shapes checked against a third-party rip of Brobot pick an image of
    #: exactly the reference's dimensions, against 14-31% for a shuffled
    #: control.
    materials: list = field(default_factory=list)  # pylint: disable=container-return
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
        outside `modelarrays.mesh` fills `groups`, and a caller that got an
        empty list back would write a file with no geometry in it.
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
            colours = self.corner_colours[span]
            corners = [
                Corner(
                    position=p,
                    normal=normals[i] if i < len(normals) else None,
                    uv=uvs[i] if i < len(uvs) else None,
                    colour=colours[i] if i < len(colours) else None,
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
