"""The scene graph an effect is posed by: sections 9, 6, 12 and 10 of `effdata.dat`.

Split from `effdata` on the same seam `effgeom` and `effcurve` came out on: a
node knows nothing about effects, parts, materials or images. It is a tree of
transforms addressed by absolute index, and `effdata.draws` is what pairs a
part's root node with the artwork the tree reaches.

⚠️ **Import direction is one-way.** `effnode` reads `effsections` and
`effcurve`; `effdata` reads `effnode`. Nothing here may reach back into
`effdata` — an earlier attempt at this split put a node walk on the far side of
that line and the cycle only surfaced at import time, not at lint time.

## ✅ The curves, and how a node is posed (D266)

Section 10 is **4,752 `(u32 tag, u32 offset)` pairs**, the offset relative to
section 2. A node names a **run** of them at `+0x10`/`+0x12`, and the tag picks
one of ten scalars — T.xyz, R.xyz, S.xyz, alpha — which `slots_at` fills from
the node's own static values before letting a curve overwrite one. `effcurve`
holds the record layout; both come from the game's evaluator.

⛔ **The earlier reading of a curve record is superseded**: `+0x06` is the last
frame, not a sample count, and `u8` samples were being read as floats.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from bleck.formats.effcurve import curve_at, product, turn
from bleck.formats.effsections import count_in, section

#: Section 10: `(tag, offset)` pairs addressing section 2.
COMMAND_SECTION = 10
COMMAND_STRIDE = 8

#: Section 9: the nodes themselves.
NODE_SECTION, NODE_STRIDE = 9, 20

#: Section 6: a node's own local transform, as a 3x4 row-major matrix of
#: floats. ✅ Node `+0x06` reaches 1,348 and the section holds exactly 1,349 at
#: this stride -- zero spare, the same exact-fill argument that settled the
#: vertex arrays (D265).
MATRIX_SECTION, MATRIX_STRIDE = 6, 48

#: Section 12: translate, rotate and scale vectors, three floats each. A node's
#: `+0x08`, `+0x0A` and `+0x0C` index it.
VECTOR_SECTION, VECTOR_STRIDE = 12, 12

#: Inside a node record. `sibling` and `child` are **relative to the effect's
#: own base**, not absolute -- resolving them as absolute reaches 649 of 3,739
#: nodes and 73 of 219 images, which is a plausible partial answer and a wrong
#: one (D258).
NODE_SIBLING, NODE_CHILD, NODE_DRAW = 0x00, 0x02, 0x04
NODE_ALPHA, NODE_BILLBOARD = 0x0E, 0x0F

#: Inside a node record, past the three indices above.
NODE_MATRIX, NODE_TRANSLATE, NODE_ROTATE, NODE_SCALE = 0x06, 0x08, 0x0A, 0x0C

#: Section 10 again, reached from the other end: a node names a **run** of
#: curve commands.
NODE_CURVES, NODE_CURVE_COUNT = 0x10, 0x12

#: -1 read as a signed 16-bit value. ⚠️ `effdata.Part.first` is read unsigned,
#: so its null is 0xFFFF rather than -1.
NO_INDEX = -1

#: A node that pointed at itself, or a cycle, would walk forever. The file has
#: 3,739 nodes, so nothing legitimate can visit more than that.
WALK_LIMIT = 4096


@dataclass(frozen=True)
class Command:
    """One `(tag, offset)` pair. What the ten tags mean is unestablished."""

    tag: int
    offset: int
    """Relative to section 2, not to the file."""


def commands(data: bytes) -> list[Command]:  # pylint: disable=container-return
    """Section 10, in file order."""
    start, end = section(data, COMMAND_SECTION)
    return [
        Command(*struct.unpack_from(">II", data, at))
        for at in range(start, end - COMMAND_STRIDE + 1, COMMAND_STRIDE)
    ]


@dataclass(frozen=True)
class Node:
    """One entry of section 9: a scene-graph node under an effect's base.

    ⚠️ `sibling` and `child` are relative to the effect's base node, and
    `draw` is not -- it is an absolute index into section 7.
    """

    index: int
    sibling: int
    child: int
    draw: int
    alpha: int
    billboard: int

    matrix: int = 0
    """Into section 6: this node's local transform, relative to its parent."""

    translate: int = 0
    rotate: int = 0
    scale: int = 0
    """Into section 12. ✅ **The same transform as `matrix`, encoded twice** --
    see `Transform.composed`."""

    curves: int = 0
    count: int = 0
    """A run of section 10 curve commands, evaluated by `slots_at`."""


@dataclass(frozen=True)
class Transform:
    """A 3x4 row-major matrix: three rows of `(x, y, z, translation)`.

    ✅ **Established twice from different bytes** (D265). Section 6 holds it
    outright, and a node's section 12 translate/rotate/scale compose to the same
    thing -- **3,738 of the file's 3,739 nodes agree exactly**, the one exception
    being the last node, whose every index is zero.

    ⚠️ **The rotation is `zyx` in degrees**, and that order is *discriminated*
    rather than merely consistent: 199 nodes rotate on more than one axis, and
    the next-best order matches 3,615 where this one matches 3,738. Nothing here
    needs it — the matrix is used directly, which is the point of checking that
    the two agree — but a caller animating a rotation curve will.
    """

    values: tuple

    @property
    def is_flat(self) -> bool:
        """Whether the transform collapses volume to nothing.

        ⚠️ **44% of the file's drawing nodes are flat in the rest pose**, and 26
        of 139 effects are flat throughout it (D265). That is not a fault: the
        scale is animated up from zero by section 10's curves. It is why
        applying this transform *without* those curves renders less than
        drawing every part at the origin does.
        """
        m = self.values
        determinant = (
            m[0] * (m[5] * m[10] - m[6] * m[9])
            - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8])
        )
        return abs(determinant) < 1e-9

    def then(self, child: Transform) -> Transform:
        """`child` applied first, then this one — parent-to-child accumulation."""
        a, b = self.values, child.values
        out = []
        for row in range(3):
            for col in range(3):
                out.append(sum(a[row * 4 + k] * b[k * 4 + col] for k in range(3)))
            out.append(
                sum(a[row * 4 + k] * b[k * 4 + 3] for k in range(3)) + a[row * 4 + 3]
            )
        return Transform(tuple(out))


#: What no transform at all looks like, and what an effect's root inherits.
IDENTITY = Transform((1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0))


def matrix_at(data: bytes, index: int) -> Transform:
    """One section 6 matrix, or the identity when the index is out of range."""
    start, end = section(data, MATRIX_SECTION)
    at = start + index * MATRIX_STRIDE
    if index < 0 or at + MATRIX_STRIDE > end:
        return IDENTITY
    return Transform(struct.unpack_from(">12f", data, at))


def vector_at(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    """One section 12 vector — a translate, a rotate in degrees, or a scale."""
    start, end = section(data, VECTOR_SECTION)
    at = start + index * VECTOR_STRIDE
    if index < 0 or at + VECTOR_STRIDE > end:
        return (0.0, 0.0, 0.0)
    return struct.unpack_from(">3f", data, at)


def _signed(data: bytes, at: int) -> int:
    return struct.unpack_from(">h", data, at)[0]


def node_count(data: bytes) -> int:
    """How many section 9 nodes the file holds."""
    return count_in(data, NODE_SECTION, NODE_STRIDE)


def node_at(data: bytes, index: int) -> Node:
    """One section 9 node, by absolute index."""
    start, _ = section(data, NODE_SECTION)
    at = start + index * NODE_STRIDE
    return Node(
        index=index,
        sibling=_signed(data, at + NODE_SIBLING),
        child=_signed(data, at + NODE_CHILD),
        draw=_signed(data, at + NODE_DRAW),
        alpha=data[at + NODE_ALPHA],
        billboard=data[at + NODE_BILLBOARD],
        matrix=_signed(data, at + NODE_MATRIX),
        translate=_signed(data, at + NODE_TRANSLATE),
        rotate=_signed(data, at + NODE_ROTATE),
        scale=_signed(data, at + NODE_SCALE),
        curves=struct.unpack_from(">H", data, at + NODE_CURVES)[0],
        count=struct.unpack_from(">H", data, at + NODE_CURVE_COUNT)[0],
    )


#: The ten scalars a node's curves can drive, in tag order. ✅ Read off the
#: game's own slot array at `0x8005f290`, which it fills from the node's static
#: translate, rotate, scale and alpha before letting any curve overwrite a slot.
SLOT_NAMES = (
    "translate.x",
    "translate.y",
    "translate.z",
    "rotate.x",
    "rotate.y",
    "rotate.z",
    "scale.x",
    "scale.y",
    "scale.z",
    "alpha",
)
SLOTS = len(SLOT_NAMES)


def slots_at(data: bytes, index: int, frame: float) -> tuple:
    # pylint: disable=container-return
    """A node's ten scalars at `frame`.

    ✅ **The static TRS first, then curves over the top** — which is what the
    game does, and it matters: a node with one scale curve keeps its *own* other
    two axes rather than falling to zero.
    """
    node = node_at(data, index)
    slots = [
        *vector_at(data, node.translate),
        *vector_at(data, node.rotate),
        *vector_at(data, node.scale),
        float(node.alpha),
    ]
    every = commands(data)
    for step in range(node.count):
        at = node.curves + step
        if not 0 <= at < len(every):
            continue
        command = every[at]
        if not 0 <= command.tag < SLOTS:
            continue
        value = curve_at(data, command.offset).value_at(frame)
        if value is not None:
            slots[command.tag] = value
    return tuple(slots)


def local_at(data: bytes, index: int, frame: float) -> Transform:
    """A node's own transform at `frame`, its curves applied.

    ⚠️ Rotates **z, then y, then x, in degrees** — the order D265 measured
    against section 6's stored matrices, which agree on 3,738 of 3,739 nodes.
    """
    slots = slots_at(data, index, frame)
    spin = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    for which in (2, 1, 0):
        spin = product(spin, turn(which, slots[3 + which]))
    out: list = []
    for row in range(3):
        out.extend(spin[row * 3 + col] * slots[6 + col] for col in range(3))
        out.append(slots[row])
    return Transform(tuple(out))


@dataclass(frozen=True)
class Placed:
    """A node, and where it lands once its parents' transforms are applied."""

    index: int
    world: Transform

    chain: tuple = ()
    """Every node from the part's root down to this one, inclusive.

    ⚠️ Exported so a viewer can pose the node itself, at whatever time it is
    scrubbed to. `world` is one frame's answer; the chain is the question."""


def placed(data: bytes, base: int, root: int, frame: float | None = None) -> list[Placed]:
    # pylint: disable=container-return
    """`root` and everything under it, each with its accumulated transform.

    ⚠️ **The root's own sibling is not followed.** A sibling chain runs on into
    the next part's nodes, so walking it would give one part the artwork of the
    parts after it -- and the result would still be in range, still resolve, and
    still look like an answer.

    `frame` of `None` takes each node's stored section 6 matrix; a number
    evaluates its curves instead. ⛔ **Do not pose an effect from the rest pose
    alone** — 44% of nodes are flat in it (D265).
    """
    total = node_count(data)
    found: list[Placed] = []
    seen: set = set()
    pending = [(root, IDENTITY, ())]
    while pending and len(found) < WALK_LIMIT:
        index, parent, above = pending.pop()
        if not 0 <= index < total or index in seen:
            continue
        seen.add(index)
        node = node_at(data, index)
        own = (
            matrix_at(data, node.matrix)
            if frame is None
            else local_at(data, index, frame)
        )
        here = parent.then(own)
        chain = (*above, index)
        found.append(Placed(index, here, chain))
        cursor = node.child
        while cursor != NO_INDEX and len(found) < WALK_LIMIT:
            absolute = base + cursor
            if not 0 <= absolute < total:
                break
            pending.append((absolute, here, chain))
            cursor = node_at(data, absolute).sibling
    return found
