"""Morph targets and the animations that drive them, in a `.glb`.

Split from `gltf` on the seam the file itself has: the geometry is written once
and the animation is a separate pass over the same primitives. Nothing here
reads the document beyond the primitive list `apply` is handed, and `gltf` is
the only caller.

## Sparse where sparse is smaller

A pose displaces a few dozen of a *model's* vertices out of hundreds (D217), so
a target can be written as a glTF **sparse accessor**: an index array, a value
array, and zero everywhere else.

⚠️ **This overturns an earlier decision, deliberately.** Targets were written
dense on the grounds that sparse support is patchy across readers and a target
that fails to load is worse than one that wastes a few kilobytes (D217). That
reasoning is not withdrawn — it is outweighed. The dense cost dropped 823 of
3,079 clips from the export, and a clip that was never written cannot fail to
load either. `gltf.write(..., sparse=False)` writes every target in full for a
reader that chokes, and `bleck model export --dense-morphs` reaches it.

⚠️ **Sparse turned out to be the minority case, and it is applied per target
rather than everywhere.** A primitive is one *shape*, so a pose that reaches a
primitive at all usually moves all of it: 68% of touched primitive-poses across
the disc move every vertex the primitive has, and the mean fill is 0.811
(D238). A sparse accessor over those costs more than the dense one it replaces,
so `sparse_pays` decides each target on its own.

⛔ **A pose that misses a primitive is not a count-0 sparse accessor.**
`accessor.sparse.count` carries `"minimum": 1` in the specification's schema.
It is an accessor with no `bufferView` and no `sparse` instead, which the
specification defines as zeros and which occupies no bytes at all.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.gltfcore import (
    ARRAY_BUFFER,
    FLOAT,
    UNSIGNED_BYTE,
    UNSIGNED_INT,
    UNSIGNED_SHORT,
    Blob,
    Part,
    accessor,
    parts,
)

#: The narrowest index type a sparse accessor over `count` elements can use,
#: and how many bytes one of its indices takes. ⚠️ Most primitives after the
#: per-shape split hold a handful of vertices, so this is nearly always one
#: byte -- a `u32` index would cost more than the delta it points at saves.
INDEX_WIDTHS = ((0x100, UNSIGNED_BYTE, 1), (0x10000, UNSIGNED_SHORT, 2))

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


@dataclass(frozen=True)
class Clip:
    """One animation to write: its name and the poses it steps through."""

    name: str
    poses: list = field(default_factory=list)  # pylint: disable=container-return


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


def _bounds(record: dict, deltas: list, whole: bool) -> None:
    """The accessor's `min`/`max`, counting the zeros a sparse target implies.

    ⚠️ A sparse accessor's values are the *deviations*; every vertex it does
    not name still reads as zero, and a bound that ignored them would exclude
    the origin on any target that only pushes one way.
    """
    values = list(deltas) if whole else [*deltas, (0.0, 0.0, 0.0)]
    record["min"] = [float(min(d[axis] for d in values)) for axis in range(3)]
    record["max"] = [float(max(d[axis] for d in values)) for axis in range(3)]


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


def _sparse_target(blob: Blob, accessors: list, part: Part, shift: Shift) -> int:
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
    record = {
        "componentType": FLOAT,
        "count": len(part.vertices),
        "type": "VEC3",
        "sparse": {
            "count": count,
            "indices": {"bufferView": indices, "componentType": index.component},
            "values": {"bufferView": values},
        },
    }
    _bounds(record, shift.deltas, count == len(part.vertices))
    accessors.append(record)
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


def _dense_target(blob: Blob, accessors: list, part: Part, shift: Shift) -> int:
    """The same pose written out in full: a zero triple per vertex it misses."""
    deltas = [(0.0, 0.0, 0.0)] * len(part.vertices)
    for index, delta in zip(shift.at, shift.deltas, strict=True):
        deltas[index] = delta
    view = blob.add(b"".join(struct.pack("<3f", *d) for d in deltas), ARRAY_BUFFER)
    record = accessor(view, len(part.vertices), "VEC3", FLOAT)
    _bounds(record, deltas, True)
    accessors.append(record)
    return len(accessors) - 1


def _still(vertices: int, view: int | None) -> dict:  # pylint: disable=container-return
    """A target that displaces nothing, over a primitive of `vertices`.

    ⛔ **Sparse cannot express this as a count-0 accessor.**
    `accessor.sparse.count` carries `"minimum": 1` in the specification's
    schema, so a count of zero is an invalid file rather than a free one. An
    accessor with **no `bufferView` and no `sparse`** is what the specification
    defines as zeros — it costs no bytes at all, which is strictly better.
    """
    record = {"componentType": FLOAT, "count": vertices, "type": "VEC3"}
    if view is not None:
        record["bufferView"] = view
    record["min"] = [0.0, 0.0, 0.0]
    record["max"] = [0.0, 0.0, 0.0]
    return record


def _morph_targets(
    blob: Blob, accessors: list, primitives: list, poses: list, sparse: bool
) -> list:
    # pylint: disable=container-return
    """Every pose's targets, as one accessor-index column per primitive.

    ⚠️ **One shared do-nothing accessor per vertex count, reused by every pose
    that leaves that primitive alone.** glTF requires each primitive to carry
    the same number of targets, and a pose moves one shape out of dozens —
    writing a fresh zero-filled target for the rest gave `p_wii_mario` 23,434
    accessors and a 2.9 MB JSON chunk on a 335-vertex mesh (D236).

    ⚠️ **A pose that leaves a primitive where the last one did reuses that
    target too**, which is what keeps the cost bearable now poses accumulate
    (D252). A pose holds the whole model's displacement, so once a shape has
    moved its target stops being empty and the blank above never applies to it
    again — but the shape still only *changes* on the poses whose own track
    reaches it, and that is the great majority left unwritten.
    """
    widest = max(len(part.vertices) for part in primitives)
    zero = None if sparse else blob.add(b"\0" * (widest * TARGET_BYTES), ARRAY_BUFFER)
    blanks: dict[int, int] = {}
    columns: list[list[int]] = [[] for _ in primitives]
    held: list = [None] * len(primitives)
    for pose in poses:
        moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
        for at, part in enumerate(primitives):
            shift = _shift(part, moved)
            if held[at] == shift and columns[at]:
                columns[at].append(columns[at][-1])
                continue
            held[at] = shift
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
    """Which shared target each of one clip's keyframes turns on.

    ⚠️ **glTF has one target list per primitive, not one per animation.** Two
    clips in a file therefore drive the *same* weights, and each has to hold the
    other's targets at zero — which is what `total` is for.

    ⚠️ **A keyframe is not a target** (D252). Poses accumulate, so a clip holds
    its shape for a beat whenever a track carries no keys, and 36% of the
    disc's keyframes do. Those repeat the previous target rather than adding
    one, which matters because the weight block is `keys * targets`.
    """

    at: list = field(default_factory=list)  # pylint: disable=container-return
    total: int = 0


@dataclass(frozen=True)
class Slots:
    """Every keyframe's target across a file, and which poses wrote them.

    `at[i]` is the target keyframe *i* turns on; `keep` names, per target, the
    pose it was taken from.
    """

    at: list = field(default_factory=list)  # pylint: disable=container-return
    keep: list = field(default_factory=list)  # pylint: disable=container-return


def _slots(columns: list, poses: int) -> Slots:
    """Fold each run of keyframes that draw the same picture into one target.

    ⚠️ **Consecutive only.** Two poses far apart that happen to match are left
    as two targets: catching those would need every column compared against
    every earlier one, and the runs are what the hold keyframes produce.
    """
    at: list[int] = []
    keep: list[int] = []
    last: tuple | None = None
    for index in range(poses):
        here = tuple(column[index] for column in columns)
        if here != last:
            keep.append(index)
            last = here
        at.append(len(keep) - 1)
    return Slots(at=at, keep=keep)


def _weight_animation(
    blob: Blob, accessors: list, poses: list, slot: Slot, name: str
) -> dict:
    # pylint: disable=container-return
    """One target active at a time, stepping through the clip.

    The game rebuilds the vertex buffer from the model each frame and adds the
    accumulated pose to it, so the targets do not stack — weight 1 for the
    current one and 0 for every other reproduces that.
    """
    times = [float(pose.time) for pose in poses]
    time_view = blob.add(struct.pack(f"<{len(times)}f", *times))
    time_accessor = len(accessors)
    accessors.append(accessor(time_view, len(times), "SCALAR", FLOAT))
    accessors[-1]["min"] = [min(times)]
    accessors[-1]["max"] = [max(times)]

    weights = []
    for active in slot.at:
        weights += [1.0 if at == active else 0.0 for at in range(slot.total)]
    weight_view = blob.add(struct.pack(f"<{len(weights)}f", *weights))
    weight_accessor = len(accessors)
    accessors.append(accessor(weight_view, len(weights), "SCALAR", FLOAT))

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


def apply(
    document: dict, blob: Blob, primitives: list, clips: list, sparse: bool
) -> None:
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
    columns = _morph_targets(blob, accessors, primitives, poses, sparse)
    slots = _slots(columns, len(poses))
    total = len(slots.keep)

    written = document["meshes"][0]["primitives"]
    for primitive, column in zip(written, columns, strict=True):
        primitive["targets"] = [{"POSITION": column[at]} for at in slots.keep]
    document["meshes"][0]["weights"] = [0.0] * total

    animations = []
    first = 0
    for clip in usable:
        slot = Slot(at=slots.at[first : first + len(clip.poses)], total=total)
        animations.append(_weight_animation(blob, accessors, clip.poses, slot, clip.name))
        first += len(clip.poses)
    document["animations"] = animations


@dataclass(frozen=True)
class ClipCost:
    """What one clip's morph targets add to a file, and how many it adds.

    ⚠️ **`body` is not the whole cost.** Every keyframe also carries a weight
    for every target in the *file*, so a file's weight block is `keys *
    targets` and cannot be attributed to one clip — the caller adds that term
    as it decides what to keep.

    ⚠️ **`poses` and `keys` are different numbers** (D252). A hold keyframe
    repeats the target before it, so it lengthens the timeline without adding
    a target.
    """

    poses: int
    body: int
    keys: int = 0


def costs(mesh, clips: list, sparse: bool = True) -> list:  # pylint: disable=container-return
    """Each clip's target cost, measured by partitioning the way `write` does.

    ⚠️ **Measured, not estimated from the vertex count.** What a target costs
    depends on which primitives the pose reaches and how much of each it moves,
    and the two encodings differ by a factor of ten on the same pose.

    ⚠️ **It has to mirror `_morph_targets`' reuse or it prices a fiction.**
    Poses accumulate, so a primitive's target repeats until its own track moves
    again; charging for each repeat overstates a large clip several-fold and
    the budget would drop clips that fit.
    """
    primitives = parts(mesh)
    if not primitives:
        return []
    reference = len(primitives) * TARGET_REFERENCE
    found = []
    for clip in clips:
        body = 0
        held: list = [None] * len(primitives)
        distinct = 0
        for index, pose in enumerate(clip.poses):
            moved = {vertex: (dx, dy, dz) for vertex, dx, dy, dz in pose.offsets}
            fresh = False
            for at, part in enumerate(primitives):
                shift = _shift(part, moved)
                if held[at] == shift and index:
                    continue
                held[at] = shift
                fresh = True
                if not shift.at:
                    continue
                wide = len(part.vertices)
                if sparse and sparse_pays(wide, len(shift.at)):
                    body += SPARSE_OVERHEAD + len(shift.at) * (
                        _indexing(wide).width + TARGET_BYTES
                    )
                else:
                    body += DENSE_OVERHEAD + wide * TARGET_BYTES
            if fresh:
                distinct += 1
                body += reference
        found.append(ClipCost(poses=distinct, body=body, keys=len(clip.poses)))
    return found


def weight_cost(targets: int, keys: int | None = None) -> int:
    """What a file's weight arrays cost once it carries `targets` of them.

    ⚠️ **The dominant term above a few hundred targets**, and it is a product:
    every keyframe carries a weight for every target. 256 targets over 256 keys
    cost 262 KB, 1,024 over 1,024 cost 4.2 MB. It is what decides how many
    clips a file can hold, not the deltas.

    `keys` defaults to `targets`, which is the shape a file has when no clip
    holds a pose for a second beat.
    """
    keys = targets if keys is None else keys
    return keys * targets * WEIGHT_BYTES + targets * WEIGHT_JSON
