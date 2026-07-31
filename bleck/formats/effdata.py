"""`effdata.dat` — the effect definitions, as far as they are decoded.

The file sits beside `effdata.tpl` (219 images) and holds what the 174 effect
entry points in the DOL are *made of*. Two of its sixteen sections are decoded;
the rest are binary parameter data and are not.

## Layout

```
0x00  16 x u32   section offsets
0x40  "EFDT"     then a build stamp: "Tue Jan 1 10:43:27   2002"
```

| Section | Size | What |
|---|---|---|
| 0 | 6,176 | ✅ **139 effect records**, 44 bytes each |
| 1 | 14,080 | ✅ **704 part records**, 20 bytes each |
| 2 | 619,936 | ✅ **Animation curves**: a 12-byte header then N floats |
| 6 | 64,768 | ✅ **4,048 transform rows**, four floats each |
| 10 | 38,016 | ✅ **4,752 `(tag, offset)` pairs** addressing section 2 |
| 3-5, 7-9, 11-15 | ~700 KB | 🔶 binary; no structure established |

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

⛔ **The remaining sections.** ~700 KB, no strings.

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
    """u16 at +16. Runs 0..238 with 146 distinct values; meaning unestablished."""

    second: int
    """u16 at +18. Runs 1..621 with 55 distinct values. ⛔ **Not** a texture
    index -- there are only 219 images in `effdata.tpl`."""


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
