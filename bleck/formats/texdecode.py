"""Turning GameCube texture data into RGBA pixels.

Separate from `tpl.py` because they answer different questions. That module
*edits* textures without ever decoding them, which is the whole reason a
recolour is lossless; this one decodes, which is only ever for **looking** —
export, preview, a viewer.

⛔ **Nothing in the build path calls this.** A texture edit still goes through
the endpoint domain (D187). If decoding ever became part of building, every
rebuild would be a re-encode and textures would degrade a generation at a time.

## The tiling, and why it is trustworthy

Pixels are stored in small rectangular tiles, left to right then top to bottom,
and every format uses a different tile size. Getting one wrong yields plausible
noise rather than an obvious failure.

✅ So the table in `tpl.TILING` was checked against the disc rather than a
reference: for **1,976 of 1,976** consecutive image pairs across every TPL,
`offset + data_size(image)` lands exactly on the next image's offset. The
game's own layout agrees with the arithmetic, for every format and every size.

⚠️ That validates the *sizes*, not the pixel order within a tile. Only looking
at the result does that, which is what the viewer is for.
"""

from __future__ import annotations

import struct

from bleck.formats.tpl import (
    TILING,
    Colour,
    Format,
    Image,
    Pixels,
    TextureError,
    unpack565,
)

#: Fully opaque, the alpha every format without an alpha channel decodes to.
OPAQUE = 255


def _put(out: bytearray, image: Image, x: int, y: int, rgba: tuple) -> None:
    """Write one pixel, dropping those in a tile's padding beyond the edge."""
    if x >= image.width or y >= image.height:
        return
    at = (y * image.width + x) * 4
    out[at : at + 4] = bytes(rgba)


def _tile_origins(image: Image):
    """Every tile's top-left corner, in the order the data stores them."""
    tile = TILING[image.format]
    for top in range(0, image.height, tile.height):
        for left in range(0, image.width, tile.width):
            yield left, top


def _decode_i4(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(8):
            for pair in range(4):
                byte = data[cursor]
                cursor += 1
                for half in range(2):
                    value = (byte >> 4) if half == 0 else (byte & 0x0F)
                    level = value * 17
                    _put(
                        out,
                        image,
                        left + pair * 2 + half,
                        top + row,
                        (level, level, level, OPAQUE),
                    )


def _decode_i8(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(4):
            for column in range(8):
                level = data[cursor]
                cursor += 1
                _put(out, image, left + column, top + row, (level, level, level, OPAQUE))


def _decode_ia4(data: bytes, image: Image, out: bytearray) -> None:
    """⚠️ Alpha in the *high* nibble, intensity in the low one."""
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(4):
            for column in range(8):
                byte = data[cursor]
                cursor += 1
                alpha = (byte >> 4) * 17
                level = (byte & 0x0F) * 17
                _put(out, image, left + column, top + row, (level, level, level, alpha))


def _decode_ia8(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(4):
            for column in range(4):
                alpha, level = data[cursor], data[cursor + 1]
                cursor += 2
                _put(out, image, left + column, top + row, (level, level, level, alpha))


def _decode_rgb565(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(4):
            for column in range(4):
                value = struct.unpack_from(">H", data, cursor)[0]
                cursor += 2
                colour = unpack565(value)
                _put(
                    out,
                    image,
                    left + column,
                    top + row,
                    (colour.r, colour.g, colour.b, OPAQUE),
                )


def _rgb5a3(value: int) -> tuple:  # pylint: disable=container-return
    """⚠️ Two layouts in one format, chosen by the top bit.

    Set means opaque RGB555; clear means a 3-bit alpha with RGB444. Reading it
    as one layout gives an image that is *almost* right, which is the hardest
    kind of wrong to notice.
    """
    if value & 0x8000:
        red = ((value >> 10) & 0x1F) << 3
        green = ((value >> 5) & 0x1F) << 3
        blue = (value & 0x1F) << 3
        return (red | (red >> 5), green | (green >> 5), blue | (blue >> 5), OPAQUE)
    alpha = ((value >> 12) & 0x07) * 255 // 7
    red = ((value >> 8) & 0x0F) * 17
    green = ((value >> 4) & 0x0F) * 17
    blue = (value & 0x0F) * 17
    return (red, green, blue, alpha)


def _decode_rgb5a3(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for row in range(4):
            for column in range(4):
                value = struct.unpack_from(">H", data, cursor)[0]
                cursor += 2
                _put(out, image, left + column, top + row, _rgb5a3(value))


def _decode_rgba32(data: bytes, image: Image, out: bytearray) -> None:
    """⚠️ One 4x4 tile is two halves: 16 alpha/red pairs, then 16 green/blue."""
    cursor = image.offset
    for left, top in _tile_origins(image):
        for index in range(16):
            alpha = data[cursor + index * 2]
            red = data[cursor + index * 2 + 1]
            green = data[cursor + 32 + index * 2]
            blue = data[cursor + 32 + index * 2 + 1]
            _put(
                out,
                image,
                left + (index % 4),
                top + (index // 4),
                (red, green, blue, alpha),
            )
        cursor += 64


def _cmpr_palette(c0: int, c1: int) -> list:  # pylint: disable=container-return
    """The four colours a block's endpoints imply.

    ⚠️ `c0 > c1` is a 4-colour opaque block; otherwise the fourth entry is
    transparent and the third is a plain midpoint. This is the same comparison
    `tpl.map_cmpr` preserves, seen from the decoding side.
    """
    first, second = unpack565(c0), unpack565(c1)
    palette = [
        (first.r, first.g, first.b, OPAQUE),
        (second.r, second.g, second.b, OPAQUE),
    ]
    if c0 > c1:
        palette.append(
            (
                (2 * first.r + second.r) // 3,
                (2 * first.g + second.g) // 3,
                (2 * first.b + second.b) // 3,
                OPAQUE,
            )
        )
        palette.append(
            (
                (first.r + 2 * second.r) // 3,
                (first.g + 2 * second.g) // 3,
                (first.b + 2 * second.b) // 3,
                OPAQUE,
            )
        )
    else:
        palette.append(
            (
                (first.r + second.r) // 2,
                (first.g + second.g) // 2,
                (first.b + second.b) // 2,
                OPAQUE,
            )
        )
        palette.append((0, 0, 0, 0))
    return palette


#: Where each of a CMPR tile's four sub-blocks sits inside its 8x8 tile.
_SUBBLOCKS = ((0, 0), (4, 0), (0, 4), (4, 4))


def _decode_cmpr(data: bytes, image: Image, out: bytearray) -> None:
    cursor = image.offset
    for left, top in _tile_origins(image):
        for dx, dy in _SUBBLOCKS:
            c0, c1 = struct.unpack_from(">HH", data, cursor)
            palette = _cmpr_palette(c0, c1)
            for row in range(4):
                bits = data[cursor + 4 + row]
                for column in range(4):
                    # ⚠️ Most significant pair first: the leftmost pixel is the
                    # top bits, not the bottom ones as in PC DXT1.
                    index = (bits >> (6 - column * 2)) & 0x03
                    _put(
                        out,
                        image,
                        left + dx + column,
                        top + dy + row,
                        palette[index],
                    )
            cursor += 8


_DECODERS = {
    Format.I4: _decode_i4,
    Format.I8: _decode_i8,
    Format.IA4: _decode_ia4,
    Format.IA8: _decode_ia8,
    Format.RGB565: _decode_rgb565,
    Format.RGB5A3: _decode_rgb5a3,
    Format.RGBA32: _decode_rgba32,
    Format.CMPR: _decode_cmpr,
}


def decode(data: bytes, image: Image) -> Pixels:
    """One image as 8-bit RGBA, row-major, with tile padding discarded."""
    decoder = _DECODERS.get(image.format)
    if decoder is None:
        raise TextureError(f"{image.describe()}: no decoder for {image.format.name}")

    out = bytearray(image.width * image.height * 4)
    try:
        decoder(data, image, out)
    except (IndexError, struct.error) as exc:
        raise TextureError(
            f"{image.describe()}: pixel data runs past the end of the file.\n"
            f"  Wanted {image.offset:#x} plus its tiles; the file is "
            f"{len(data)} bytes."
        ) from exc
    return Pixels(image.width, image.height, bytes(out))


def average(pixels: Pixels) -> Colour:
    """The image's mean colour, weighted by nothing. Useful as a cheap check."""
    total = len(pixels.rgba) // 4
    if not total:
        return Colour(0, 0, 0)
    sums = [0, 0, 0]
    for index in range(0, len(pixels.rgba), 4):
        sums[0] += pixels.rgba[index]
        sums[1] += pixels.rgba[index + 1]
        sums[2] += pixels.rgba[index + 2]
    return Colour(sums[0] // total, sums[1] // total, sums[2] // total)
