"""Writing PNG, in about eighty lines and no new dependency.

⛔ **Not Pillow.** `bleck` ships as a frozen binary with *two* runtime
dependencies, and every one is paid for by users who never touch the feature
that needed it. PNG's writer half is small: a signature, three chunks, and
zlib — which is stdlib. Reading PNG would be a different argument, and nothing
here reads one.

Output is 8-bit RGBA, non-interlaced, with filter type 0 on every row. ⚠️ No
filter heuristics: they trade a slower write for a smaller file, and these are
throwaway previews of textures whose commonest size is 64x64.
"""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Colour type 6 is truecolour with alpha; 8 bits per channel.
BIT_DEPTH = 8
COLOUR_RGBA = 6


def _chunk(kind: bytes, payload: bytes) -> bytes:
    """One PNG chunk: length, type, payload, and a CRC over type+payload."""
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def write(width: int, height: int, rgba: bytes) -> bytes:
    """Encode 8-bit RGBA rows as a PNG.

    ⚠️ Every row is prefixed with a filter byte of 0. That byte is not optional
    padding -- a decoder reads it as the row's filter method, and omitting it
    shifts the whole image by one byte per row, which renders as a diagonal
    smear rather than an error.
    """
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(
            f"expected {expected} bytes for {width}x{height} RGBA, got {len(rgba)}"
        )

    raw = bytearray()
    stride = width * 4
    for row in range(height):
        raw.append(0)
        raw += rgba[row * stride : (row + 1) * stride]

    header = struct.pack(">IIBBBBB", width, height, BIT_DEPTH, COLOUR_RGBA, 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def dimensions(data: bytes) -> tuple[int, int]:  # pylint: disable=container-return
    """Width and height from a PNG's header, for checking our own output."""
    if not data.startswith(SIGNATURE):
        raise ValueError("not a PNG")
    return struct.unpack_from(">II", data, 16)
