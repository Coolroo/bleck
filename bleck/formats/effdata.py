"""`effdata.dat` — the effect definitions, and the walk from a part to its art.

The file sits beside `effdata.tpl` (219 images) and holds what the 174 effect
entry points in the DOL are *made of*.

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

| Section | Size | What | Read by |
|---|---|---|---|
| 0 | 6,176 | ✅ **139 effect records**, 44 bytes each | here |
| 1 | 14,080 | ✅ **704 part records**, 20 bytes each | here |
| 2 | 619,936 | ✅ **Animation curves**: a 12-byte header then N floats | `effcurve` |
| 3 | 350,976 | ✅ **360 GX display lists** (D263) | `effgeom` |
| 4 | 9,824 | ✅ **351 texture records**, 28 bytes each | here |
| 5 | 8,384 | ✅ **524 material records**, 16 bytes each | here |
| 6 | 64,768 | ✅ **1,349 3x4 matrices**, a node's own transform | `effnode` |
| 7 | 17,760 | ✅ **2,960 `(start, count, flags)`** records, 6 bytes each | here |
| 8 | 23,680 | ✅ **2,960 draws**, 8 bytes: material, descriptor, display list | here |
| 9 | 74,784 | ✅ **3,739 scene-graph nodes**, 20 bytes each | `effnode` |
| 10 | 38,016 | ✅ **4,752 `(tag, offset)` pairs** addressing section 2 | `effnode` |
| 11 | 72,544 | ✅ **9,068 texture coordinates**, `2 x f32` | `effgeom` |
| 12 | 16,096 | ✅ **1,006 translate/rotate/scale vectors** | `effnode` |
| 13 | 73,504 | ✅ **12,250 positions**, `3 x s16` | `effgeom` |
| 14 | 4,896 | ✅ **1,632 normals**, `3 x s8` (D264) | `effgeom` |
| 15 | 224 | ✅ **56 vertex colours**, `GX_RGBA8` (D264) | `effgeom` |

Four modules read one file, and the split is by concern rather than by size:
`effsections` answers where a section is, `effgeom` reads display lists,
`effcurve` reads sampled curves, `effnode` walks the scene graph, and this
module holds the effects and parts that address all of it. ⚠️ **The imports run
one way only** — nothing under this module reaches back into it.

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

🟢 **219 is exactly the number of images in `effdata.tpl`** — the bound that
refuted five candidate texture-index fields.

An **effect record** is a 32-byte name then three u32s: its first part, its
part count, and its base node.

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

⚠️ **A part draws a set, not one image**: 560 parts draw one, 35 none, and the
rest up to twelve. 14 draw one image twice under two tints, which is why a
count of `Picture`s is not a count of images.

🟢 **`extra` is the effect's base node**, which is what it always was. ⛔ The
`Effect.rows` view of section 6 that sliced it by `extra` is **deleted** (D270):
section 6 is 1,349 3x4 matrices reached from a node's `+0x06` (D265), and
grouping those floats per effect meant nothing.

✅ Both of D258's outstanding refutations are acted on: section 8's last four
bytes are one `u32` display-list offset, and section 3 is 360 GX display lists.

## The curves, and how a node is posed

`effnode` holds it — sections 9, 6, 12 and 10, and the evaluator that turns them
into a matrix at a frame (D266). `draws` below is what asks it for a pose.

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

An effect is **real indexed geometry**, not a billboard. `effgeom.mesh_at` reads
it and states the framing; each descriptor bit names an array, and the evidence
for which is the fit:

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

"""

from __future__ import annotations

import itertools
import struct
from dataclasses import dataclass, field

from bleck.common.errors import BleckError
from bleck.formats import effgeom, effnode
from bleck.formats.effsections import SECTIONS, count_in, section

MAGIC = b"EFDT"

#: The header is sixteen u32 section offsets, then the magic at the first.
HEADER_SIZE = SECTIONS * 4

EFFECT_STRIDE = 44
EFFECT_NAME = 32
PART_STRIDE = 20
PART_NAME = 16


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
    return _read_effects(data, offsets[0], offsets[1], parts)


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


#: Sections 7 and 8, which pair: 7 groups 8's entries by start and count.
GROUP_SECTION, GROUP_STRIDE = 7, 6
ENTRY_SECTION, ENTRY_STRIDE = 8, 8


#: What a group's `flags` high byte selects, as the switch at `0x8005c9f8`
#: reads it. ✅ Each case is one `GXSetBlendMode` call (D270).
#:
#: ⚠️ **Zero is not a mode.** It falls through the switch, and the mode is then
#: derived from state this reading does not follow — so a viewer should keep
#: doing whatever it did before rather than inventing an opaque default.
BLEND_DERIVED = 0
BLEND_ADD = 4
BLEND_SUBTRACT = 5
BLEND_INVERSE = 6


@dataclass(frozen=True)
class Group:
    """A section 7 record: a run of section 8 entries, plus flags."""

    index: int
    start: int
    count: int
    flags: int

    @property
    def blend(self) -> int:
        """How this draw is composited — the flags' **high byte** (D270).

        ✅ 0, 4, 5 and 6 occur, and every one is a case of the game's own
        `GXSetBlendMode` switch. 🟢 The semantic check: mode 4 is additive, and
        the effects using it are `explosion`, `dmen_explosion`, `event_fire`,
        `event_enmagic`, `chaos_start` and `fairyn_get` — glows and flashes,
        every one. Nothing incongruous is in the set.
        """
        return (self.flags >> 8) & 0xFF


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


def groups(data: bytes) -> list[Group]:  # pylint: disable=container-return
    """Section 7, in file order."""
    start, end = section(data, GROUP_SECTION)
    return [
        Group(index, *struct.unpack_from(">3H", data, at))
        for index, at in enumerate(range(start, end - GROUP_STRIDE + 1, GROUP_STRIDE))
    ]


def entries(data: bytes) -> list[Entry]:  # pylint: disable=container-return
    """Section 8, in file order. Section 7's start/count addresses these."""
    start, end = section(data, ENTRY_SECTION)
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


#: The material and texture sections the five-hop chain ends in (D258).
#: ⚠️ Sections 7, 8 and 9 are the other three hops, and each is read from a
#: different direction: a node names a group, a group is a run of entries, and
#: an entry names one of these materials.
MATERIAL_SECTION, MATERIAL_STRIDE = 5, 16
TEXTURE_SECTION, TEXTURE_STRIDE = 4, 28

#: A material's texture reference, and a texture's image index.
MATERIAL_TEXTURE = 0x0C
TEXTURE_IMAGE, TEXTURE_WRAP = 0x00, 0x02

#: ⚠️ `Part.first` is read unsigned, so its null is 0xFFFF rather than the -1
#: `effnode.NO_INDEX` uses for a node reference.
NO_PART = 0xFFFF


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


def _signed(data: bytes, at: int) -> int:
    return struct.unpack_from(">h", data, at)[0]


def _picture(data: bytes, material: int) -> Picture | None:
    """A material's image, or `None` when it names no texture."""
    materials = count_in(data, MATERIAL_SECTION, MATERIAL_STRIDE)
    if not 0 <= material < materials:
        return None
    start, _ = section(data, MATERIAL_SECTION)
    at = start + material * MATERIAL_STRIDE
    reference = _signed(data, at + MATERIAL_TEXTURE)
    textures = count_in(data, TEXTURE_SECTION, TEXTURE_STRIDE)
    if not 0 <= reference < textures:
        return None
    texture_start, _ = section(data, TEXTURE_SECTION)
    texture_at = texture_start + reference * TEXTURE_STRIDE
    return Picture(
        image=_signed(data, texture_at + TEXTURE_IMAGE),
        wrap=data[texture_at + TEXTURE_WRAP],
        red=data[at],
        green=data[at + 1],
        blue=data[at + 2],
        alpha=data[at + 3],
    )


def meshes(data: bytes) -> list[effgeom.Mesh]:  # pylint: disable=container-return
    """Every distinct display list the entries name, in a stable order.

    ⚠️ **360 meshes for 2,960 entries.** Reading one per entry would be eight
    times the work and eight times the export, for the same geometry.
    """
    wanted = sorted({(entry.display_list, entry.descriptor) for entry in entries(data)})
    return [effgeom.mesh_at(data, offset, descriptor) for offset, descriptor in wanted]


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

    blend: int = BLEND_DERIVED
    """How to composite this draw — see `Group.blend`."""

    chain: tuple = ()
    """Every node from the part's root down to the one that issued this draw.

    ✅ What a viewer needs to pose the draw at an arbitrary time (D266): each
    node in the chain is evaluated at that frame and the results multiplied,
    parent first."""

    world: effnode.Transform = effnode.IDENTITY
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
    for placed in effnode.placed(data, effect.extra, effect.extra + part.first, frame):
        node = effnode.node_at(data, placed.index)
        if not 0 <= node.draw < len(groups_all):
            continue
        group = groups_all[node.draw]
        for entry in entries_all[group.start : group.start + group.count]:
            found.append(
                Draw(
                    picture=_picture(data, entry.material),
                    offset=entry.display_list,
                    descriptor=entry.descriptor,
                    blend=group.blend,
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
