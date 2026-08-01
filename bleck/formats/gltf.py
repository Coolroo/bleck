"""Writing glTF 2.0, in the single-file `.glb` container.

⚠️ **Chosen because it can be checked by someone other than us.** A `.glb`
opens in Blender, Windows 3D Viewer and any browser, so a claim about the
geometry stops depending on `dimentio` — which is the only thing that could
display a mesh, on a machine that cannot capture its own screen (D213). An
export nobody can open independently is an export nobody can falsify.

⛔ **Wavefront OBJ was the first choice and cannot survive.** It has no
skeleton and no keyframe, so animation is not expressible in it at all. FBX
carries both and is proprietary, binary, and has no maintainable open writer.

glTF is JSON plus one binary blob, so this is stdlib-only. `bleck` ships with
two runtime dependencies, both argued for in `pyproject.toml`, and a model
exporter is not the place to spend a third.

## One primitive per shape

⛔ **Merging a file's shapes into one mesh is what made `e_lui_robo` look
broken** (D236). It holds 92 of them, one is a flat quad 130 units off to the
side, and merged there was no way to see that it was a separate object or to
hide it. Each shape is now its own primitive, which is also the prerequisite
for ever binding a texture per shape (D229).

## Where the textures went

`gltfpaint` writes the materials, samplers, textures and images. This module
writes the geometry and calls it; the split is because a shape's texture layers
carry a wrap mode, a UV transform and possibly a mask (D247), and none of that
belongs beside the accessor arithmetic.

## Morph targets, sparse where sparse is smaller

A pose displaces a few dozen of a *model's* vertices out of hundreds (D217), so
a target can be written as a glTF **sparse accessor**: an index array, a value
array, and zero everywhere else.

⚠️ **This overturns an earlier decision, deliberately.** Targets were written
dense on the grounds that sparse support is patchy across readers and a target
that fails to load is worse than one that wastes a few kilobytes (D217). That
reasoning is not withdrawn — it is outweighed. The dense cost dropped 823 of
3,079 clips from the export, and a clip that was never written cannot fail to
load either. `write(..., sparse=False)` writes every target in full for a
reader that chokes, and `bleck model export --dense-morphs` reaches it.

⚠️ **Sparse turned out to be the minority case, and it is applied per target
rather than everywhere.** A primitive is one *shape* after the split above, so
a pose that reaches a primitive at all usually moves all of it: 68% of touched
primitive-poses across the disc move every vertex the primitive has, and the
mean fill is 0.811 (D238). A sparse accessor over those costs more than the
dense one it replaces, so `sparse_pays` decides each target on its own.

⛔ **A pose that misses a primitive is not a count-0 sparse accessor.**
`accessor.sparse.count` carries `"minimum": 1` in the specification's schema.
It is an accessor with no `bufferView` and no `sparse` instead, which the
specification defines as zeros and which occupies no bytes at all.

## The container

    [12-byte header][JSON chunk][BIN chunk]

Every chunk is padded to a 4-byte boundary -- JSON with spaces, binary with
zeros. ⚠️ The padding is not optional; a reader that trusts the length fields
will misparse the second chunk without it.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field

from bleck.formats import gltfpaint

MAGIC = 0x46546C67
VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942

#: glTF component types, from the specification's enum.
FLOAT = 5126
UNSIGNED_INT = 5125
UNSIGNED_SHORT = 5123
UNSIGNED_BYTE = 5121

#: The narrowest index type a sparse accessor over `count` elements can use,
#: and how many bytes one of its indices takes. ⚠️ Most primitives after the
#: per-shape split hold a handful of vertices, so this is nearly always one
#: byte -- a `u32` index would cost more than the delta it points at saves.
INDEX_WIDTHS = ((0x100, UNSIGNED_BYTE, 1), (0x10000, UNSIGNED_SHORT, 2))

#: Buffer view targets. Vertex data and index data are bound differently, and
#: some readers reject a view that does not say which it is.
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963

#: What one dense morph target costs per glTF vertex: three floats of position
#: delta. ⚠️ The whole reason animation needs a budget -- a file's targets are
#: `poses * vertices * 12` bytes, which passes the geometry at three poses.
TARGET_BYTES = 12

#: What one target costs in the JSON chunk before any delta: the accessor
#: record and the buffer views it names. ⚠️ **Measured, by differencing real
#: `.glb` files against the same models written without animation** -- a sparse
#: accessor names two views and carries a nested `sparse` object, so it costs
#: ~100 bytes more than a dense one however few vertices it moves.
SPARSE_OVERHEAD = 260
DENSE_OVERHEAD = 162

#: What each primitive adds to every pose, as one `{"POSITION":n}` entry in its
#: own `targets` array. ⚠️ **This is what binds on a split mesh.**
#: `p_wii_mario` carries 90 primitives, so a pose costs ~1.8 KB of JSON before
#: a single delta is written.
TARGET_REFERENCE = 20

#: One float of the `weights` array a keyframe carries for every target in the
#: file, and the `0.0,` the mesh's own array spends on each.
#: ⚠️ **This term is quadratic** -- `keys * targets` with one key per target --
#: and above a few hundred targets it is the largest cost in the file, whatever
#: the targets themselves are encoded as.
WEIGHT_BYTES = 4
WEIGHT_JSON = 4


@dataclass
class _Blob:
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


def _accessor(view: int, count: int, kind: str, component: int) -> dict:
    # pylint: disable=container-return
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
            )
            found = order.get(vertex)
            if found is None:
                found = len(vertices)
                order[vertex] = found
                vertices.append(vertex)
            indices.append(found)
    return Part(vertices=vertices, indices=indices)


def _parts(mesh) -> list:  # pylint: disable=container-return
    """One `Part` per shape the mesh describes.

    ⛔ **Not one merged mesh.** `e_lui_robo` holds 92 shapes and one of them is
    a flat quad 130 units from the character; merged, it reads as broken
    geometry welded to the model with no way to hide it (D236).

    A shape whose faces all fell out as degenerate contributes no primitive
    rather than an empty one, which no reader accepts.
    """
    found = []
    for span in mesh.shape_spans():
        part = _weld(mesh, mesh.shape_faces(span))
        if part.vertices and part.indices:
            found.append(
                Part(
                    vertices=part.vertices,
                    indices=part.indices,
                    textures=list(getattr(span, "textures", [])),
                )
            )
    return found


@dataclass(frozen=True)
class Shift:
    """One pose's effect on one primitive: which vertices move, and by how much.

    `at` indexes the *primitive's* vertex list and ascends strictly, which is
    what a glTF sparse accessor requires of its index array.

    ⚠️ Offsets are addressed by *model* vertex, and a glTF vertex is a welded
    (position, normal, uv) triple — so one offset may land on several entries.
    """

    at: list = field(default_factory=list)  # pylint: disable=container-return
    deltas: list = field(default_factory=list)  # pylint: disable=container-return


def _shift(part: Part, moved: dict) -> Shift:
    """Which of one primitive's vertices a pose displaces.

    A delta that is all zeros is left out: it is indistinguishable from not
    being named at all, and naming it costs a sparse element.
    """
    at: list[int] = []
    deltas: list = []
    for index, vertex in enumerate(part.vertices):
        delta = moved.get(vertex.position)
        if delta is not None and any(delta):
            at.append(index)
            deltas.append(delta)
    return Shift(at=at, deltas=deltas)


def _bounds(accessor: dict, deltas: list, whole: bool) -> None:
    """The accessor's `min`/`max`, counting the zeros a sparse target implies.

    ⚠️ A sparse accessor's values are the *deviations*; every vertex it does
    not name still reads as zero, and a bound that ignored them would exclude
    the origin on any target that only pushes one way.
    """
    values = list(deltas) if whole else [*deltas, (0.0, 0.0, 0.0)]
    accessor["min"] = [float(min(d[axis] for d in values)) for axis in range(3)]
    accessor["max"] = [float(max(d[axis] for d in values)) for axis in range(3)]


@dataclass(frozen=True)
class Indexing:
    """The narrowest integer a sparse index array over `count` elements fits."""

    component: int
    width: int
    code: str


def _indexing(count: int) -> Indexing:
    """How to pack one primitive's sparse indices."""
    for limit, component, width in INDEX_WIDTHS:
        if count <= limit:
            return Indexing(component=component, width=width, code="BH"[width - 1])
    return Indexing(component=UNSIGNED_INT, width=4, code="I")


def _sparse_target(blob: _Blob, accessors: list, part: Part, shift: Shift) -> int:
    """One pose's deltas for one primitive, as a sparse accessor.

    ⚠️ **The index and value views carry no `target`.** The specification
    forbids `target` and `byteStride` on a buffer view a sparse accessor reads
    from, and a validator rejects the file outright when they are set.

    `byteOffset` is left out of both where it would be zero: it defaults to
    zero, and at ~15 bytes each it is a real fraction of the record.
    """
    count = len(shift.at)
    index = _indexing(len(part.vertices))
    indices = blob.add(struct.pack(f"<{count}{index.code}", *shift.at))
    values = blob.add(b"".join(struct.pack("<3f", *d) for d in shift.deltas))
    accessor = {
        "componentType": FLOAT,
        "count": len(part.vertices),
        "type": "VEC3",
        "sparse": {
            "count": count,
            "indices": {"bufferView": indices, "componentType": index.component},
            "values": {"bufferView": values},
        },
    }
    _bounds(accessor, shift.deltas, count == len(part.vertices))
    accessors.append(accessor)
    return len(accessors) - 1


def sparse_pays(vertices: int, moved: int) -> bool:
    """Whether a sparse accessor is smaller than the same target written full.

    ⚠️ **Usually it is not, and that is a consequence of the per-shape split.**
    A pose moves a few dozen of a *model's* vertices, but a primitive is one
    shape, so when a pose reaches a primitive at all it tends to move all of
    it: measured over the whole disc, 68% of touched primitive-poses move
    **every** vertex the primitive has, and the mean fill is 0.811 (D238).
    Sparse costs ~100 bytes more of JSON and saves only on what it leaves out.
    """
    index = _indexing(vertices)
    sparse = SPARSE_OVERHEAD + moved * (index.width + TARGET_BYTES)
    return sparse < DENSE_OVERHEAD + vertices * TARGET_BYTES


def _dense_target(blob: _Blob, accessors: list, part: Part, shift: Shift) -> int:
    """The same pose written out in full: a zero triple per vertex it misses."""
    deltas = [(0.0, 0.0, 0.0)] * len(part.vertices)
    for index, delta in zip(shift.at, shift.deltas, strict=True):
        deltas[index] = delta
    view = blob.add(b"".join(struct.pack("<3f", *d) for d in deltas), ARRAY_BUFFER)
    accessor = _accessor(view, len(part.vertices), "VEC3", FLOAT)
    _bounds(accessor, deltas, True)
    accessors.append(accessor)
    return len(accessors) - 1


def _still(vertices: int, view: int | None) -> dict:  # pylint: disable=container-return
    """A target that displaces nothing, over a primitive of `vertices`.

    ⛔ **Sparse cannot express this as a count-0 accessor.**
    `accessor.sparse.count` carries `"minimum": 1` in the specification's
    schema, so a count of zero is an invalid file rather than a free one. An
    accessor with **no `bufferView` and no `sparse`** is what the specification
    defines as zeros — it costs no bytes at all, which is strictly better.
    """
    accessor = {"componentType": FLOAT, "count": vertices, "type": "VEC3"}
    if view is not None:
        accessor["bufferView"] = view
    accessor["min"] = [0.0, 0.0, 0.0]
    accessor["max"] = [0.0, 0.0, 0.0]
    return accessor


def _morph_targets(
    blob: _Blob, accessors: list, parts: list, poses: list, sparse: bool
) -> list:
    # pylint: disable=container-return
    """Every pose's targets, as one accessor-index column per primitive.

    ⚠️ **One shared do-nothing accessor per vertex count, reused by every pose
    that leaves that primitive alone.** glTF requires each primitive to carry
    the same number of targets, and a pose moves one shape out of dozens —
    writing a fresh zero-filled target for the rest gave `p_wii_mario` 23,434
    accessors and a 2.9 MB JSON chunk on a 335-vertex mesh (D236).
    """
    widest = max(len(part.vertices) for part in parts)
    zero = None if sparse else blob.add(b"\0" * (widest * TARGET_BYTES), ARRAY_BUFFER)
    blanks: dict[int, int] = {}
    columns: list[list[int]] = [[] for _ in parts]
    for pose in poses:
        moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
        for at, part in enumerate(parts):
            shift = _shift(part, moved)
            if shift.at:
                write = (
                    _sparse_target
                    if sparse and sparse_pays(len(part.vertices), len(shift.at))
                    else _dense_target
                )
                columns[at].append(write(blob, accessors, part, shift))
                continue
            wide = len(part.vertices)
            if wide not in blanks:
                blanks[wide] = len(accessors)
                accessors.append(_still(wide, zero))
            columns[at].append(blanks[wide])
    return columns


@dataclass(frozen=True)
class Slot:
    """Where one clip's poses sit in the target list every clip shares.

    ⚠️ **glTF has one target list per primitive, not one per animation.** Two
    clips in a file therefore drive the *same* weights, and each has to hold the
    other's targets at zero — which is what `first` and `total` are for.
    """

    first: int
    total: int


def _weight_animation(
    blob: _Blob, accessors: list, poses: list, slot: Slot, name: str
) -> dict:
    # pylint: disable=container-return
    """One pose active at a time, stepping through the clip.

    The game rebuilds the vertex buffer from the model each frame and adds one
    pose's offsets to it, so the poses do not stack — weight 1 for the current
    target and 0 for every other reproduces that.
    """
    times = [float(pose.time) for pose in poses]
    time_view = blob.add(struct.pack(f"<{len(times)}f", *times))
    time_accessor = len(accessors)
    accessors.append(_accessor(time_view, len(times), "SCALAR", FLOAT))
    accessors[-1]["min"] = [min(times)]
    accessors[-1]["max"] = [max(times)]

    weights = []
    for index in range(len(poses)):
        active = slot.first + index
        weights += [1.0 if at == active else 0.0 for at in range(slot.total)]
    weight_view = blob.add(struct.pack(f"<{len(weights)}f", *weights))
    weight_accessor = len(accessors)
    accessors.append(_accessor(weight_view, len(weights), "SCALAR", FLOAT))

    return {
        "name": name,
        "samplers": [
            {
                "input": time_accessor,
                "output": weight_accessor,
                "interpolation": "LINEAR",
            }
        ],
        "channels": [{"sampler": 0, "target": {"node": 0, "path": "weights"}}],
    }


def _morphs(document: dict, blob: _Blob, parts: list, clips: list, sparse: bool) -> None:
    """Every clip's poses as one target list, and one animation per clip.

    A clip with no poses is skipped rather than written as an empty animation:
    a sampler with no keyframes is not loadable, and the caller has already
    counted it.

    ⚠️ **Every primitive gets the same number of targets, in the same order.**
    glTF requires it, and it is what lets the one `weights` array on the mesh
    drive all of them from a single animation channel — one node per shape
    would need a channel and a full weight array each.
    """
    usable = [clip for clip in clips if clip.poses]
    if not usable:
        return
    accessors = document["accessors"]
    poses = [pose for clip in usable for pose in clip.poses]
    columns = _morph_targets(blob, accessors, parts, poses, sparse)

    primitives = document["meshes"][0]["primitives"]
    for primitive, column in zip(primitives, columns, strict=True):
        primitive["targets"] = [{"POSITION": index} for index in column]
    document["meshes"][0]["weights"] = [0.0] * len(poses)

    animations = []
    first = 0
    for clip in usable:
        slot = Slot(first=first, total=len(poses))
        animations.append(_weight_animation(blob, accessors, clip.poses, slot, clip.name))
        first += len(clip.poses)
    document["animations"] = animations


@dataclass(frozen=True)
class ClipCost:
    """What one clip's morph targets add to a file, and how many it adds.

    ⚠️ **`body` is not the whole cost.** Every keyframe also carries a weight
    for every target in the *file*, so a file's weight block is quadratic in
    the total and cannot be attributed to one clip — the caller adds that term
    as it decides what to keep.
    """

    poses: int
    body: int


def costs(mesh, clips: list, sparse: bool = True) -> list:  # pylint: disable=container-return
    """Each clip's target cost, measured by partitioning the way `write` does.

    ⚠️ **Measured, not estimated from the vertex count.** What a target costs
    depends on which primitives the pose reaches and how much of each it moves,
    and the two encodings differ by a factor of ten on the same pose.
    """
    parts = _parts(mesh)
    if not parts:
        return []
    reference = len(parts) * TARGET_REFERENCE
    found = []
    for clip in clips:
        body = 0
        for pose in clip.poses:
            moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
            body += reference
            for part in parts:
                shift = _shift(part, moved)
                if not shift.at:
                    continue
                wide = len(part.vertices)
                if sparse and sparse_pays(wide, len(shift.at)):
                    body += SPARSE_OVERHEAD + len(shift.at) * (
                        _indexing(wide).width + TARGET_BYTES
                    )
                else:
                    body += DENSE_OVERHEAD + wide * TARGET_BYTES
        found.append(ClipCost(poses=len(clip.poses), body=body))
    return found


def weight_cost(targets: int) -> int:
    """What a file's weight arrays cost once it carries `targets` of them.

    ⚠️ **Quadratic.** One keyframe per target, each weighting every target:
    256 targets cost 262 KB, 1,024 cost 4.2 MB, and 2,048 cost 16.8 MB. It is
    the term that decides how many clips a file can hold, not the deltas.
    """
    return targets * targets * WEIGHT_BYTES + targets * WEIGHT_JSON


def _primitive(blob: _Blob, accessors: list, mesh, part: Part) -> dict:
    # pylint: disable=container-return
    """One shape's attributes and indices, as the primitive that draws it."""
    vertices = part.vertices
    positions = [mesh.positions[v.position] for v in vertices]
    payload = b"".join(struct.pack("<3f", *p) for p in positions)

    attributes = {"POSITION": len(accessors)}
    accessor = _accessor(blob.add(payload, ARRAY_BUFFER), len(vertices), "VEC3", FLOAT)
    # ⚠️ Required by the specification on POSITION, and some readers frame the
    # camera from it. Omitting it makes a valid-looking file open empty.
    accessor["min"] = [min(p[i] for p in positions) for i in range(3)]
    accessor["max"] = [max(p[i] for p in positions) for i in range(3)]
    accessors.append(accessor)

    if mesh.normals and all(
        v.normal is not None and v.normal < len(mesh.normals) for v in vertices
    ):
        data = b"".join(struct.pack("<3f", *mesh.normals[v.normal]) for v in vertices)
        attributes["NORMAL"] = len(accessors)
        accessors.append(
            _accessor(blob.add(data, ARRAY_BUFFER), len(vertices), "VEC3", FLOAT)
        )

    # ⚠️ **Asked of this primitive, not of the mesh** (D243). `mesh.is_textured`
    # is false the moment any one shape draws bare, and 269 models mix the two,
    # so gating here on the whole mesh left every one of them unpaintable.
    if mesh.uvs and all(v.uv is not None and v.uv < len(mesh.uvs) for v in vertices):
        data = b"".join(struct.pack("<2f", *mesh.uvs[v.uv]) for v in vertices)
        attributes["TEXCOORD_0"] = len(accessors)
        accessors.append(
            _accessor(blob.add(data, ARRAY_BUFFER), len(vertices), "VEC2", FLOAT)
        )

    view = blob.add(
        struct.pack(f"<{len(part.indices)}I", *part.indices), ELEMENT_ARRAY_BUFFER
    )
    indices = len(accessors)
    accessors.append(_accessor(view, len(part.indices), "SCALAR", UNSIGNED_INT))
    return {"attributes": attributes, "indices": indices}


def _lone(document: dict, blob: _Blob, painted: list, texture: bytes) -> None:
    """One image over every primitive that can carry it.

    ⚠️ **Only for a caller with no layer table at all** -- `bleck model export`
    always has one. It keeps `write(texture=...)` working for a hand-built mesh
    and a single PNG.
    """
    document["images"] = [{"bufferView": blob.add(texture), "mimeType": "image/png"}]
    document["samplers"] = [{"wrapS": gltfpaint.REPEAT, "wrapT": gltfpaint.REPEAT}]
    document["textures"] = [{"sampler": 0, "source": 0}]
    document["materials"] = [
        gltfpaint.material_over(gltfpaint.Surface(image=0), texture=0)
    ]
    for primitive in painted:
        primitive["material"] = 0


def write(  # pylint: disable=too-many-positional-arguments
    mesh,
    texture: bytes = b"",
    name: str = "",
    clips: list | None = None,
    sparse: bool = True,
    paints: list | None = None,
) -> bytes:
    """One mesh as a `.glb`, one primitive per shape.

    ⚠️ Returns bytes rather than writing a file, so a caller can size it,
    checksum it or hand it to a test without touching a disk.

    ⚠️ **`clips` is a list, and the caller decides how long it is.** Every
    entry is another full set of morph targets; nothing here refuses one for
    being large, because only the caller knows the file's budget.

    ⚠️ **Primitives of one mesh, not a node each.** Both split the geometry;
    only this one keeps a single shared `weights` array, so an animation stays
    one channel rather than one per shape (D236).

    `sparse=False` writes every target in full instead — see the note on that
    choice below.
    """
    parts = _parts(mesh)
    if not parts:
        raise ValueError("the mesh has no triangles to write")

    blob = _Blob()
    accessors: list = []
    primitives = [_primitive(blob, accessors, mesh, part) for part in parts]

    document = {
        "asset": {"version": "2.0", "generator": "bleck"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name or mesh.name}],
        "meshes": [{"name": mesh.name, "primitives": primitives}],
        "accessors": accessors,
        "bufferViews": blob.views,
    }

    if paints:
        gltfpaint.paint(document, blob, primitives, parts, paints)
    else:
        painted = [p for p in primitives if "TEXCOORD_0" in p["attributes"]]
        if texture and painted:
            _lone(document, blob, painted, texture)

    if clips:
        _morphs(document, blob, parts, clips, sparse)

    document["buffers"] = [{"byteLength": len(blob.data)}]
    return _container(document, bytes(blob.data))


@dataclass(frozen=True)
class Clip:
    """One animation to write: its name and the poses it steps through."""

    name: str
    poses: list = field(default_factory=list)  # pylint: disable=container-return


@dataclass(frozen=True)
class Painting:
    """What a written `.glb` actually carries, counted from its own bytes."""

    primitives: int
    painted: int
    images: int
    #: How many distinct materials the primitives name. ⚠️ **No longer the same
    #: as `images`.** A two-layer shape's material reaches two of them (D247),
    #: and the viewer's cross-check counts materials rather than pictures.
    materials: int = 0
    #: Materials carrying a second layer in `extras`.
    masked: int = 0

    @property
    def textured(self) -> bool:
        """Whether any primitive in the file resolves to an image."""
        return bool(self.painted)


def parse(blob: bytes) -> dict:  # pylint: disable=container-return
    """The JSON chunk of a `.glb`, parsed the way a reader parses it."""
    at = 12
    while at + 8 <= len(blob):
        length, kind = struct.unpack_from("<II", blob, at)
        if kind == JSON_CHUNK:
            return json.loads(blob[at + 8 : at + 8 + length])
        at += 8 + length
    raise ValueError("the file carries no JSON chunk")


def painting(blob: bytes) -> Painting:
    """How much of a written file a reader will find painted.

    ⚠️ **Read back out of the emission, not taken from what the writer was
    handed** (D245). The manifest reported the images a caller had decoded, so
    ten files counted as textured while every primitive in them drew bare and
    nobody could tell from the manifest.
    """
    parsed = parse(blob)
    primitives = [p for mesh in parsed.get("meshes", []) for p in mesh["primitives"]]
    materials = parsed.get("materials", [])
    return Painting(
        primitives=len(primitives),
        painted=sum(1 for p in primitives if "material" in p),
        images=len(parsed.get("images", [])),
        materials=len(materials),
        masked=sum(1 for m in materials if gltfpaint.MASK_KEY in m.get("extras", {})),
    )


def _container(document: dict, binary: bytes) -> bytes:
    """The 12-byte header and two padded chunks."""
    text = json.dumps(document, separators=(",", ":")).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)

    total = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = bytearray(struct.pack("<III", MAGIC, VERSION, total))
    out += struct.pack("<II", len(text), JSON_CHUNK) + text
    if binary:
        out += struct.pack("<II", len(binary), BIN_CHUNK) + binary
    return bytes(out)
