"""`effdata.dat` — the effect definitions, as far as they are decoded.

The file sits beside `effdata.tpl` (219 images) and holds what the 174 effect
entry points in the DOL are *made of*. Two of its sixteen sections are decoded;
the rest are binary parameter data and are not.

## Layout

```
0x00  16 x u32   section offsets
0x40  "EFDT"     then a build stamp: "Tue Jan 1 10:43:27   2002"
```

⚠️ **On disc those sixteen words are offsets; in memory they are pointers.**
The game rewrites the header in place when it loads the file, so
`header[n] == buffer + offset[n]` for all sixteen (D199, measured live). Anyone
comparing a memory dump against this module's reading will see sixteen numbers
that disagree completely and are the same thing.

| Section | Size | What |
|---|---|---|
| 0 | 6,176 | ✅ **139 effect records**, 44 bytes each |
| 1 | 14,080 | ✅ **704 part records**, 20 bytes each |
| 2 | 619,936 | ✅ **Animation curves**: a 12-byte header then N floats |
| 3 | 350,976 | ✅ **360 GX display lists** (D263) |
| 4 | 9,824 | ✅ **351 texture records**, 28 bytes each |
| 5 | 8,384 | ✅ **524 material records**, 16 bytes each |
| 6 | 64,768 | ✅ **4,048 transform rows**, four floats each |
| 7 | 17,760 | ✅ **2,960 `(start, count, flags)`** records, 6 bytes each |
| 8 | 23,680 | ✅ **2,960 draws**, 8 bytes: material, descriptor, display list |
| 9 | 74,784 | ✅ **3,739 scene-graph nodes**, 20 bytes each |
| 10 | 38,016 | ✅ **4,752 `(tag, offset)` pairs** addressing section 2 |
| 11 | 72,544 | ✅ **9,068 texture coordinates**, `2 x f32` |
| 12 | 16,096 | ✅ **1,006 translate/rotate/scale vectors** |
| 13 | 73,504 | ✅ **12,250 positions**, `3 x s16` |
| 14 | 4,896 | ✅ **1,632 normals**, `3 x s8` (D264) |
| 15 | 224 | ✅ **56 vertex colours**, `GX_RGBA8` (D264) |

### The EFDT block, as the game's own loader reads it

`effSubMain` validates `'E','F','D','T'` byte by byte and then reads exactly two
fields, which is what fixes this layout rather than inferring it (D201):

| | | |
|---|---|---|
| +0x00 | `"EFDT"` | checked one byte at a time |
| +0x04 | build stamp | `"Tue Jan 1 10:43:27   2002"` |
| +0x20 | `u32` = 2 | `lwz`, stored at `effsub_wp+0x08`. A version |
| +0x28 | `u16` = **219** | `lhz`, stored at `effsub_wp+0x14` |
| +0x2C | records begin | which is why `EFFECT_STRIDE` is the header size too |

🟢 **219 is exactly the number of images in `effdata.tpl`.** The game holds a
texture count, so a texture index exists somewhere and is bounded by it — the
first hard constraint on a search that has refuted five candidate fields.

An **effect record** is a 32-byte name then three u32s: the index of its first
part, how many parts it has, and a third running index into something in
sections 2-15 that is not yet identified.

✅ **The part index and count chain exactly**: for all 138 consecutive pairs,
`first + count` lands on the next record's `first`, and the total (704) is
precisely `section 1 size / 20`. Two independent arithmetics agreeing is what
makes this a reading rather than a guess.

A **part record** is a 16-byte name then two u16s.

## ⚠️ The part names are the runtime name fragments

D172 found that the Chaos Heart's effect name is *assembled at runtime* from
pieces — the DOL string table at `0x803293B0` holds `pure_heart`, `chaos`, and
the bare letters `A` `B` `C` `D` `E`. Those letters are **these part names**:

    pure_heart -> parts A B C D E
    chaos      -> parts A C D E

So an effect is a named group of parts, and the game composes `<effect><part>`
when it needs one. That is why no whole name like `chaos_C` appears anywhere on
the disc, and why searching for one found nothing.

## ✅ Which image a part draws — five hops, not a field (D258)

Seven candidates were refuted because they were all looked for *near* the part
record. The reference is five sections away:

```
part +0x10 "first" (s16, 0xFFFF null) + effect +0x28 "extra"
  -> section  9  node      20 bytes   +0x04 -> draw, -1 for none
  -> section  7  draw       6 bytes   start, count
  -> section  8  subdraw    8 bytes   +0x00 -> material
  -> section  5  material  16 bytes   +0x0C -> texture, -1 untextured
  -> section  4  texture   28 bytes   +0x00 =  the effdata.tpl image index
```

✅ **Measured over all 704 parts**: every index lands in 0..218, **all 219
images are referenced and none is orphaned**, and 35 parts resolve to no image
because their materials carry the documented `-1` — not because the walk failed.

⚠️ **A part draws a set, not one image.** Counting distinct images: 560 parts
draw one, 35 none, and the rest up to twelve. `artwork` returns every
`Picture`, so a part that draws one image twice under two tints appears twice;
that is 14 parts, and it is why a count of `Picture`s is not a count of images.

🟢 **`extra` is the effect's base node**, which is what it always was. ⛔ The
`Effect.rows` attachment below reads it as an index into section 6 instead and
is superseded — it predates D258 and is kept only because the viewer's layout
still leans on it. Section 6 is 3x4 matrices reached from a node's `+0x06`.

✅ Both of D258's outstanding refutations are now acted on: section 8's last
four bytes are one `u32` display-list offset, and section 3 is 360 GX display
lists. `draws` returns the geometry alongside the picture; see below.

## ✅ The curves, and how a node is posed (D266)

Section 10 is **4,752 `(u32 tag, u32 offset)` pairs**, the offset relative to
section 2. A node names a **run** of them at `+0x10`/`+0x12`, and the tag picks
one of ten scalars — T.xyz, R.xyz, S.xyz, alpha — which `slots_at` fills from
the node's own static values before letting a curve overwrite one. `effcurve`
holds the record layout; both come from the game's evaluator.

⛔ **The earlier reading of a curve record is superseded**: `+0x06` is the last
frame, not a sample count, and `u8` samples were being read as floats.

## Sections 7 and 8, which pair up

Section 7 is 2,960 records of `(u16 start, u16 count, u16 flags)`, and the
start/count chain the same way the effect records do: ✅ **2,958 of 2,959**
consecutive pairs satisfy `start + count == next start`, for an implied total of
2,960. Nearly every count is 1 — eight break that, which makes the chain visible.

Section 8 is **2,960 records of 8 bytes**, the exact count section 7 implies —
`u16 material`, `u16 vertex descriptor`, `u32 display-list offset` (D263). ⛔ The
four-`u16` reading is superseded: "always a multiple of 32" was taken for a
record stride and is GX display-list alignment, so the last two are one number.

## ✅ The geometry (D263, D264)

An effect is **real indexed geometry**, not a billboard. `mesh_at` reads it and
states the framing; each descriptor bit names an array, and the evidence for
which is the fit:

| bit | attribute | array | evidence |
|---|---|---|---|
| 0 | POS | section 13, `3 x s16` | max index 12,247 of 12,250 |
| 1 | NRM | section 14, `3 x s8` | 1,632 of 1,632 unit length |
| 2 | CLR0 | section 15, `GX_RGBA8` | 49 used, the last 7 zero padding |
| 3 | TEX0 | section 11, `2 x f32` | max index 9,065 of 9,068 |

⚠️ **Two readings that look right and are not.** Ignoring the descriptor and
assuming a 4-byte vertex parses **275 of 360**, with the failures confined to
effects nobody had opened. And reading section 14 at stride 6 as `3 x s16`
makes **738 of 816** entries unit-length against `1/32767`, a coincidence of
where the bytes fall: 4,896 divides by 3, not by 6, and the largest index any
vertex carries is 1,631.

🔶 **One display list is anomalous.** `item_delete`'s is 640 units wide and
58,642 deep, where 359 others are flat or near it. The framing is right — it
consumes its declared size exactly — and why the Z values run to +/-32,000 is
not established.

⚠️ **What a transform row *means* is not established.** They are plainly
geometry -- 42% are unit-length vectors, and `chaos` holds an exact 72-degree
rotation -- but which row is a rotation, which a scale, and how many belong to
one emitter is unknown. The per-effect row counts are not multiples of three, so
they are not simply 3x4 matrices.
"""

from __future__ import annotations

import itertools
import struct
from dataclasses import dataclass, field

from bleck.common.errors import BleckError
from bleck.formats.effcurve import curve_at, product, turn

MAGIC = b"EFDT"

#: The header is sixteen u32 section offsets, then the magic at the first.
SECTIONS = 16
HEADER_SIZE = SECTIONS * 4

EFFECT_STRIDE = 44
EFFECT_NAME = 32
PART_STRIDE = 20
PART_NAME = 16

#: Section 6: four big-endian floats per row. `Effect.extra` indexes it.
TRANSFORM_SECTION = 6
TRANSFORM_STRIDE = 16


class EffectDataError(BleckError):
    """`effdata.dat` could not be read."""


@dataclass(frozen=True)
class Part:
    """One piece of an effect. Its name is a suffix, not a whole name."""

    index: int
    name: str
    first: int
    """u16 at +16. ✅ The part's **root node in section 9** (D258), relative to
    its effect's `extra`. `NO_PART` (0xFFFF) is the null.

    ⛔ It reads like a texture index and is not (D210): the parts of one effect
    carry consecutive values -- `chaosA` 0, `chaosC` 1, `chaosD` 2 -- and 14 of
    704 exceed the 219 images outright. It *reaches* an image five sections
    later; `artwork` walks it."""

    second: int
    """u16 at +18. A **duration in frames**, counted inclusively.

    ✅ 54% of all parts are exactly 1 mod 60, and the commonest values are 61,
    121, 31, 41 and 181 -- one second, two, a half, two thirds, three, at the
    game's 60 Hz (D210). ⛔ Also not a texture index: it reaches 621."""

    @property
    def seconds(self) -> float:
        """How long this part lasts, at 60 Hz. ⚠️ Inclusive, so 61 frames is
        one second rather than 61/60."""
        return max(self.second - 1, 0) / 60.0


@dataclass(frozen=True)
class Row:
    """Four floats from section 6, indexed by an effect's `extra`.

    ⚠️ Geometry, but of an unestablished kind. `chaos` holds an exact 72-degree
    rotation -- 360/5, matching the five-fold ring measured in game (D172,
    D173) -- and 42% of all rows are unit-length. That is enough to say these
    drive placement and not enough to say how.
    """

    index: int
    values: tuple

    @property
    def is_unit(self) -> bool:
        x, y, z = self.values[:3]
        return abs((x * x + y * y + z * z) ** 0.5 - 1.0) < 1e-4


@dataclass(frozen=True)
class Effect:
    """A named effect, and the parts it is assembled from."""

    index: int
    name: str
    first_part: int
    part_count: int
    extra: int
    """✅ The effect's **base node** in section 9 (D258). Every `Part.first`,
    and every node `sibling` and `child`, is measured from here.

    ⛔ Resolving those as absolute indices instead reaches 649 of 3,739 nodes
    and 73 of 219 images -- a plausible partial answer, and a wrong one."""

    parts: list[Part] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    """⛔ **Superseded by D258**, and kept only because the viewer's layout
    still leans on it.

    This slices section 6 by `extra`, which is not an index into section 6 --
    it is the effect's base node in section 9. Section 6 is reached from a
    node's `+0x06` instead, and holds 3x4 matrices rather than four-float rows.
    The floats are real and at real offsets; the **grouping by effect** is the
    part that means nothing."""

    def composed(self) -> list[str]:  # pylint: disable=container-return
        """The names the game builds at runtime: effect plus each part (D172)."""
        return [f"{self.name}{part.name}" for part in self.parts]


def _text(raw: bytes) -> str:
    return raw.split(b"\x00")[0].decode("ascii", "replace")


def read(data: bytes) -> list[Effect]:  # pylint: disable=container-return
    """Every effect and its parts. Sections 2-15 are not touched."""
    if len(data) < HEADER_SIZE:
        raise EffectDataError("too short to hold a section table")
    offsets = list(struct.unpack_from(f">{SECTIONS}I", data, 0))
    if data[offsets[0] : offsets[0] + 4] != MAGIC:
        raise EffectDataError(
            f"no {MAGIC.decode()} magic at {offsets[0]:#x}, so this is not effdata.dat"
        )

    parts = _read_parts(data, offsets[1], offsets[2])
    effects = _read_effects(data, offsets[0], offsets[1], parts)
    return _attach_rows(data, offsets, effects)


def _read_parts(data: bytes, start: int, end: int) -> list[Part]:
    # pylint: disable=container-return
    found: list[Part] = []
    for index, at in enumerate(range(start, end - PART_STRIDE + 1, PART_STRIDE)):
        first, second = struct.unpack_from(">HH", data, at + PART_NAME)
        found.append(Part(index, _text(data[at : at + PART_NAME]), first, second))
    return found


def _read_effects(data: bytes, start: int, end: int, parts: list[Part]) -> list[Effect]:
    # pylint: disable=container-return
    # ⚠️ Records begin after the magic and its build stamp, not at the section
    # offset. The first name sits at a fixed 0x2C past it.
    cursor = start + EFFECT_STRIDE
    found: list[Effect] = []
    while cursor + EFFECT_STRIDE <= end:
        name = _text(data[cursor : cursor + EFFECT_NAME])
        first, count, extra = struct.unpack_from(">3I", data, cursor + EFFECT_NAME)
        if name:
            found.append(
                Effect(
                    index=len(found),
                    name=name,
                    first_part=first,
                    part_count=count,
                    extra=extra,
                    parts=parts[first : first + count],
                )
            )
        cursor += EFFECT_STRIDE
    return found


def chains_cleanly(effects: list[Effect]) -> bool:
    """Whether every record's `first + count` lands on the next record's `first`.

    ⚠️ This is the check that made the layout a reading rather than a guess, so
    it stays callable rather than living only in a test: a future `effdata.dat`
    that fails it is a different format, not a bug in the caller.
    """
    return all(
        this.first_part + this.part_count == following.first_part
        for this, following in itertools.pairwise(effects)
    )


def _read_rows(data: bytes, start: int, end: int) -> list[Row]:
    # pylint: disable=container-return
    return [
        Row(index, struct.unpack_from(">4f", data, at))
        for index, at in enumerate(
            range(start, end - TRANSFORM_STRIDE + 1, TRANSFORM_STRIDE)
        )
    ]


def _attach_rows(data: bytes, offsets: list[int], effects: list[Effect]) -> list[Effect]:
    # pylint: disable=container-return
    """Give each effect the rows between its `extra` and the next one's.

    ⚠️ The span is inferred from the *next* record, because no field states a
    count. The last effect therefore takes everything remaining, which is why
    its row list is far longer than any other and must not be read as meaning
    that effect is enormous.
    """
    start = offsets[TRANSFORM_SECTION]
    end = offsets[TRANSFORM_SECTION + 1]
    rows = _read_rows(data, start, end)

    out: list[Effect] = []
    for index, effect in enumerate(effects):
        stop = effects[index + 1].extra if index + 1 < len(effects) else len(rows)
        out.append(
            Effect(
                index=effect.index,
                name=effect.name,
                first_part=effect.first_part,
                part_count=effect.part_count,
                extra=effect.extra,
                parts=effect.parts,
                rows=rows[effect.extra : stop],
            )
        )
    return out


#: Section 10: `(tag, offset)` pairs addressing section 2.
COMMAND_SECTION = 10
COMMAND_STRIDE = 8

#: Section 2: curve records, reached by those offsets.
CURVE_SECTION = 2
CURVE_HEADER = 12


@dataclass(frozen=True)
class Command:
    """One `(tag, offset)` pair. What the ten tags mean is unestablished."""

    tag: int
    offset: int
    """Relative to section 2, not to the file."""


def commands(data: bytes) -> list[Command]:  # pylint: disable=container-return
    """Section 10, in file order."""
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    start, end = offsets[COMMAND_SECTION], offsets[COMMAND_SECTION + 1]
    return [
        Command(*struct.unpack_from(">II", data, at))
        for at in range(start, end - COMMAND_STRIDE + 1, COMMAND_STRIDE)
    ]


#: Sections 7 and 8, which pair: 7 groups 8's entries by start and count.
GROUP_SECTION, GROUP_STRIDE = 7, 6
ENTRY_SECTION, ENTRY_STRIDE = 8, 8


@dataclass(frozen=True)
class Group:
    """A section 7 record: a run of section 8 entries, plus flags."""

    index: int
    start: int
    count: int
    flags: int


@dataclass(frozen=True)
class Entry:
    """A section 8 record: one draw — a material, and the geometry to draw.

    ✅ **Eight bytes as `u16, u16, u32`** (D263), superseding the four-`u16`
    reading this class used to carry. The last two `u16` are one offset, and
    the "always a multiple of 32" tell was GX display-list alignment rather
    than a record stride.
    """

    index: int
    material: int
    """0..522, an index into section 5. `_picture` resolves it to an image."""

    descriptor: int
    """The GX vertex descriptor: which attributes each vertex of the display
    list carries, one bit each in GX's own order.

    ✅ Nine values occur, and every one is a subset of POS/NRM/CLR0/TEX0 plus
    bit 15 (D263). ⚠️ **Bit 15 is a flag, not an attribute** -- it takes no
    index, so masking it out is what makes the stride come out right."""

    display_list: int
    """Byte offset into section 3, always a multiple of `DISPLAY_ALIGN`.

    ⚠️ 2,960 entries share **360** display lists, so geometry is worth reading
    once and referring to, not once per entry."""


def _section(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    # ⚠️ The last section has no following offset to bound it. Reading one past
    # the table would raise on section 15, which is the vertex colour array and
    # is read below -- so the file's own end is the bound.
    end = offsets[index + 1] if index + 1 < SECTIONS else len(data)
    # ⚠️ Clamped to what is actually there. A truncated file still carries a
    # full section table, so the table's own end is a claim rather than a fact.
    return min(offsets[index], len(data)), min(end, len(data))


def groups(data: bytes) -> list[Group]:  # pylint: disable=container-return
    """Section 7, in file order."""
    start, end = _section(data, GROUP_SECTION)
    return [
        Group(index, *struct.unpack_from(">3H", data, at))
        for index, at in enumerate(range(start, end - GROUP_STRIDE + 1, GROUP_STRIDE))
    ]


def entries(data: bytes) -> list[Entry]:  # pylint: disable=container-return
    """Section 8, in file order. Section 7's start/count addresses these."""
    start, end = _section(data, ENTRY_SECTION)
    return [
        Entry(index, *struct.unpack_from(">HHI", data, at))
        for index, at in enumerate(range(start, end - ENTRY_STRIDE + 1, ENTRY_STRIDE))
    ]


#: Inside the EFDT block, at the start of section 0. Both offsets are the ones
#: `effSubMain` reads immediately after checking the magic (D201).
VERSION_AT = 0x20
TEXTURE_COUNT_AT = 0x28


@dataclass(frozen=True)
class Header:
    """The EFDT block's two meaningful fields, plus its build stamp."""

    version: int
    """`u32` at +0x20. The game stores it at `effsub_wp+0x08`."""

    texture_count: int
    """`u16` at +0x28, stored at `effsub_wp+0x14`.

    🟢 Equals the image count of the matching `effdata.tpl` -- 219 for the main
    set. ⚠️ That is the bound any texture index in this file must respect, and
    the reason five candidate fields reaching 522, 621 and 64,960 are refuted.
    """

    stamp: str


def header(data: bytes) -> Header:
    """The EFDT block, read the way the game's loader reads it."""
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    at = offsets[0]
    if data[at : at + 4] != MAGIC:
        raise EffectDataError(f"no {MAGIC.decode()} magic at {at:#x}")
    return Header(
        version=struct.unpack_from(">I", data, at + VERSION_AT)[0],
        texture_count=struct.unpack_from(">H", data, at + TEXTURE_COUNT_AT)[0],
        stamp=_text(data[at + 4 : at + VERSION_AT]),
    )


#: The five sections between a part and its image (D258). ⚠️ Sections 7 and 8
#: are the `Group` and `Entry` readers above, reached from a different
#: direction: a group is a run of entries, and an entry names a material.
NODE_SECTION, NODE_STRIDE = 9, 20
MATERIAL_SECTION, MATERIAL_STRIDE = 5, 16
TEXTURE_SECTION, TEXTURE_STRIDE = 4, 28

#: Inside a node record. `sibling` and `child` are **relative to the effect's
#: own base**, not absolute -- resolving them as absolute reaches 649 of 3,739
#: nodes and 73 of 219 images, which is a plausible partial answer and a wrong
#: one (D258).
NODE_SIBLING, NODE_CHILD, NODE_DRAW = 0x00, 0x02, 0x04
NODE_ALPHA, NODE_BILLBOARD = 0x0E, 0x0F

#: A material's texture reference, and a texture's image index.
MATERIAL_TEXTURE = 0x0C
TEXTURE_IMAGE, TEXTURE_WRAP = 0x00, 0x02

#: Both nulls are -1 read as a signed 16-bit value. ⚠️ `Part.first` is read
#: unsigned above, so its null is 0xFFFF rather than -1.
NO_INDEX = -1
NO_PART = 0xFFFF

#: A node that pointed at itself, or a cycle, would walk forever. The file has
#: 3,739 nodes, so nothing legitimate can visit more than that.
WALK_LIMIT = 4096


@dataclass(frozen=True)
class Picture:
    """One image a part draws, with how it is sampled and tinted.

    ✅ **The end of the five-hop chain from a part to `effdata.tpl`** (D258):
    part -> node -> draw -> subdraw -> material -> texture -> image. Every hop
    is a fixed offset the draw code loads, and `image` is bounded by the 219 the
    game's own loader reads out of the EFDT header.
    """

    image: int
    """0..218, an index into `files/eff/effdata.tpl`."""

    wrap: int
    """The texture record's `+0x02`. Wrap bits, in the GX sense."""

    red: int
    green: int
    blue: int
    alpha: int
    """The material's own RGBA at `+0x00`, before the node's alpha is folded in."""


#: Section 6: a node's own local transform, as a 3x4 row-major matrix of
#: floats. ✅ Node `+0x06` reaches 1,348 and the section holds exactly 1,349 at
#: this stride -- zero spare, the same exact-fill argument that settled the
#: vertex arrays (D265).
MATRIX_SECTION, MATRIX_STRIDE = 6, 48

#: Section 12: translate, rotate and scale vectors, three floats each. A node's
#: `+0x08`, `+0x0A` and `+0x0C` index it.
VECTOR_SECTION, VECTOR_STRIDE = 12, 12

#: Inside a node record, past the three indices `node_at` already reads.
NODE_MATRIX, NODE_TRANSLATE, NODE_ROTATE, NODE_SCALE = 0x06, 0x08, 0x0A, 0x0C

#: Section 10 again, reached from the other end: a node names a **run** of
#: curve commands. 🔶 What the curves do to a node is not read -- see `Transform`.
NODE_CURVES, NODE_CURVE_COUNT = 0x10, 0x12


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
    """A run of section 10 curve commands. 🔶 Read, and not yet acted on."""


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
    start, end = _section(data, MATRIX_SECTION)
    at = start + index * MATRIX_STRIDE
    if index < 0 or at + MATRIX_STRIDE > end:
        return IDENTITY
    return Transform(struct.unpack_from(">12f", data, at))


def vector_at(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    """One section 12 vector — a translate, a rotate in degrees, or a scale."""
    start, end = _section(data, VECTOR_SECTION)
    at = start + index * VECTOR_STRIDE
    if index < 0 or at + VECTOR_STRIDE > end:
        return (0.0, 0.0, 0.0)
    return struct.unpack_from(">3f", data, at)


def _signed(data: bytes, at: int) -> int:
    return struct.unpack_from(">h", data, at)[0]


def _count(data: bytes, section: int, stride: int) -> int:
    start, end = _section(data, section)
    return max(end - start, 0) // stride


def node_count(data: bytes) -> int:
    """How many section 9 nodes the file holds."""
    return _count(data, NODE_SECTION, NODE_STRIDE)


def node_at(data: bytes, index: int) -> Node:
    """One section 9 node, by absolute index."""
    start, _ = _section(data, NODE_SECTION)
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


def _placed(
    data: bytes, base: int, root: int, frame: float | None = None
) -> list[Placed]:
    # pylint: disable=container-return
    """`root` and everything under it, each with its accumulated transform.

    The same walk as `_subtree` and with the same trap: ⚠️ **the root's own
    sibling is not followed**, because a sibling chain runs on into the next
    part's nodes.
    """
    total = _count(data, NODE_SECTION, NODE_STRIDE)
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


def _subtree(data: bytes, base: int, root: int) -> list[int]:
    # pylint: disable=container-return
    """Absolute node indices of `root` and everything under it.

    ⚠️ **The root's own sibling is not followed.** A sibling chain runs on into
    the next part's nodes, so walking it would give one part the artwork of the
    parts after it -- and the result would still be in range, still resolve, and
    still look like an answer.
    """
    total = _count(data, NODE_SECTION, NODE_STRIDE)
    found: list[int] = []
    pending = [root]
    while pending and len(found) < WALK_LIMIT:
        index = pending.pop()
        if not 0 <= index < total or index in found:
            continue
        found.append(index)
        node = node_at(data, index)
        # Children are relative to the effect's base, and each child's sibling
        # chain belongs to the same subtree.
        cursor = node.child
        while cursor != NO_INDEX and len(found) < WALK_LIMIT:
            absolute = base + cursor
            if not 0 <= absolute < total:
                break
            pending.append(absolute)
            cursor = node_at(data, absolute).sibling
    return found


def _picture(data: bytes, material: int) -> Picture | None:
    """A material's image, or `None` when it names no texture."""
    materials = _count(data, MATERIAL_SECTION, MATERIAL_STRIDE)
    if not 0 <= material < materials:
        return None
    start, _ = _section(data, MATERIAL_SECTION)
    at = start + material * MATERIAL_STRIDE
    reference = _signed(data, at + MATERIAL_TEXTURE)
    textures = _count(data, TEXTURE_SECTION, TEXTURE_STRIDE)
    if not 0 <= reference < textures:
        return None
    texture_start, _ = _section(data, TEXTURE_SECTION)
    texture_at = texture_start + reference * TEXTURE_STRIDE
    return Picture(
        image=_signed(data, texture_at + TEXTURE_IMAGE),
        wrap=data[texture_at + TEXTURE_WRAP],
        red=data[at],
        green=data[at + 1],
        blue=data[at + 2],
        alpha=data[at + 3],
    )


#: The display-list reader lives next door: it needs none of the effect, part
#: or node machinery above, and this module was the repo's first to pass
#: pylint's 1,000-line ceiling. `draws` below is what pairs the two.
from bleck.formats.effgeom import (  # noqa: E402  pylint: disable=wrong-import-position
    Mesh,
    mesh_at,
)


def meshes(data: bytes) -> list[Mesh]:  # pylint: disable=container-return
    """Every distinct display list the entries name, in a stable order.

    ⚠️ **360 meshes for 2,960 entries.** Reading one per entry would be eight
    times the work and eight times the export, for the same geometry.
    """
    wanted = sorted({(entry.display_list, entry.descriptor) for entry in entries(data)})
    return [mesh_at(data, offset, descriptor) for offset, descriptor in wanted]


@dataclass(frozen=True)
class Draw:
    """One section 8 entry resolved: what to draw, and what to draw it with.

    ⚠️ `picture` is `None` for a material naming no texture -- 35 parts are
    untextured and that is a fact about them, not a failed walk. `offset` and
    `descriptor` always name a mesh, because every entry carries geometry.
    """

    picture: Picture | None
    offset: int
    descriptor: int

    chain: tuple = ()
    """Every node from the part's root down to the one that issued this draw.

    ✅ What a viewer needs to pose the draw at an arbitrary time (D266): each
    node in the chain is evaluated at that frame and the results multiplied,
    parent first."""

    world: Transform = IDENTITY
    """Where the issuing node lands once its parents' transforms are applied.

    ⛔ **Do not pose an effect from the rest pose alone.** 44% of nodes are flat
    in the rest pose and 26 of 139 effects are flat throughout it (D265) —
    their scale is animated up from zero by section 10's curves, which are not
    read. Applying this without them renders *less* than drawing every part at
    the origin."""


def draws(
    data: bytes, effect: Effect, part: Part, frame: float | None = None
) -> list[Draw]:
    # pylint: disable=container-return
    """Every draw `part` issues, in the order the draw code reaches them.

    ⚠️ **Not deduplicated.** Two draws sharing a material and differing only in
    geometry are two draws, and collapsing them loses half the shape. `artwork`
    dedupes, because it answers a different question.
    """
    if part.first == NO_PART:
        return []
    found: list[Draw] = []
    groups_all = groups(data)
    entries_all = entries(data)
    for placed in _placed(data, effect.extra, effect.extra + part.first, frame):
        node = node_at(data, placed.index)
        if not 0 <= node.draw < len(groups_all):
            continue
        group = groups_all[node.draw]
        for entry in entries_all[group.start : group.start + group.count]:
            found.append(
                Draw(
                    picture=_picture(data, entry.material),
                    offset=entry.display_list,
                    descriptor=entry.descriptor,
                    chain=placed.chain,
                    world=placed.world,
                )
            )
    return found


def artwork(data: bytes, effect: Effect, part: Part) -> list[Picture]:
    # pylint: disable=container-return
    """Every image `part` draws, in the order the draw code reaches them.

    ⚠️ **A part draws a set of images, not one.** 560 of 704 parts resolve to
    exactly one, 35 to none -- their materials carry the documented null and the
    geometry is untextured -- and the rest to as many as twelve.

    ⛔ **Do not read the first as "the" image.** `system`'s parts are named
    after their own textures and carry two apiece.
    """
    found: list[Picture] = []
    for draw in draws(data, effect, part):
        if draw.picture is not None and draw.picture not in found:
            found.append(draw.picture)
    return found
