"""The scene graph's visibility flags — slot 20, keyed by slot 22's shapes.

Split from `modelarrays`, which owns the vertex arrays: this reads two other
slots of the same section table and answers one question — which shapes does the
file say to draw?

⚠️ **`model-format.md` called slot 20 "32 bytes of `01`", unread** (D287 left it
so). It is a `u8` for every node, padded to a multiple of four, and `0` means
the node is off. Slot 22's node record names the shape each node draws, so the
two together give the shapes a viewer should hide.

⛔ **The game has not been read.** That the file carries the flag is measured on
869 of 870 models; that the game obeys it is not, which is the same limit D287
records for slots 21 and 22. Treat a hidden shape as the file's own statement,
not as proven runtime behaviour.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import SHAPE_SECTIONS_AT

#: Slots of the section table at `0x150` this module reads.
VISIBILITY_SLOT = 20
NODE_SLOT = 22
SLOTS_NEEDED = 24

#: One slot-22 node record. Its `+0x48` is the shape the node draws, or `-1`
#: for a node that only groups others (D287).
NODE_STRIDE = 88
NODE_SHAPE_AT = 0x48

#: What a clear visibility byte means, and the only other value seen. ⚠️ Across
#: all 869 readable models the unpadded region holds **nothing but 0 and 1**.
NODE_OFF = 0


@dataclass(frozen=True)
class Visibility:
    """Which shapes the file says to hide, and what it was read from.

    `hidden` holds **shape indices**, not node indices — a node that draws
    nothing cannot be hidden, and several nodes never share one shape on this
    disc.
    """

    hidden: frozenset = field(default_factory=frozenset)
    nodes: int = 0
    #: Nodes whose byte is clear, including ones that draw no shape. ⚠️ Larger
    #: than `len(hidden)`: 2,560 nodes are off corpus-wide but only 2,427 of
    #: them draw anything.
    off: int = 0

    @property
    def read(self) -> bool:
        """Whether the two tables were both present and agreed on a count."""
        return self.nodes > 0

    def describe(self) -> str:
        return f"{len(self.hidden)} hidden of {self.nodes} node(s)"


def _padded(nodes: int) -> int:
    """The slot-20 length a node count implies: one byte each, aligned to 4."""
    return (nodes + 3) // 4 * 4


def visibility(data: bytes) -> Visibility:
    """Which shape indices slot 20 marks as off.

    Degrades to an empty answer rather than raising. A model whose two tables
    disagree on a count is one this reading does not describe, and dropping its
    geometry would be worse than showing every shape — which is what every
    export did before this existed.
    """
    if len(data) < SHAPE_SECTIONS_AT + SLOTS_NEEDED * 4:
        return Visibility()
    table = struct.unpack_from(f">{SLOTS_NEEDED}I", data, SHAPE_SECTIONS_AT)
    start, after = table[VISIBILITY_SLOT], table[VISIBILITY_SLOT + 1]
    nodes_at, nodes_end = table[NODE_SLOT], table[NODE_SLOT + 1]
    if not 0 < start <= after <= len(data):
        return Visibility()
    if not 0 < nodes_at <= nodes_end <= len(data):
        return Visibility()

    nodes = (nodes_end - nodes_at) // NODE_STRIDE
    flags = data[start:after]
    if nodes <= 0 or len(flags) != _padded(nodes):
        return Visibility()

    hidden: set[int] = set()
    off = 0
    for index in range(nodes):
        if flags[index] != NODE_OFF:
            continue
        off += 1
        at = nodes_at + index * NODE_STRIDE + NODE_SHAPE_AT
        shape = struct.unpack_from(">i", data, at)[0]
        if shape >= 0:
            hidden.add(shape)
    return Visibility(hidden=frozenset(hidden), nodes=nodes, off=off)
