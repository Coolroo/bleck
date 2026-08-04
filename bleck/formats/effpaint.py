"""Sections 5 and 4: a material's colour register, and a texture's sampler.

`effnode` reads the scene graph and the curves that pose it; this reads the two
records at the far end of the five-hop chain, and the **other two** curve
evaluators that drive them. D266 recorded that `eff_sub.c` inlines the same
loop three times — a material's RGBA, a texture's UV animation, and a node's
transform. Only the third was read until now.

⚠️ **Import direction is one way.** This reads `effcurve` and `effnode`
(section 10's command list lives there); `effdata` reads this. Nothing here may
reach back into `effdata`.

## ✅ The material evaluator, at `0x8005c634` (D281)

```
lhz  r6,0(r10)      entry +0x00 -> material index, section 8 stepped by 8
lwz  r11,20(r21)    section 5
slwi r6,r6,4        stride 16
lha  r6,6(r20)      +0x06 = how many curve commands
lbz  r17..r11,0..3  +0x00..+0x03 = R, G, B, A
stb  ... 88..91(r1) written into a four-byte slot array first
lha  r11,4(r20)     +0x04 = the first command
lwz  r16,40(r21)    section 10, stepped by 8
...
stbx r16,r15,r17    a curve overwrites ONE byte, indexed by its tag
```

✅ **A curve overrides a channel; it does not replace the register.** The four
static bytes are stored into the slot array *before* the loop runs, exactly as
the node evaluator fills its ten slots (D266). A material with only a red curve
keeps its own green, blue and alpha.

⚠️ A `f32` sample is put through `fctiwz` and stored with `stbx`, so it is
truncated toward zero and the low byte kept. All 212 material curves in the
file are `u8` already, so nothing exercises it.

## ✅ The texture evaluator, at `0x8005d040` (D281)

```
lwz  r4,16(r21)     section 4
mulli r3,r0,28      stride 28
lbz  r4,2(r16)      +0x02 -> the texture loader's wrap argument
lha  r0,26(r16)     +0x1A = how many curve commands
lfs  f4..f0,4..20   +0x04, +0x08, +0x0C, +0x10, +0x14
stfs ... 120..136(r1)   a five-float slot array; `addi r20,r1,120` is its base
lha  r3,24(r16)     +0x18 = the first command
stfsx f0,r20,r6     a curve overwrites ONE float, indexed by its tag
```

So the tags are **translate u, translate v, scale u, scale v, rotation** — the
first two and the last matching what D278 inferred from the sample ranges, and
the middle two named outright by the code.

### ✅ The matrix the game then builds

Three blocks, each skipped when it would be the identity, concatenated as
`R · T · S` — so scale first, then translate, then rotate:

| block | built when | `PSMTX` call |
|---|---|---|
| scale | `su != 1` or `sv != 1` | `Scale(su, sv, 1)` |
| translate | `tu != 0` or `tv != 0` or `sv != 0` | `Trans(tu, 1 - tv - sv, 0)` |
| rotate | `rotation != 0` | `T(.5,.5) · RotRad(z, -rot*pi/180) · T(-.5,-.5)` |

⚠️ **The V translation is `1 - tv - sv`, not `tv`.** With the usual `sv == 1`
that is `-tv`, and with the usual `tv == 0` the whole block is the identity —
which is why the default record needs no transform at all. Read it as `+tv` and
every scrolling texture runs backwards.

The constants are read, not guessed: `_SDA2_BASE_` is `0x805B7260` (from
`__init_registers` at `0x80006304`), and the offsets the code uses hold `0.5`,
`-0.5`, `1.0`, `0.0` and `0.01745329` — the last being pi/180.

### ✅ The wrap byte, at `0x8004cb54`

Two bits per axis, mirror winning over the repeat bit:

| bit | meaning |
|---|---|
| 0 | S repeats rather than clamping |
| 1 | T repeats rather than clamping |
| 2 | S mirrors, whatever bit 0 says |
| 3 | T mirrors, whatever bit 1 says |

✅ Measured over the file's 350 texture records: 264 repeat/repeat, 67
clamp/clamp, 16 mirror/mirror, 3 mixed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from bleck.formats.effcurve import curve_at
from bleck.formats.effnode import Command, commands
from bleck.formats.effsections import count_in, section

MATERIAL_SECTION, MATERIAL_STRIDE = 5, 16
TEXTURE_SECTION, TEXTURE_STRIDE = 4, 28

#: Inside a section 5 material record.
MATERIAL_RGBA = 0x00
MATERIAL_CURVES, MATERIAL_CURVE_COUNT = 0x04, 0x06
MATERIAL_TEXTURE = 0x0C

#: Inside a section 4 texture record. `TEXTURE_UV` is five consecutive `f32`.
TEXTURE_IMAGE, TEXTURE_WRAP, TEXTURE_FLAGS = 0x00, 0x02, 0x03
TEXTURE_UV = 0x04
TEXTURE_CURVES, TEXTURE_CURVE_COUNT = 0x18, 0x1A

#: GX's own wrap enum, which is what the game passes to `GXInitTexObj`.
WRAP_CLAMP, WRAP_REPEAT, WRAP_MIRROR = 0, 1, 2

#: What a material's four curve tags drive, in tag order.
MATERIAL_SLOT_NAMES = ("red", "green", "blue", "alpha")

#: What a texture's five curve tags drive, in tag order.
SAMPLER_SLOT_NAMES = (
    "translate.u",
    "translate.v",
    "scale.u",
    "scale.v",
    "rotation",
)

#: The point a UV rotation turns about, in texture coordinates.
ROTATION_CENTRE = 0.5


@dataclass(frozen=True)
class Run:
    """A run of section 10 curve commands, named from one record's two fields.

    ⚠️ **The same table a node's `+0x10`/`+0x12` addresses**, and the three
    claims never overlap: of the file's 4,752 commands, nodes reach 4,447,
    materials 212 and textures 93 — 4,752 with nothing left over (D278).
    """

    first: int
    count: int

    @property
    def is_empty(self) -> bool:
        return self.count <= 0


@dataclass(frozen=True)
class Colour:
    """A material's four channels at some frame, each 0..255."""

    red: int
    green: int
    blue: int
    alpha: int

    @property
    def is_white(self) -> bool:
        """Whether this multiplies every texel by one."""
        return (self.red, self.green, self.blue, self.alpha) == (255, 255, 255, 255)


@dataclass(frozen=True)
class UvTransform:
    """A texture's five UV scalars at some frame. `rotation` is in degrees."""

    translate_u: float
    translate_v: float
    scale_u: float
    scale_v: float
    rotation: float

    @property
    def is_identity(self) -> bool:
        """Whether the game would build no texture matrix at all for this.

        ⚠️ **Not "every field is at its neutral value".** The game skips the
        translate block when `tu`, `tv` and `sv` are *all* zero, and builds it
        otherwise — but with `sv == 1` and `tu == tv == 0` what it builds is a
        translation by nothing. Both routes reach the identity.
        """
        return (
            self.translate_u == 0.0
            and self.translate_v == 0.0
            and self.scale_u == 1.0
            and self.scale_v == 1.0
            and self.rotation == 0.0
        )


@dataclass(frozen=True)
class Material:
    """One section 5 record: a colour register, and the curves that drive it."""

    index: int
    colour: Colour
    texture: int
    """Into section 4, or negative where this material names no texture. ✅ 20
    of the file's 524 carry the documented null."""

    run: Run


@dataclass(frozen=True)
class Sampler:
    """One section 4 record: an image, how it wraps, and its UV transform."""

    index: int
    image: int
    """0..218, an index into `files/eff/effdata.tpl`."""

    wrap: int
    """The raw `+0x02` byte. `wrap_s` and `wrap_t` decode it."""

    flags: int
    """`+0x03`. 🔶 Non-zero on most records and **not applied anywhere** — no
    read of it appears in the evaluator, so what it selects is untested."""

    uv: UvTransform
    run: Run

    @property
    def wrap_s(self) -> int:
        """How the U axis folds, as GX's own enum."""
        if self.wrap & 0x04:
            return WRAP_MIRROR
        return WRAP_REPEAT if self.wrap & 0x01 else WRAP_CLAMP

    @property
    def wrap_t(self) -> int:
        """How the V axis folds, as GX's own enum."""
        if self.wrap & 0x08:
            return WRAP_MIRROR
        return WRAP_REPEAT if self.wrap & 0x02 else WRAP_CLAMP


def material_count(data: bytes) -> int:
    return count_in(data, MATERIAL_SECTION, MATERIAL_STRIDE)


def sampler_count(data: bytes) -> int:
    return count_in(data, TEXTURE_SECTION, TEXTURE_STRIDE)


def material_at(data: bytes, index: int) -> Material | None:
    """One section 5 record, or `None` when the index is outside the section."""
    if not 0 <= index < material_count(data):
        return None
    start, _ = section(data, MATERIAL_SECTION)
    at = start + index * MATERIAL_STRIDE
    first, count = struct.unpack_from(">2h", data, at + MATERIAL_CURVES)
    return Material(
        index=index,
        colour=Colour(*data[at + MATERIAL_RGBA : at + MATERIAL_RGBA + 4]),
        texture=struct.unpack_from(">h", data, at + MATERIAL_TEXTURE)[0],
        run=Run(first, count),
    )


def sampler_at(data: bytes, index: int) -> Sampler | None:
    """One section 4 record, or `None` when the index is outside the section."""
    if not 0 <= index < sampler_count(data):
        return None
    start, _ = section(data, TEXTURE_SECTION)
    at = start + index * TEXTURE_STRIDE
    first, count = struct.unpack_from(">2h", data, at + TEXTURE_CURVES)
    return Sampler(
        index=index,
        image=struct.unpack_from(">h", data, at + TEXTURE_IMAGE)[0],
        wrap=data[at + TEXTURE_WRAP],
        flags=data[at + TEXTURE_FLAGS],
        uv=UvTransform(*struct.unpack_from(">5f", data, at + TEXTURE_UV)),
        run=Run(first, count),
    )


def materials(data: bytes) -> list[Material]:  # pylint: disable=container-return
    """Section 5, in file order."""
    found = [material_at(data, index) for index in range(material_count(data))]
    return [record for record in found if record is not None]


def samplers(data: bytes) -> list[Sampler]:  # pylint: disable=container-return
    """Section 4, in file order."""
    found = [sampler_at(data, index) for index in range(sampler_count(data))]
    return [record for record in found if record is not None]


def run_of(run: Run, every: list[Command]) -> list[Command]:
    # pylint: disable=container-return
    """The commands a record's `(first, count)` names, skipping any out of range.

    ⚠️ **Out of range is skipped, not clamped.** A record naming a run past the
    end of section 10 says nothing about the slots; folding it onto the last
    command would drive the wrong scalar and still look like an answer.
    """
    found = []
    for step in range(max(run.count, 0)):
        at = run.first + step
        if 0 <= at < len(every):
            found.append(every[at])
    return found


def colour_at(data: bytes, index: int, frame: float, every: list[Command]) -> Colour:
    """A material's colour register at `frame`, its own curves applied.

    ✅ **The static register first, then a curve over the top** — the game
    stores the four bytes into its slot array before the loop and a curve
    overwrites one of them by tag. A material with a red curve alone keeps its
    own green, blue and alpha.
    """
    material = material_at(data, index)
    if material is None:
        return Colour(255, 255, 255, 255)
    slots = [
        material.colour.red,
        material.colour.green,
        material.colour.blue,
        material.colour.alpha,
    ]
    for command in run_of(material.run, every):
        if not 0 <= command.tag < len(slots):
            continue
        value = curve_at(data, command.offset).value_at(frame)
        if value is not None:
            # `fctiwz` then `stbx`: truncated toward zero, low byte kept.
            slots[command.tag] = int(value) & 0xFF
    return Colour(*slots)


def uv_at(data: bytes, index: int, frame: float, every: list[Command]) -> UvTransform:
    """A texture's five UV scalars at `frame`, its own curves applied.

    ✅ Same scheme as `colour_at`, on a five-float slot array rather than four
    bytes — the game fills it from `+0x04`..`+0x14` and lets a curve overwrite
    one entry.
    """
    sampler = sampler_at(data, index)
    if sampler is None:
        return UvTransform(0.0, 0.0, 1.0, 1.0, 0.0)
    slots = [
        sampler.uv.translate_u,
        sampler.uv.translate_v,
        sampler.uv.scale_u,
        sampler.uv.scale_v,
        sampler.uv.rotation,
    ]
    for command in run_of(sampler.run, every):
        if not 0 <= command.tag < len(slots):
            continue
        value = curve_at(data, command.offset).value_at(frame)
        if value is not None:
            slots[command.tag] = value
    return UvTransform(*slots)


def command_list(data: bytes) -> list[Command]:  # pylint: disable=container-return
    """Section 10, so a caller evaluating many records reads it once.

    ⚠️ 4,752 commands. `colour_at` and `uv_at` take the list rather than
    reading it, because a per-draw read is 2,960 sweeps of the same section.
    """
    return commands(data)
