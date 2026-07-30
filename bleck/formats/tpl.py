"""TPL textures, and colour operations that never re-compress them.

A TPL is a container of images. 90.6% of the 9,403 images on the disc are
**CMPR** — S3TC/DXT1 block compression — and the rest are direct formats
(measured, `docs/plan-textures.md`). ⛔ **Zero are paletted**, which removes
palette decoding and the whole class of "editing one image changes another".

## Why this does not decode CMPR

A CMPR block is two `RGB565` endpoint colours followed by 2-bit per-pixel
indices selecting among the four colours those endpoints imply. A **per-pixel
colour map changes only the endpoints** — every index still means "the same
fraction of the way between them".

So a recolour rewrites four bytes per block and copies the rest. It never
decodes the index packing, never re-compresses, and is therefore *exact*: an
identity map returns the input byte for byte, and a mod rebuilt ten times is
not ten generations degraded.

⛔ **This is why `replace with new artwork` is not here.** That genuinely needs
an encoder; everything in this module deliberately does not.

## The trap, which is real and was tested

DXT1 encodes two block kinds and tells them apart by **comparing the
endpoints**: `c0 > c1` is a 4-colour opaque block, `c0 <= c1` is 3 colours plus
transparent. A colour map can reorder the endpoints and silently flip a block
between the two — turning opaque pixels transparent.

⚠️ So the original ordering is restored after mapping, by swapping the mapped
endpoints when the comparison changed. `tests/test_tpl.py` asserts this against
constructed blocks of both kinds, because "it looked fine" would not have
caught it.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from bleck.common.errors import BleckError

#: `00 20 AF 30`, big-endian, at offset 0.
TPL_MAGIC = 0x0020AF30

#: Bytes per CMPR block: two RGB565 endpoints, then 16 2-bit indices.
CMPR_BLOCK = 8

#: A CMPR block covers 4x4 pixels.
CMPR_TILE = 4


class TextureError(BleckError):
    """A TPL could not be read, or an operation cannot apply to it."""


class Format(IntEnum):
    """GameCube texture formats, by the value stored in an image header.

    ⚠️ Only the ones that occur on this disc are named. C4, C8 and C14X2 are
    paletted and measured at **zero** images, so nothing here handles palettes.
    """

    I4 = 0
    I8 = 1
    IA4 = 2
    IA8 = 3
    RGB565 = 4
    RGB5A3 = 5
    RGBA32 = 6
    CMPR = 14

    @property
    def has_colour(self) -> bool:
        """Whether the format can represent a hue at all.

        ⚠️ `I4` and `I8` cannot. A colour map applied to one has to be projected
        back to intensity, so `tint` on an intensity texture is meaningful but
        **not reversible** — unlike every other case here.
        """
        return self not in (Format.I4, Format.I8, Format.IA4, Format.IA8)


@dataclass(frozen=True)
class Image:
    """One image inside a TPL, and where its pixels are."""

    index: int
    width: int
    height: int
    format: Format
    offset: int
    """Byte offset of the pixel data within the whole TPL."""

    @property
    def blocks(self) -> int:
        """CMPR blocks covering this image, rounded up as the hardware does."""
        wide = (self.width + CMPR_TILE - 1) // CMPR_TILE
        tall = (self.height + CMPR_TILE - 1) // CMPR_TILE
        return wide * tall

    def describe(self) -> str:
        return f"image {self.index}: {self.width}x{self.height} {self.format.name}"


def is_tpl(data: bytes) -> bool:
    if len(data) < 4:
        return False
    return struct.unpack_from(">I", data, 0)[0] == TPL_MAGIC


def read(data: bytes) -> list[Image]:  # pylint: disable=container-return
    """Every image a TPL declares, in table order.

    ⚠️ An unknown format value is **refused, not skipped**. Skipping would make
    a texture edit silently do nothing, which is this repo's most-repeated bug
    shape (D126).
    """
    if not is_tpl(data):
        raise TextureError("not a TPL: expected magic 00 20 AF 30 at offset 0")

    count, table = struct.unpack_from(">II", data, 4)
    found: list[Image] = []
    for index in range(count):
        head, _palette = struct.unpack_from(">II", data, table + index * 8)
        height, width, raw = struct.unpack_from(">HHI", data, head)
        offset = struct.unpack_from(">I", data, head + 8)[0]
        try:
            fmt = Format(raw)
        except ValueError as exc:
            raise TextureError(
                f"image {index} has texture format {raw}, which bleck does not "
                f"know.\n"
                f"  Known formats: {', '.join(f.name for f in Format)}."
            ) from exc
        found.append(Image(index, width, height, fmt, offset))
    return found


@dataclass(frozen=True)
class Colour:
    """An 8-bit RGB triple, the space every operation works in."""

    r: int
    g: int
    b: int

    def clamped(self) -> Colour:
        return Colour(
            max(0, min(255, self.r)),
            max(0, min(255, self.g)),
            max(0, min(255, self.b)),
        )

    @property
    def luma(self) -> int:
        """Rec. 601 luma, for projecting a colour back onto an intensity format."""
        return max(0, min(255, (self.r * 299 + self.g * 587 + self.b * 114) // 1000))


#: ⛔ **Bit replication, not `v * 255 // n`.** The obvious scaling does not round
#: trip: 5-bit 1 becomes 8, and 8 scales back to 0. Every channel drifts down one
#: step per rebuild, so an *identity* map was not identity -- caught by the
#: real-disc test after the constructed fixtures passed, because the fixtures
#: happened to use values that survive (D187).
def _expand5(value: int) -> int:
    return (value << 3) | (value >> 2)


def _expand6(value: int) -> int:
    return (value << 2) | (value >> 4)


def _contract(value: int, bits: int) -> int:
    top = (1 << bits) - 1
    return (value * top + 127) // 255


def unpack565(value: int) -> Colour:
    return Colour(
        _expand5((value >> 11) & 0x1F),
        _expand6((value >> 5) & 0x3F),
        _expand5(value & 0x1F),
    )


def pack565(colour: Colour) -> int:
    fixed = colour.clamped()
    return (
        (_contract(fixed.r, 5) << 11)
        | (_contract(fixed.g, 6) << 5)
        | _contract(fixed.b, 5)
    )


@dataclass(frozen=True)
class ColourMap:
    """A per-channel affine map, applied in 8-bit space.

    Affine rather than arbitrary because that is exactly what survives the
    endpoint trick: every operation this repo needs -- invert, brightness,
    tint, greyscale -- is one of these, and none of them needs to see a pixel.
    """

    name: str
    scale_r: float = 1.0
    scale_g: float = 1.0
    scale_b: float = 1.0
    offset_r: int = 0
    offset_g: int = 0
    offset_b: int = 0
    to_grey: bool = False
    """Collapse to luma first, so a tint applies to brightness rather than hue."""

    def apply(self, colour: Colour) -> Colour:
        source = colour
        if self.to_grey:
            grey = colour.luma
            source = Colour(grey, grey, grey)
        return Colour(
            int(source.r * self.scale_r + self.offset_r),
            int(source.g * self.scale_g + self.offset_g),
            int(source.b * self.scale_b + self.offset_b),
        ).clamped()

    @property
    def is_identity(self) -> bool:
        """⚠️ Load-bearing: an identity map must leave a texture byte-identical,
        and that is the acceptance test for the whole endpoint approach."""
        return (
            not self.to_grey
            and (self.scale_r, self.scale_g, self.scale_b) == (1.0, 1.0, 1.0)
            and (self.offset_r, self.offset_g, self.offset_b) == (0, 0, 0)
        )


IDENTITY = ColourMap("identity")

#: Named operations a `tables/textures.csv` row can ask for. `tint` takes an
#: argument and is built per row, so it is absent here.
OPERATIONS = {
    "identity": IDENTITY,
    "invert": ColourMap("invert", -1.0, -1.0, -1.0, 255, 255, 255),
    "greyscale": ColourMap("greyscale", to_grey=True),
}


def brightness(factor: float) -> ColourMap:
    """Scale every channel. `0.5` halves, `2.0` doubles and clips."""
    return ColourMap(f"brightness:{factor}", factor, factor, factor)


def tint(colour: Colour, strength: float = 1.0) -> ColourMap:
    """Map greys onto `colour`, keeping the texture's own light and shade.

    Collapses to luma first, then scales each channel by that colour's share of
    full brightness -- so a mid-grey lands on `colour` and highlights stay
    highlights, rather than the whole texture becoming one flat hue.
    """
    return ColourMap(
        f"tint:{colour.r:02x}{colour.g:02x}{colour.b:02x}",
        scale_r=(colour.r / 255.0) * 2.0 * strength,
        scale_g=(colour.g / 255.0) * 2.0 * strength,
        scale_b=(colour.b / 255.0) * 2.0 * strength,
        to_grey=True,
    )


@dataclass(frozen=True)
class Applied:
    """The result of mapping one image, and what it took."""

    data: bytes
    blocks: int = 0
    reordered: int = 0
    """CMPR blocks whose endpoints were swapped back to keep their kind."""


def map_cmpr(data: bytes, image: Image, colours: ColourMap) -> Applied:
    """Rewrite every block's endpoints, leaving the indices byte-identical.

    ⚠️ The `c0 > c1` comparison is what DXT1 uses to choose between a 4-colour
    opaque block and a 3-colour-plus-transparent one. Mapping can reorder the
    endpoints and flip that, turning opaque pixels transparent -- so the
    original relation is restored by swapping when it changed.
    """
    if image.format is not Format.CMPR:
        raise TextureError(
            f"{image.describe()} is not CMPR, so it has no endpoints to "
            f"rewrite.\n"
            f"  Reading four bytes per 'block' out of a direct-colour image "
            f"would corrupt it silently."
        )

    out = bytearray(data)
    reordered = 0
    for index in range(image.blocks):
        at = image.offset + index * CMPR_BLOCK
        if at + CMPR_BLOCK > len(out):
            raise TextureError(
                f"{image.describe()} claims {image.blocks} blocks but the file "
                f"ends after {(len(out) - image.offset) // CMPR_BLOCK}"
            )
        c0, c1 = struct.unpack_from(">HH", out, at)
        n0 = pack565(colours.apply(unpack565(c0)))
        n1 = pack565(colours.apply(unpack565(c1)))
        if (c0 > c1) != (n0 > n1):
            n0, n1 = n1, n0
            reordered += 1
        struct.pack_into(">HH", out, at, n0, n1)
    return Applied(bytes(out), blocks=image.blocks, reordered=reordered)


@dataclass(frozen=True)
class Tiling:
    """How one format lays pixels out, and how much space it needs.

    ⛔ **GameCube textures are tiled, not scanline.** Pixels are stored in small
    rectangular blocks, left to right then top to bottom, and every format uses
    a different block size. Decoding one as scanline produces an image that
    looks like plausible noise rather than an obvious failure, which is why the
    tile sizes below are stated per format rather than assumed.
    """

    width: int
    height: int
    bits: int
    """Bits per pixel. CMPR is 4 by this measure -- 8 bytes per 4x4 sub-block."""


TILING = {
    Format.I4: Tiling(8, 8, 4),
    Format.I8: Tiling(8, 4, 8),
    Format.IA4: Tiling(8, 4, 8),
    Format.IA8: Tiling(4, 4, 16),
    Format.RGB565: Tiling(4, 4, 16),
    Format.RGB5A3: Tiling(4, 4, 16),
    Format.RGBA32: Tiling(4, 4, 32),
    Format.CMPR: Tiling(8, 8, 4),
}


@dataclass(frozen=True)
class Pixels:
    """A decoded image: 8-bit RGBA, row-major, no padding."""

    width: int
    height: int
    rgba: bytes

    def at(self, x: int, y: int) -> tuple[int, int, int, int]:
        # pylint: disable=container-return
        start = (y * self.width + x) * 4
        return tuple(self.rgba[start : start + 4])  # type: ignore[return-value]


def _tiles(image: Image) -> tuple[int, int]:  # pylint: disable=container-return
    """How many tiles across and down, rounded up as the hardware pads."""
    tile = TILING[image.format]
    across = (image.width + tile.width - 1) // tile.width
    down = (image.height + tile.height - 1) // tile.height
    return across, down


def data_size(image: Image) -> int:
    """Bytes this image occupies, including the padding to whole tiles."""
    tile = TILING[image.format]
    across, down = _tiles(image)
    return across * down * tile.width * tile.height * tile.bits // 8
