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

## 🔶 What is not known

⛔ **The link from a part to its texture.** The obvious candidate — the u16 at
`+18` — reaches 621 against 219 images, so it is not a TPL index. Until that is
found, this reader can say what an effect is made of but not what it looks like.

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
    """u16 at +16. A **running index** into an undecoded section, not an image.

    ⛔ It reads like a texture index and is not (D210): the parts of one effect
    carry consecutive values -- `chaosA` 0, `chaosC` 1, `chaosD` 2 -- which is
    how `first_part` and `extra` behave, and 14 of 704 parts exceed the 219
    images outright."""

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
    """A third running index, into the undecoded sections."""

    parts: list[Part] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    """Transform rows from `extra` up to the next effect's `extra`."""

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
