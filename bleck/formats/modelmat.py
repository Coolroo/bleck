"""Which image each shape draws with, read off the chain the draw code walks.

The third piece of the geometry reader: `modelmesh` reads the vertex arrays,
`modelrebase` decides which slice of them a shape indexes, and this decides
which picture goes on the result.

✅ **Every step is stated by the file** (D243). The draw loop at `0x80047f00`
steps a shape record, reads its layer count from `+0x00` and the layer indices
from `+0x10`, and hands them to `0x8004729c`:

    lwz   r3, 0(r29)        ; shape +0x00 -> how many texture layers
    addi  r4, r29, 16       ; shape +0x10 -> the layer indices
    lwz   r5, 404(r8)       ; +0x194 (slot 17) -> 8-byte layer records
    lwz   r7, 308(r8)       ; +0x134 -> how many materials there are
    lwz   r8, 408(r8)       ; +0x198 (slot 18) -> 64-byte material records

and inside it:

    lwzx  r3, r26, r0       ; indices[count - i - 1]
    lwzx  r7, r27, r3       ; slot 17 [idx] -> a material index
    lbzx  r6, r24, r0       ; plus a runtime animation offset
    add   r21, r7, r6
    mulli r0, r21, 64       ; -> slot 18, the material record
    lwz   r20, 4(r5)        ; its index in the bank beside the file
    bl    0x802e3200        ; look that up, then GXInitTexObj/GXLoadTexObj

⛔ **D229 said this was undecoded and is superseded.** Three candidate bindings
were refuted there — shape *i* to image *i*, the slot-17 table read as a
per-shape array, and a material index in the face record — and all three failed
because they skipped the indirection: a shape names a *layer*, a layer names a
*material*, and only the material names the image.

⚠️ **The layer indices are stored in reverse of GX texture-map order.** The
loop reads `indices[count - i - 1]` and binds it to map *i*, so the last stored
index is `GX_TEXMAP0`. `Binding.images` is already in map order.

## How a layer is sampled

✅ **Slot 17 `+0x04` is the wrap mode** (D247), and `0x8004729c` spells the
mapping out before it calls `GXInitTexObj`:

    cmpwi   r18,0                   ; the flag, below zero -> keep the image's
    blt     keep                    ;   own GXInitTexObj defaults
    rlwinm. r0,r18,0,29,29          ; bit 2 -> wrap_s = GX_MIRROR
    clrlwi  r20,r18,31              ; else   wrap_s = bit 0 (CLAMP / REPEAT)
    rlwinm. r0,r18,0,28,28          ; bit 3 -> wrap_t = GX_MIRROR
    rlwinm  r21,r18,31,31,31        ; else   wrap_t = bit 1

✅ **Slot 16 is a 24-byte record per layer**, 1:1 with slot 17 on all 870
models. `+0x00` is the frame offset added to the material index -- the byte
`lbzx r6, r24, r0` picks up, which is how a texture animates -- and the five
floats after it are a UV transform the draw code composes as `R * T * S`.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import SHAPE_SECTIONS_AT, text

#: Slot 17: one 8-byte record per layer. `+0x00` is the material index a layer
#: resolves to; a runtime byte is added to it, which is how a texture animates
#: without the file changing. `+0x04` is the wrap mode, decoded by `Wrap.of`.
LAYER_SLOT = 17
LAYER_STRIDE = 8
LAYER_MATERIAL_AT = 0x00
LAYER_WRAP_AT = 0x04

#: `GXTexWrapMode`, as `GXInitTexObj` takes it.
CLAMP = 0
REPEAT = 1
MIRROR = 2

#: What slot 17 `+0x04` means. Bits 0 and 1 choose CLAMP or REPEAT for S and T;
#: bits 2 and 3 override either with MIRROR. ⛔ **A negative word is not a
#: mode** -- the draw code leaves the `GXTexObj` defaults alone for it. Nothing
#: on the disc is negative, so that branch is unexercised here.
WRAP_DEFAULT = -1
WRAP_S_BIT = 0x1
WRAP_T_BIT = 0x2
WRAP_S_MIRROR = 0x4
WRAP_T_MIRROR = 0x8

#: Slot 16: 24 bytes per layer. `+0x00` is a `u8` frame offset and the rest is
#: the UV transform, in the order the draw code reads them.
TRANSFORM_SLOT = 16
TRANSFORM_STRIDE = 24
TRANSFORM_FRAMES_AT = 0x00
TRANSFORM_TRANSLATE_AT = 0x04
TRANSFORM_SCALE_AT = 0x0C
TRANSFORM_ROTATION_AT = 0x14

#: The game rotates a texture about the middle of the image, not its corner:
#: `MTXTrans(0.5, 0.5)` and `MTXTrans(-0.5, -0.5)` bracket the `MTXRotRad`.
UV_CENTRE = 0.5

#: Slot 18: one 64-byte material record. `+0x04` is the image's index in the
#: TPL bank beside the file and `+0x0C` the source art it was made from --
#: `ara/enemy/luigi_robo/tex/boushi1.tga`. ⚠️ Those paths are what
#: `model.TEXTURE_RE` has always scraped; the record is where they live.
MATERIAL_SLOT = 18
MATERIAL_STRIDE = 64
MATERIAL_IMAGE_AT = 0x04
MATERIAL_PATH_AT = 0x0C

#: Slot 19's 108-byte shape record, from this module's side of it.
#: `modelrebase` reads the same record for the face span and the corner
#: offsets. `+0x00` counts the shape's texture layers -- ⛔ **not a boolean**,
#: which is how it was read before: 0, 1 and 2 all occur.
RECORD_SLOT = 19
RECORD_STRIDE = 108
RECORD_LAYERS_AT = 0x00
RECORD_LAYERS_FROM = 0x10
RECORD_LAYERS = 8
NO_LAYER = -1

#: Three counts the header states outright, immediately before the section
#: table: layers, materials, shapes. ✅ They agree with the section strides on
#: all 870 models, which is what makes the strides a reading rather than a fit.
COUNTS_AT = 0x130


@dataclass(frozen=True)
class Material:
    """One image a model can draw with."""

    #: Where it sits in the TPL bank beside the file.
    index: int
    #: The source art it was made from, as the exporter recorded it.
    path: str


@dataclass(frozen=True)
class Pair:
    """Two numbers in texture-coordinate space, named so neither is a guess."""

    u: float
    v: float


@dataclass(frozen=True)
class Wrap:
    """What happens to a coordinate outside the image, per axis.

    ✅ **Read, not assumed** (D247). Both axes were written as REPEAT for as
    long as the exporter had samplers at all, and the disc is overwhelmingly
    the other way: 6,719 of its 7,300 layers clamp on both axes.
    """

    s: int = CLAMP
    t: int = CLAMP

    @classmethod
    def of(cls, flag: int) -> Wrap:
        """Slot 17 `+0x04`, decoded the way `0x8004729c` decodes it."""
        if flag < 0:
            return cls(s=WRAP_DEFAULT, t=WRAP_DEFAULT)
        return cls(
            s=MIRROR if flag & WRAP_S_MIRROR else flag & WRAP_S_BIT,
            t=MIRROR if flag & WRAP_T_MIRROR else (flag & WRAP_T_BIT) >> 1,
        )


@dataclass(frozen=True)
class Transform:
    """A layer's UV transform, as the five floats the file states.

    The draw code builds up to three matrices and concatenates whichever are
    not the identity, always in the order `rotate * translate * scale`. Only
    the rotation is bracketed by the half-unit shift, so a layer that does not
    rotate translates about the corner and one that does rotates about the
    middle.

    ⚠️ **The V translation is not the stored field.** The code computes
    `1 - translate_v - scale_v`, so an unrotated layer at the defaults comes out
    at zero rather than one.
    """

    translate_u: float = 0.0
    translate_v: float = 0.0
    scale_u: float = 1.0
    scale_v: float = 1.0
    #: Degrees. `MTXRotRad` is handed `-rotation * pi / 180`.
    rotation: float = 0.0

    @property
    def turns(self) -> bool:
        """Whether the rotation matrix is built at all."""
        return self.rotation != 0.0

    @property
    def shifts(self) -> bool:
        """Whether the translation matrix is built at all.

        ⚠️ **`scale_v` is one of the three fields tested**, which is why the
        default record still takes this branch — and why the translation it
        builds is `(0, 0)` rather than `(0, 1)`.
        """
        return (self.translate_u, self.translate_v, self.scale_v) != (0.0, 0.0, 0.0)

    @property
    def stretches(self) -> bool:
        """Whether the scale matrix is built at all."""
        return (self.scale_u, self.scale_v) != (1.0, 1.0)

    @property
    def scale(self) -> Pair:
        return Pair(u=self.scale_u, v=self.scale_v) if self.stretches else Pair(1.0, 1.0)

    @property
    def radians(self) -> float:
        """The rotation as `KHR_texture_transform` states it.

        ✅ The sign is read off `MTXRotRad`, disassembled: its Z matrix is
        `[[cos, -sin], [sin, cos]]` and it is handed `-rotation * pi / 180`, so
        the composed matrix is the extension's own `[[cos r, sin r], [-sin r,
        cos r]]` at `r = radians(rotation)`.
        """
        return math.radians(self.rotation) if self.turns else 0.0

    @property
    def offset(self) -> Pair:
        """The translation left over once the rotation is about the origin.

        The file's matrix is `T(0.5) * R * T(-0.5) * T(shift) * S`. Moving the
        rotation out to the origin turns the two inner translations into one,
        which is what `KHR_texture_transform` takes.
        """
        shift = Pair(
            u=self.translate_u if self.shifts else 0.0,
            v=1.0 - self.translate_v - self.scale_v if self.shifts else 0.0,
        )
        if not self.turns:
            return shift
        angle = -math.radians(self.rotation)
        away_u, away_v = shift.u - UV_CENTRE, shift.v - UV_CENTRE
        return Pair(
            u=UV_CENTRE + math.cos(angle) * away_u - math.sin(angle) * away_v,
            v=UV_CENTRE + math.sin(angle) * away_u + math.cos(angle) * away_v,
        )

    @property
    def is_identity(self) -> bool:
        """Whether the composed matrix leaves every coordinate where it is.

        ⚠️ Asked of the *result*, not of the fields. The default record builds
        a translation matrix and it is the identity anyway, so testing the
        branches would call 7,170 layers transformed.
        """
        return (
            self.offset == Pair(0.0, 0.0)
            and self.scale == Pair(1.0, 1.0)
            and self.radians == 0.0
        )


@dataclass(frozen=True)
class Layer:
    """One texture layer: which material it draws, and how it is sampled."""

    material: int
    wrap: Wrap = field(default_factory=Wrap)
    transform: Transform = field(default_factory=Transform)
    #: Slot 16 `+0x00`: added to `material` at runtime to step an animation.
    #: A static export takes offset zero, which is frame one.
    frames: int = 0


@dataclass(frozen=True)
class Binding:
    """The layers one shape draws with, in GX texture-map order.

    Empty for a shape that draws with no texture at all -- 4,319 of the disc's
    19,022 shapes, which is why "is this model textured" was always the wrong
    question to ask once (D240).
    """

    layers: list = field(default_factory=list)  # pylint: disable=container-return

    @property
    def images(self) -> list:  # pylint: disable=container-return
        """Just the material indices, for a caller that wants no more.

        ⚠️ **Derived, not stored beside `layers`.** Two lists that have to stay
        the same length is the shape D246 rejected in the viewer.
        """
        return [layer.material for layer in self.layers]


@dataclass(frozen=True)
class Palette:
    """A model's images, and which of them each shape draws with.

    The two travel together because neither settles anything alone: a binding
    is a list of indices into `images`, and an index without the list it
    indexes cannot name a picture.
    """

    images: list = field(default_factory=list)  # pylint: disable=container-return
    shapes: list = field(default_factory=list)  # pylint: disable=container-return


@dataclass(frozen=True)
class Table:
    """Where one section starts and how many fixed-size records it holds."""

    start: int
    count: int


def read(data: bytes) -> Palette:
    """A file's materials and the per-shape bindings that reach them.

    ⚠️ **Returns an empty `Palette` rather than raising.** Half the files under
    `files/a` are not models, and a caller that got an exception here would
    lose the geometry of the ones that are — the same trade `group_table`
    makes.

    Every step is bounds-checked against the counts the header states at
    `0x130`, so a file whose section table is not this layout falls out here
    instead of indexing into whatever follows.
    """
    layers = _table(data, LAYER_SLOT, LAYER_STRIDE)
    materials = _table(data, MATERIAL_SLOT, MATERIAL_STRIDE)
    records = _table(data, RECORD_SLOT, RECORD_STRIDE)
    if layers is None or materials is None or records is None:
        return Palette()
    if not _counts_agree(data, layers, materials, records):
        return Palette()

    images = [
        Material(
            index=struct.unpack_from(
                ">I", data, materials.start + i * MATERIAL_STRIDE + MATERIAL_IMAGE_AT
            )[0],
            path=text(
                data[materials.start + i * MATERIAL_STRIDE + MATERIAL_PATH_AT :][
                    : MATERIAL_STRIDE - MATERIAL_PATH_AT
                ]
            ),
        )
        for i in range(materials.count)
    ]
    picks = _layers(data, layers)
    if any(not 0 <= layer.material < materials.count for layer in picks):
        return Palette()

    shapes = []
    for index in range(records.count):
        bound = _binding(data, records.start + index * RECORD_STRIDE, picks)
        if bound is None:
            return Palette()
        shapes.append(bound)
    return Palette(images=images, shapes=shapes)


def _table(data: bytes, slot: int, stride: int) -> Table | None:
    """One section, as a record count, or nothing when it is not that shape."""
    need = SHAPE_SECTIONS_AT + (slot + 2) * 4
    if len(data) < need:
        return None
    edges = struct.unpack_from(f">{slot + 2}I", data, SHAPE_SECTIONS_AT)
    start, stop = edges[slot], edges[slot + 1]
    if not 0 < start <= stop <= len(data) or (stop - start) % stride:
        return None
    return Table(start=start, count=(stop - start) // stride)


def _counts_agree(data: bytes, layers: Table, materials: Table, records: Table) -> bool:
    """Whether the header's own three counts match the section strides.

    ✅ This is the check that turns "168 divides the span" into a reading. It
    holds on every one of the 870 models, and a file where it does not is not
    laid out the way the draw code expects.
    """
    if len(data) < COUNTS_AT + 12:
        return False
    stated = struct.unpack_from(">3I", data, COUNTS_AT)
    return stated == (layers.count, materials.count, records.count)


def _binding(data: bytes, start: int, picks: list) -> Binding | None:
    """One shape's layers, resolved to material indices in texture-map order.

    ⛔ Nothing rather than a partial answer when a record does not read: a
    layer index outside the table, a count above the eight the record can hold,
    or a used slot that is not `-1` past the count. The whole palette is
    dropped in that case, because a file that fails here is not this layout and
    the indices that *did* resolve would be coincidence.
    """
    count = struct.unpack_from(">I", data, start + RECORD_LAYERS_AT)[0]
    if count > RECORD_LAYERS:
        return None
    slots = struct.unpack_from(f">{RECORD_LAYERS}i", data, start + RECORD_LAYERS_FROM)
    if any(not 0 <= slot < len(picks) for slot in slots[:count]):
        return None
    if any(slot != NO_LAYER for slot in slots[count:]):
        return None
    return Binding(layers=[picks[slot] for slot in reversed(slots[:count])])


def _layers(data: bytes, table: Table) -> list:  # pylint: disable=container-return
    """Slot 17 joined to slot 16, one `Layer` per record.

    ⚠️ **A slot-16 table that does not read leaves the transforms at the
    identity** rather than dropping the palette. It is `layers * 24` bytes on
    every one of the 870 models, so nothing on the disc takes that path -- but a
    file that fails here still has a usable material binding, and refusing it
    would trade a whole model for a UV offset.
    """
    moves = _table(data, TRANSFORM_SLOT, TRANSFORM_STRIDE)
    aligned = moves is not None and moves.count == table.count
    found = []
    for index in range(table.count):
        at = table.start + index * LAYER_STRIDE
        material, flag = struct.unpack_from(">2i", data, at)
        moved = Moved(frames=0, transform=Transform())
        if aligned:
            moved = _transform(data, moves.start + index * TRANSFORM_STRIDE)
        found.append(
            Layer(
                material=material,
                wrap=Wrap.of(flag),
                transform=moved.transform,
                frames=moved.frames,
            )
        )
    return found


@dataclass(frozen=True)
class Moved:
    """One slot-16 record: the animation offset, and the UV transform."""

    frames: int
    transform: Transform


def _transform(data: bytes, at: int) -> Moved:
    """One 24-byte slot-16 record."""
    frames = data[at + TRANSFORM_FRAMES_AT]
    translate = struct.unpack_from(">2f", data, at + TRANSFORM_TRANSLATE_AT)
    scale = struct.unpack_from(">2f", data, at + TRANSFORM_SCALE_AT)
    rotation = struct.unpack_from(">f", data, at + TRANSFORM_ROTATION_AT)[0]
    return Moved(
        frames=frames,
        transform=Transform(
            translate_u=translate[0],
            translate_v=translate[1],
            scale_u=scale[0],
            scale_v=scale[1],
            rotation=rotation,
        ),
    )
