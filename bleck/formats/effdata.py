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
| 2-15 | ~1.3 MB | 🔶 binary; no strings, no structure established |

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

⛔ **Sections 2-15.** 1.3 MB of it, no strings. The third field of each effect
record indexes into that region and is the thread to pull.
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
class Effect:
    """A named effect, and the parts it is assembled from."""

    index: int
    name: str
    first_part: int
    part_count: int
    extra: int
    """A third running index, into the undecoded sections."""

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
