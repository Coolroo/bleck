"""The pieces every part of a `.glb` is built out of: the blob, and the vertices.

Split from `gltf` because three modules need these and none of them needs each
other. `gltf` writes the document and the container, `gltfmorph` writes the
animation, `gltfpaint` writes the materials — and all three hand bytes to one
`Blob` and address them through accessors described here.

⚠️ **Imports run one way.** `gltfcore` reads nothing of the three; a helper
that needed `gltf.write` back would be in the wrong module.

## One primitive per shape

⛔ **Merging a file's shapes into one mesh is what made `e_lui_robo` look
broken** (D236). It holds 92 of them, one is a flat quad 130 units off to the
side, and merged there was no way to see that it was a separate object or to
hide it. `parts` returns one `Part` per shape, which is also the prerequisite
for binding a texture per shape (D229).
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: glTF component types, from the specification's enum.
FLOAT = 5126
UNSIGNED_INT = 5125
UNSIGNED_SHORT = 5123
UNSIGNED_BYTE = 5121

#: Buffer view targets. Vertex data and index data are bound differently, and
#: some readers reject a view that does not say which it is.
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


@dataclass
class Blob:
    """The binary chunk, and the views handed out into it."""

    data: bytearray = field(default_factory=bytearray)
    views: list = field(default_factory=list)  # pylint: disable=container-return

    def add(self, payload: bytes, target: int | None = None) -> int:
        """Append bytes 4-byte aligned, and return the new view's index."""
        while len(self.data) % 4:
            self.data.append(0)
        view = {"buffer": 0, "byteOffset": len(self.data), "byteLength": len(payload)}
        if target is not None:
            view["target"] = target
        self.views.append(view)
        self.data += payload
        return len(self.views) - 1


@dataclass(frozen=True)
class Vertex:
    """One glTF vertex: a position, and the normal and UV that go with it.

    ⚠️ **glTF indexes every attribute together; this format does not.** A
    corner names its position, its normal and its UV separately, so two corners
    sharing a position but not a normal are *two* glTF vertices. Collapsing
    them would weld a hard edge into a smooth one. The same holds for the UV:
    two corners at one point on a texture seam sit at different places on the
    image, and welding them stretches the art across the seam.
    """

    position: int
    normal: int | None
    uv: int | None
    colour: int | None = None
    """Which entry of `Mesh.colours` multiplies this vertex's texture."""


def accessor(view: int, count: int, kind: str, component: int) -> dict:
    # pylint: disable=container-return
    """One glTF accessor record over a whole buffer view."""
    return {
        "bufferView": view,
        "componentType": component,
        "count": count,
        "type": kind,
    }


@dataclass(frozen=True)
class Part:
    """One shape, as the primitive that will carry it.

    ⚠️ **Its own vertices, not a window into a shared list.** A morph target is
    per-primitive, so primitives sharing one vertex list would each pay for
    every other primitive's vertices — 92 shapes would cost 92 times the
    animation block. Partitioned, the total is what it always was.
    """

    vertices: list = field(default_factory=list)  # pylint: disable=container-return
    indices: list = field(default_factory=list)  # pylint: disable=container-return
    #: The layers this shape draws with, in texture-map order -- `modelmat.Layer`
    #: records, or bare image indices from a hand-built mesh. The first becomes
    #: the primitive's `baseColorTexture` and the second, where there is one, its
    #: alpha mask; see `gltfpaint`.
    textures: list = field(default_factory=list)  # pylint: disable=container-return
    #: Which shape of the model this came from. ⚠️ **Not the primitive's own
    #: position.** `parts` drops a shape whose faces are all degenerate, so the
    #: two indices diverge, and anything keyed on a shape -- the visibility flag
    #: in `modelnodes` -- must match on this rather than count primitives.
    shape: int = -1


@dataclass(frozen=True)
class Paint:
    """One image the caller decoded, ready to embed.

    `index` is the model's own image index, which is what `Part.textures`
    names -- not a position in the list, so a caller may pass only the images
    its shapes actually reach.
    """

    index: int
    png: bytes


def _weld(mesh, faces: list | None) -> Part:
    """Corners collapsed to unique (position, normal, uv) vertices.

    ⚠️ **Whether there is a texture is asked per shape** (D240). 269 models mix
    textured and untextured shapes, and asking once for the whole mesh dropped
    the coordinates from every shape in all of them.
    """
    order: dict[Vertex, int] = {}
    vertices: list[Vertex] = []
    indices: list[int] = []
    textured = mesh.textured(faces)
    for triangle in mesh.corner_triangles(faces):
        for corner in triangle:
            vertex = Vertex(
                position=corner.position,
                normal=corner.normal,
                uv=corner.uv if textured else None,
                colour=corner.colour,
            )
            found = order.get(vertex)
            if found is None:
                found = len(vertices)
                order[vertex] = found
                vertices.append(vertex)
            indices.append(found)
    return Part(vertices=vertices, indices=indices)


def parts(mesh) -> list:  # pylint: disable=container-return
    """One `Part` per shape the mesh describes.

    ⛔ **Not one merged mesh.** `e_lui_robo` holds 92 shapes and one of them is
    a flat quad 130 units from the character; merged, it reads as broken
    geometry welded to the model with no way to hide it (D236).

    A shape whose faces all fell out as degenerate contributes no primitive
    rather than an empty one, which no reader accepts.
    """
    found = []
    for index, span in enumerate(mesh.shape_spans()):
        part = _weld(mesh, mesh.shape_faces(span))
        if part.vertices and part.indices:
            found.append(
                Part(
                    vertices=part.vertices,
                    indices=part.indices,
                    textures=list(getattr(span, "textures", [])),
                    shape=index,
                )
            )
    return found
