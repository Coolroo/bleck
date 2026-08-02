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
| 6 | 64,768 | ✅ **4,048 transform rows**, four floats each |
| 7 | 17,760 | ✅ **2,960 `(start, count, flags)`** records, 6 bytes each |
| 8 | 23,680 | ✅ **2,960 records**, 8 bytes: index, type, kind, offset |
| 10 | 38,016 | ✅ **4,752 `(tag, offset)` pairs** addressing section 2 |
| 3-5, 9, 11-15 | ~650 KB | 🔶 binary; no structure established |

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

⚠️ Two later refutations that this module has **not** yet acted on: section 8's
last four bytes are one u32 display-list offset rather than two u16 (the
"multiple of 32" tell is GX alignment, not a stride), and section 3 is 360 GX
display lists. See D258.

## The curves, and how they are reached

Section 10 is a flat list of **4,752 `(tag, offset)` pairs** — a `u32` tag in
0..9, then a `u32` offset **into section 2**. The largest offset is 619,864
against section 2's 619,936 bytes, which is what says the offsets are relative
to that section rather than absolute.

A section 2 record is a `u32`, two `u16`, a zero `u32`, then `count` floats,
where `count` is the second `u16`. ✅ **1,231 records have exactly that size**,
measured as the gap to the next referenced offset. The rest of the offsets land
*inside* records — a command list pointing at sub-ranges, which is why the naive
"gap = record size" reading only accounts for a third of them.

🟢 **They are plainly curves.** The first record's 60 floats are
`6, 12, 18 ... 354, 360` — a linear ramp to a full rotation, sampled 60 times,
which is one second at 60 fps. ⚠️ The leading `u32` is mostly ≡ 1 (mod 10) and
runs 1..621 with 53 distinct values, the same shape as a part record's second
`u16`; a duration in some unit is the obvious reading and is **not** established.

## Sections 7 and 8, which pair up

Section 7 is 2,960 records of `(u16 start, u16 count, u16 flags)`, and the
start/count chain the same way the effect records do: ✅ **2,958 of 2,959**
consecutive pairs satisfy `start + count == next start`, for an implied total of
2,960. Nearly every count is 1 — eight records break that, which is what makes
the chain visible at all.

Section 8 is **2,960 records of 8 bytes**, the exact count section 7 implies, as
four `u16`:

| field | range | |
|---|---|---|
| 0 | 0..522, 523 distinct | an index into something with 523 entries |
| 1 | 9 distinct values | a type |
| 2 | 0..5 | a small enum |
| 3 | 0..64,960 | ⚠️ **always a multiple of 32** |

⚠️ Field 3 being wholly divisible by 32 is what says it is a byte offset into a
32-byte-strided table, using about 2,030 entries. 🔶 **Which section it targets
is not settled** — 9, 11 and 13 would each be 86-90% filled by it, and none of
those is the tight near-miss that settled section 2 (D195). Guessing between
them on fill alone would be exactly the kind of plausible-and-unchecked
inference this file has avoided so far.

⛔ **The remaining sections.** ~650 KB, no strings.

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


@dataclass(frozen=True)
class Curve:
    """A sampled curve out of section 2.

    ⚠️ `samples` is the whole of what is established. The first record reads
    `6, 12, 18 ... 360` -- a linear ramp to a full rotation over 60 samples,
    one second at 60 fps -- but which curve drives what is not known.
    """

    offset: int
    leading: int
    """The header's first `u32`. Mostly congruent to 1 mod 10, range 1..621.
    🔶 A duration is the obvious reading and is not established."""

    marker: int
    """The first `u16`. Unestablished."""

    samples: tuple

    @property
    def is_monotonic(self) -> bool:
        return all(b >= a for a, b in itertools.pairwise(self.samples))


def commands(data: bytes) -> list[Command]:  # pylint: disable=container-return
    """Section 10, in file order."""
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    start, end = offsets[COMMAND_SECTION], offsets[COMMAND_SECTION + 1]
    return [
        Command(*struct.unpack_from(">II", data, at))
        for at in range(start, end - COMMAND_STRIDE + 1, COMMAND_STRIDE)
    ]


def curve_at(data: bytes, offset: int) -> Curve:
    """One curve record, by its section-2-relative offset."""
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    at = offsets[CURVE_SECTION] + offset
    leading = struct.unpack_from(">I", data, at)[0]
    marker, count = struct.unpack_from(">HH", data, at + 4)
    return Curve(
        offset=offset,
        leading=leading,
        marker=marker,
        samples=struct.unpack_from(f">{count}f", data, at + CURVE_HEADER),
    )


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
    """A section 8 record. Only its shape is established, not its meaning."""

    index: int
    reference: int
    """0..522. Indexes something with 523 entries; which is unknown."""

    kind: int
    """One of nine values."""

    variant: int
    """0..5."""

    offset: int
    """⚠️ Always a multiple of 32, so a byte offset into a 32-byte-strided
    table. 🔶 Which section holds that table is not established."""


def _section(data: bytes, index: int) -> tuple:  # pylint: disable=container-return
    offsets = struct.unpack_from(f">{SECTIONS}I", data, 0)
    return offsets[index], offsets[index + 1]


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
        Entry(index, *struct.unpack_from(">4H", data, at))
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


def _signed(data: bytes, at: int) -> int:
    return struct.unpack_from(">h", data, at)[0]


def _count(data: bytes, section: int, stride: int) -> int:
    start, end = _section(data, section)
    return max(end - start, 0) // stride


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
    )


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


def artwork(data: bytes, effect: Effect, part: Part) -> list[Picture]:
    # pylint: disable=container-return
    """Every image `part` draws, in the order the draw code reaches them.

    ⚠️ **A part draws a set of images, not one.** 560 of 704 parts resolve to
    exactly one, 35 to none -- their materials carry the documented null and the
    geometry is untextured -- and the rest to as many as twelve.

    ⛔ **Do not read the first as "the" image.** `system`'s parts are named
    after their own textures and carry two apiece.
    """
    if part.first == NO_PART:
        return []
    found: list[Picture] = []
    groups_all = groups(data)
    entries_all = entries(data)
    for index in _subtree(data, effect.extra, effect.extra + part.first):
        node = node_at(data, index)
        if not 0 <= node.draw < len(groups_all):
            continue
        group = groups_all[node.draw]
        for entry in entries_all[group.start : group.start + group.count]:
            picture = _picture(data, entry.reference)
            if picture is not None and picture not in found:
                found.append(picture)
    return found
