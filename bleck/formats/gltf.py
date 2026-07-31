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

MAGIC = 0x46546C67
VERSION = 2
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942

#: glTF component types, from the specification's enum.
FLOAT = 5126
UNSIGNED_INT = 5125

#: Buffer view targets. Vertex data and index data are bound differently, and
#: some readers reject a view that does not say which it is.
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963

#: What one dense morph target costs per glTF vertex: three floats of position
#: delta. ⚠️ The whole reason animation needs a budget -- a file's targets are
#: `poses * vertices * 12` bytes, which passes the geometry at three poses.
TARGET_BYTES = 12


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
    per-primitive and dense, so primitives sharing one vertex list would each
    pay for every other primitive's vertices — 92 shapes would cost 92 times
    the animation block. Partitioned, the total is what it always was.
    """

    vertices: list = field(default_factory=list)  # pylint: disable=container-return
    indices: list = field(default_factory=list)  # pylint: disable=container-return


def _weld(mesh, faces: list | None) -> Part:
    """Corners collapsed to unique (position, normal, uv) vertices."""
    order: dict[Vertex, int] = {}
    vertices: list[Vertex] = []
    indices: list[int] = []
    textured = mesh.is_textured
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
            found.append(part)
    return found


def _target(blob: _Blob, accessors: list, part: Part, moved: dict) -> int | None:
    """One pose's deltas for one primitive, or `None` when it moves nothing.

    ⚠️ **Dense, not sparse.** A pose touches a handful of vertices, but glTF's
    sparse accessors are widely half-supported and a target that fails to load
    is worse than one that wastes a few kilobytes.

    ⚠️ Offsets are addressed by *model* vertex, and a glTF vertex is a welded
    (position, normal, uv) triple — so one offset may land on several of them.
    """
    deltas = [moved.get(v.position, (0.0, 0.0, 0.0)) for v in part.vertices]
    if not any(any(value for value in delta) for delta in deltas):
        return None
    view = blob.add(b"".join(struct.pack("<3f", *d) for d in deltas), ARRAY_BUFFER)
    accessor = _accessor(view, len(part.vertices), "VEC3", FLOAT)
    accessor["min"] = [min(d[i] for d in deltas) for i in range(3)]
    accessor["max"] = [max(d[i] for d in deltas) for i in range(3)]
    accessors.append(accessor)
    return len(accessors) - 1


def _still(view: int, vertices: int) -> dict:  # pylint: disable=container-return
    """A target that displaces nothing, over a primitive of `vertices`."""
    accessor = _accessor(view, vertices, "VEC3", FLOAT)
    accessor["min"] = [0.0, 0.0, 0.0]
    accessor["max"] = [0.0, 0.0, 0.0]
    return accessor


def _morph_targets(blob: _Blob, accessors: list, parts: list, poses: list) -> list:
    # pylint: disable=container-return
    """Every pose's targets, as one accessor-index column per primitive.

    ⚠️ **One shared do-nothing accessor per primitive, reused by every pose
    that leaves it alone.** glTF requires each primitive to carry the same
    number of targets, and a pose moves one shape out of dozens — writing a
    fresh zero-filled target for the rest gave `p_wii_mario` 23,434 accessors
    and a 2.9 MB JSON chunk on a 335-vertex mesh (D236).
    """
    widest = max(len(part.vertices) for part in parts)
    zero = blob.add(b"\0" * (widest * TARGET_BYTES), ARRAY_BUFFER)
    blanks: list[int | None] = [None] * len(parts)
    columns: list[list[int]] = [[] for _ in parts]
    for pose in poses:
        moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
        for at, part in enumerate(parts):
            index = _target(blob, accessors, part, moved)
            if index is None:
                if blanks[at] is None:
                    blanks[at] = len(accessors)
                    accessors.append(_still(zero, len(part.vertices)))
                index = blanks[at]
            columns[at].append(index)
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


def _morphs(document: dict, blob: _Blob, parts: list, clips: list) -> None:
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
    columns = _morph_targets(blob, accessors, parts, poses)

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


def vertex_count(mesh) -> int:
    """How many glTF vertices a mesh welds to, across every primitive.

    A dense morph target costs this many times `TARGET_BYTES`, so it is what a
    caller budgeting animation has to divide by. Welding is what decides it —
    the model's own position count is a lower bound, not the answer.
    """
    return sum(len(part.vertices) for part in _parts(mesh))


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

    if mesh.is_textured and all(v.uv is not None for v in vertices):
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


def write(mesh, texture: bytes = b"", name: str = "", clips: list | None = None) -> bytes:
    """One mesh as a `.glb`, one primitive per shape.

    ⚠️ Returns bytes rather than writing a file, so a caller can size it,
    checksum it or hand it to a test without touching a disk.

    ⚠️ **`clips` is a list, and the caller decides how long it is.** Every
    entry is another full set of dense morph targets; nothing here refuses one
    for being large, because only the caller knows the file's budget.

    ⚠️ **Primitives of one mesh, not a node each.** Both split the geometry;
    only this one keeps a single shared `weights` array, so an animation stays
    one channel rather than one per shape (D236).
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

    painted = [p for p in primitives if "TEXCOORD_0" in p["attributes"]]
    if texture and painted:
        image_view = blob.add(texture)
        document["images"] = [{"bufferView": image_view, "mimeType": "image/png"}]
        document["samplers"] = [{"wrapS": 10497, "wrapT": 10497}]
        document["textures"] = [{"sampler": 0, "source": 0}]
        document["materials"] = [
            {
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
                # ⚠️ Game art is cut out with alpha, and the default OPAQUE
                # mode ignores it -- every transparent pixel renders black.
                "alphaMode": "MASK",
                "doubleSided": True,
            }
        ]
        for primitive in painted:
            primitive["material"] = 0

    if clips:
        _morphs(document, blob, parts, clips)

    document["buffers"] = [{"byteLength": len(blob.data)}]
    return _container(document, bytes(blob.data))


@dataclass(frozen=True)
class Clip:
    """One animation to write: its name and the poses it steps through."""

    name: str
    poses: list = field(default_factory=list)  # pylint: disable=container-return


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
