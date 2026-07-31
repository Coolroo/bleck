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


def _welded(mesh) -> tuple:  # pylint: disable=container-return
    """Corners collapsed to unique (position, normal, uv) vertices."""
    order: dict[Vertex, int] = {}
    vertices: list[Vertex] = []
    indices: list[int] = []
    textured = mesh.is_textured
    for triangle in mesh.corner_triangles():
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
    return vertices, indices


def _morph_targets(blob: _Blob, accessors: list, vertices: list, poses: list) -> list:
    # pylint: disable=container-return
    """Each pose as a dense POSITION-delta target, plus its accessor index.

    ⚠️ **Dense, not sparse.** A pose touches a handful of vertices, but glTF's
    sparse accessors are widely half-supported and a target that fails to load
    is worse than one that wastes a few kilobytes.

    ⚠️ Offsets are addressed by *model* vertex, and a glTF vertex is a welded
    (position, normal, uv) triple — so one offset may land on several of them.
    """
    out = []
    for pose in poses:
        moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
        payload = b"".join(
            struct.pack("<3f", *moved.get(v.position, (0.0, 0.0, 0.0))) for v in vertices
        )
        view = blob.add(payload, ARRAY_BUFFER)
        accessor = _accessor(view, len(vertices), "VEC3", FLOAT)
        deltas = [moved.get(v.position, (0.0, 0.0, 0.0)) for v in vertices]
        accessor["min"] = [min(d[i] for d in deltas) for i in range(3)]
        accessor["max"] = [max(d[i] for d in deltas) for i in range(3)]
        out.append(len(accessors))
        accessors.append(accessor)
    return out


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


def _morphs(document: dict, blob: _Blob, vertices: list, clips: list) -> None:
    """Every clip's poses as one target list, and one animation per clip.

    A clip with no poses is skipped rather than written as an empty animation:
    a sampler with no keyframes is not loadable, and the caller has already
    counted it.
    """
    usable = [clip for clip in clips if clip.poses]
    if not usable:
        return
    accessors = document["accessors"]
    poses = [pose for clip in usable for pose in clip.poses]
    targets = _morph_targets(blob, accessors, vertices, poses)

    primitive = document["meshes"][0]["primitives"][0]
    primitive["targets"] = [{"POSITION": index} for index in targets]
    document["meshes"][0]["weights"] = [0.0] * len(targets)

    animations = []
    first = 0
    for clip in usable:
        slot = Slot(first=first, total=len(targets))
        animations.append(_weight_animation(blob, accessors, clip.poses, slot, clip.name))
        first += len(clip.poses)
    document["animations"] = animations


def vertex_count(mesh) -> int:
    """How many glTF vertices a mesh welds to.

    A dense morph target costs this many times `TARGET_BYTES`, so it is what a
    caller budgeting animation has to divide by. Welding is what decides it —
    the model's own position count is a lower bound, not the answer.
    """
    return len(_welded(mesh)[0])


def write(  # pylint: disable=too-many-locals
    mesh, texture: bytes = b"", name: str = "", clips: list | None = None
) -> bytes:
    """One mesh as a `.glb`, with the texture embedded when there is one.

    ⚠️ Returns bytes rather than writing a file, so a caller can size it,
    checksum it or hand it to a test without touching a disk.

    ⚠️ **`clips` is a list, and the caller decides how long it is.** Every
    entry is another full set of dense morph targets; nothing here refuses one
    for being large, because only the caller knows the file's budget.
    """
    vertices, indices = _welded(mesh)
    if not vertices or not indices:
        raise ValueError("the mesh has no triangles to write")

    blob = _Blob()
    positions = [mesh.positions[v.position] for v in vertices]
    payload = b"".join(struct.pack("<3f", *p) for p in positions)
    position_view = blob.add(payload, ARRAY_BUFFER)

    attributes = {"POSITION": 0}
    accessors = [_accessor(position_view, len(vertices), "VEC3", FLOAT)]
    # ⚠️ Required by the specification on POSITION, and some readers frame the
    # camera from it. Omitting it makes a valid-looking file open empty.
    accessors[0]["min"] = [min(p[i] for p in positions) for i in range(3)]
    accessors[0]["max"] = [max(p[i] for p in positions) for i in range(3)]

    if mesh.normals and all(v.normal is not None for v in vertices):
        usable = [v for v in vertices if v.normal < len(mesh.normals)]
        if len(usable) == len(vertices):
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

    index_view = blob.add(
        struct.pack(f"<{len(indices)}I", *indices), ELEMENT_ARRAY_BUFFER
    )
    index_accessor = len(accessors)
    accessors.append(_accessor(index_view, len(indices), "SCALAR", UNSIGNED_INT))

    document = {
        "asset": {"version": "2.0", "generator": "bleck"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name or mesh.name}],
        "meshes": [
            {
                "name": mesh.name,
                "primitives": [{"attributes": attributes, "indices": index_accessor}],
            }
        ],
        "accessors": accessors,
        "bufferViews": blob.views,
    }

    if texture and "TEXCOORD_0" in attributes:
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
        document["meshes"][0]["primitives"][0]["material"] = 0

    if clips:
        _morphs(document, blob, vertices, clips)

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
