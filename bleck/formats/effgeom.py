"""Section 3 of `effdata.dat`: the GX display lists an effect is drawn from.

Split from `effdata` because it is a self-contained concern — this reads
geometry out of a byte range and knows nothing about effects, parts or the
five-hop chain that reaches a material. `effdata.draws` is what pairs the two.

## ✅ The format (D263, D264)

An effect is **real indexed geometry**, not a billboard:

```
section 8 entry   u16 material - u16 vertex descriptor - u32 display-list offset
section 3 record  u32 size - pad to 32 - GX primitives, for `size` bytes
  primitive       u8 opcode (always 0xA0) - u16 count - count x stride
  vertex          one u16 index per descriptor bit, in GX's attribute order
```

**`stride = 2 * popcount(descriptor & 0x7FFF)`**. Every one of the file's 14,648
primitives is `GX_DRAW_TRIANGLEFAN` at vertex format 0, so `_fan` is the whole of
triangulation rather than one case of it.

✅ **All 360 display lists parse exactly** — each consumes its declared size with
only zero padding left over — for 14,648 primitives and 58,381 vertices, and
**not one index falls outside the array its bit names**.

⚠️ **Two readings that look right and are not.** Ignoring the descriptor and
assuming a 4-byte vertex parses **275 of 360**, with the failures confined to
effects nobody had opened. And reading section 14 at stride 6 as `3 x s16` makes
**738 of 816** entries unit-length against `1/32767` — a coincidence of where the
bytes fall, since 4,896 divides by 3 and not by 6.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: The header is sixteen u32 section offsets.
SECTIONS = 16


def section(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    """Where section `index` starts and ends, clamped to what is really there.

    ⚠️ The last section has no following offset, and a truncated file still
    carries a full section table — so the table's end is a claim, not a fact.
    """
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    end = offsets[index + 1] if index + 1 < SECTIONS else len(data)
    return min(offsets[index], len(data)), min(end, len(data))


def count_in(data: bytes, index: int, stride: int) -> int:
    """How many `stride`-byte entries section `index` holds."""
    start, end = section(data, index)
    return max(end - start, 0) // stride


#: Section 3 holds the GX display lists an entry points at, and sections
#: 11/13/14/15 the arrays a vertex indexes into (D263, D264).
DISPLAY_SECTION = 3
POSITION_SECTION, POSITION_STRIDE = 13, 6
NORMAL_SECTION, NORMAL_STRIDE = 14, 3
COLOUR_SECTION, COLOUR_STRIDE = 15, 4
TEXCOORD_SECTION, TEXCOORD_STRIDE = 11, 8

#: A display list is a `u32` byte count, zero padding up to this boundary, then
#: that many bytes of GX commands. ⚠️ The size counts the commands only.
DISPLAY_ALIGN = 32

#: ✅ Every one of the file's 14,648 primitives is this opcode -- a triangle
#: fan at vertex format 0. No other primitive kind occurs, so `_fan` below is
#: the whole of triangulation rather than one case of it.
TRIANGLE_FAN = 0xA0

#: Bit 15 of a descriptor is a flag, not an attribute: it takes no index, so it
#: must be masked out before the per-vertex stride is counted. ⚠️ Leaving it in
#: reads two bytes too many per vertex and swallows the next opcode.
DESCRIPTOR_ATTRIBUTES = 0x7FFF

#: Which array each descriptor bit indexes, in GX's own attribute order.
#: ✅ Established by fit, not by convention (D264): POS's largest index is
#: 12,247 against section 13's 12,250 entries and TEX0's is 9,065 against
#: section 11's 9,068 -- two entries spare each, where the next-best candidate
#: leaves thousands.
ATTRIBUTE_SECTIONS = {
    0: POSITION_SECTION,
    1: NORMAL_SECTION,
    2: COLOUR_SECTION,
    3: TEXCOORD_SECTION,
}

#: What a section 14 normal's three signed bytes divide by.
#:
#: ✅ **1,632 of 1,632 are unit length** at this scale (D264); raw magnitudes
#: run 126.61 to 128.00. ⚠️ GX's own `GX_S8` normals with seven fractional bits
#: would divide by 128 instead -- a 0.8% difference, and nothing reads these
#: closely enough to tell the two apart.
NORMAL_SCALE = 127.0


@dataclass(frozen=True)
class Vertex:
    """One vertex of an effect primitive, with every array already resolved.

    ⚠️ A vertex carries only the attributes its display list's descriptor names,
    so the rest keep their defaults. 2,494 of the file's 2,960 draws are
    position and texture coordinate alone.
    """

    x: int = 0
    y: int = 0
    z: int = 0
    """Section 13, `3 x s16`, **in the file's own units and not scaled**.
    Dimentio's star spans +/-320; what one unit is in the game's world is not
    established, so nothing here pretends to convert it."""

    u: float = 0.0
    v: float = 0.0
    """Section 11, `2 x f32`."""

    nx: float = 0.0
    ny: float = 0.0
    nz: float = 0.0
    """Section 14, `3 x s8` over `NORMAL_SCALE`."""

    red: int = 255
    green: int = 255
    blue: int = 255
    alpha: int = 255
    """Section 15, `GX_RGBA8`. ⚠️ White rather than zero when the descriptor
    names no colour, because a vertex colour is *modulated* against the
    texture -- defaulting to black would erase the artwork."""


@dataclass(frozen=True)
class Primitive:
    """One GX primitive: an opcode and the vertices it draws."""

    kind: int
    vertices: list[Vertex]

    def triangles(self) -> list[Triangle]:  # pylint: disable=container-return
        """This primitive as triangles.

        ✅ A fan, always -- every primitive in the file is `TRIANGLE_FAN`. A
        future file carrying another kind returns nothing rather than
        triangulating it as a fan and producing plausible wrong geometry.
        """
        if self.kind != TRIANGLE_FAN:
            return []
        return [
            Triangle(self.vertices[0], self.vertices[i], self.vertices[i + 1])
            for i in range(1, len(self.vertices) - 1)
        ]


@dataclass(frozen=True)
class Triangle:
    """Three vertices, wound as the display list gave them."""

    a: Vertex
    b: Vertex
    c: Vertex


@dataclass(frozen=True)
class Mesh:
    """One display list, read as geometry.

    ⚠️ Identified by **offset and descriptor together**. The offset alone is not
    a key: the same bytes read under a different descriptor are different
    geometry, and nothing in the file forbids two entries doing that.
    """

    offset: int
    descriptor: int
    primitives: list[Primitive]

    strays: int = 0
    """How many attribute lookups fell outside the array their bit names.

    ✅ **Zero across all 360 display lists**, and that is the measurement that
    settles `ATTRIBUTE_SECTIONS` rather than GX convention doing it. ⚠️ A
    non-zero count means an array assignment or a stride is wrong: the geometry
    still parses and still renders, missing one attribute per stray, which is a
    failure that looks like success from every other angle."""

    def triangles(self) -> list[Triangle]:  # pylint: disable=container-return
        return [tri for prim in self.primitives for tri in prim.triangles()]


def _attribute(data: bytes, bit: int, index: int, into: dict) -> bool:
    """Resolve one indexed attribute into the fields a `Vertex` is built from.

    ⚠️ Returns whether the index landed inside its array. **A caller must count
    the failures**: falling back to a default silently is how a wrong array
    assignment survives — the geometry still parses, still renders, and is
    quietly missing an attribute. Section 14's stride hid behind exactly that.
    """
    at_section = ATTRIBUTE_SECTIONS.get(bit)
    if at_section is None:
        return False
    start, end = section(data, at_section)
    stride = {
        POSITION_SECTION: POSITION_STRIDE,
        NORMAL_SECTION: NORMAL_STRIDE,
        COLOUR_SECTION: COLOUR_STRIDE,
        TEXCOORD_SECTION: TEXCOORD_STRIDE,
    }[at_section]
    at = start + index * stride
    if index < 0 or at + stride > end:
        return False

    if at_section == POSITION_SECTION:
        into["x"], into["y"], into["z"] = struct.unpack_from(">3h", data, at)
    elif at_section == NORMAL_SECTION:
        raw = struct.unpack_from(">3b", data, at)
        into["nx"], into["ny"], into["nz"] = (v / NORMAL_SCALE for v in raw)
    elif at_section == COLOUR_SECTION:
        into["red"], into["green"], into["blue"], into["alpha"] = struct.unpack_from(
            ">4B", data, at
        )
    else:
        into["u"], into["v"] = struct.unpack_from(">2f", data, at)
    return True


def mesh_at(data: bytes, offset: int, descriptor: int) -> Mesh:
    """The display list at `offset` into section 3, read under `descriptor`.

    ✅ **All 360 of the file's display lists parse exactly** under this reading
    (D263): each consumes its declared size with only zero padding left over,
    for 14,648 primitives and 58,381 vertices.

    A list whose header or commands run past the section stops early and returns
    what it read, rather than raising -- a truncated `effdata.dat` is a damaged
    file, not a reason to refuse the 359 lists around it.
    """
    bits = [b for b in range(15) if descriptor & DESCRIPTOR_ATTRIBUTES & (1 << b)]
    stride = 2 * len(bits)
    start, end = section(data, DISPLAY_SECTION)
    base = start + offset
    found: list[Primitive] = []
    strays = 0
    if offset < 0 or base + DISPLAY_ALIGN > end or not stride:
        return Mesh(offset, descriptor, found)

    size = struct.unpack_from(">I", data, base)[0]
    at, stop = base + DISPLAY_ALIGN, min(base + DISPLAY_ALIGN + size, end)
    while at + 3 <= stop:
        kind = data[at]
        # Zero is the padding that fills out the last aligned block, and any
        # other non-primitive byte means the descriptor was wrong -- either way
        # there is nothing further to read.
        if kind == 0 or kind & 0xF8 != TRIANGLE_FAN:
            break
        count = struct.unpack_from(">H", data, at + 1)[0]
        if at + 3 + count * stride > stop:
            break
        run = _run(data, bits, at + 3, count)
        found.append(Primitive(kind, run.vertices))
        strays += run.strays
        at += 3 + count * stride
    return Mesh(offset, descriptor, found, strays)


@dataclass(frozen=True)
class _Run:
    """One primitive's vertices, and how many of their indices missed."""

    vertices: list[Vertex]
    strays: int


def _run(data: bytes, bits: list[int], at: int, count: int) -> _Run:
    """`count` vertices from `at`, each carrying one index per bit."""
    stride = 2 * len(bits)
    vertices: list[Vertex] = []
    strays = 0
    for n in range(count):
        row = struct.unpack_from(f">{len(bits)}H", data, at + n * stride)
        fields: dict = {}
        for bit, index in zip(bits, row, strict=True):
            strays += not _attribute(data, bit, index, fields)
        vertices.append(Vertex(**fields))
    return _Run(vertices, strays)
