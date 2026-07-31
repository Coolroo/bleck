"""Writing RIFF/WAVE, so decoded audio can be played by anything.

The counterpart to `png.py`: `bleck` decodes a disc format and hands out one
every operating system already opens. Stdlib `wave` could do this, but it wants
a file object and a context manager to produce bytes, and the format is a
header plus the samples.

⚠️ **WAVE is little-endian**, and the disc is big-endian throughout. Every
other format in this package reads `>`; this one writes `<`, and mixing them
produces a file that plays as loud static.
"""

from __future__ import annotations

import struct

#: 16-bit signed PCM, the only thing written here.
PCM = 1
BITS = 16
BYTES_PER_SAMPLE = BITS // 8


def write(rate: int, channels: list) -> bytes:
    """Interleave one list of samples per channel into a `.wav`.

    ⚠️ Channels are **interleaved per frame** — left, right, left, right — not
    concatenated. Concatenating them produces a file of the right length that
    plays one channel after the other.
    """
    if not channels or not channels[0]:
        raise ValueError("no samples to write")
    count = min(len(channel) for channel in channels)
    frames = bytearray()
    for index in range(count):
        for channel in channels:
            frames += struct.pack("<h", max(-0x8000, min(0x7FFF, channel[index])))

    block_align = len(channels) * BYTES_PER_SAMPLE
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(frames),
        b"WAVE",
        b"fmt ",
        16,
        PCM,
        len(channels),
        rate,
        rate * block_align,
        block_align,
        BITS,
        b"data",
        len(frames),
    )
    return header + bytes(frames)
