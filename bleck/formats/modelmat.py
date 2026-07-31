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
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bleck.formats.modelbase import SHAPE_SECTIONS_AT, text

#: Slot 17: one 8-byte record per layer. `+0x00` is the material index a layer
#: resolves to; a runtime byte is added to it, which is how a texture animates
#: without the file changing. `+0x04` is a wrap/clamp flag -- the draw code
#: tests bits 2 and 3 of it to choose a `GXTexWrapMode`.
LAYER_SLOT = 17
LAYER_STRIDE = 8
LAYER_MATERIAL_AT = 0x00

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
class Binding:
    """The materials one shape draws with, in GX texture-map order.

    Each entry indexes `Palette.images`; the `Material` there names the bank
    image. Empty for a shape that draws with no texture at all -- 4,319 of the
    disc's 19,022 shapes, which is why "is this model textured" was always the
    wrong question to ask once (D240).
    """

    images: list = field(default_factory=list)  # pylint: disable=container-return


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
    picks = [
        struct.unpack_from(">i", data, layers.start + i * LAYER_STRIDE)[0]
        for i in range(layers.count)
    ]
    if any(not 0 <= pick < materials.count for pick in picks):
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
    return Binding(images=[picks[slot] for slot in reversed(slots[:count])])
