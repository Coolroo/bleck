"""Nintendo LZ77 (type 0x10) decompression.

Header is 4 bytes: a 0x10 type marker followed by a 24-bit little-endian
uncompressed size. The body is a sequence of blocks, each a flag byte followed
by 8 units, MSB first. A clear flag bit means "copy one literal byte"; a set bit
means "back-reference", encoded big-endian across two bytes as a 4-bit
(length - 3) and a 12-bit (displacement - 1).
"""

from __future__ import annotations

from dataclasses import dataclass

LZ77_TYPE = 0x10
HEADER_SIZE = 4


class Lz77Error(Exception):
    pass


def is_lz77(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[0] == LZ77_TYPE


def decompressed_size(data: bytes) -> int:
    """Read the header's declared output size without decompressing."""
    if not is_lz77(data):
        raise Lz77Error(f"not LZ77 type 0x10 (first byte 0x{data[0]:02x})")
    return int.from_bytes(data[1:4], "little")


def decompress(data: bytes) -> bytes:
    expected = decompressed_size(data)
    out = bytearray()
    pos = HEADER_SIZE
    end = len(data)

    while len(out) < expected:
        if pos >= end:
            raise Lz77Error(
                f"input exhausted at {pos} with {len(out)}/{expected} bytes emitted"
            )
        flags = data[pos]
        pos += 1

        for bit in range(7, -1, -1):
            if len(out) >= expected:
                break
            if not flags >> bit & 1:
                if pos >= end:
                    raise Lz77Error("input exhausted reading a literal")
                out.append(data[pos])
                pos += 1
                continue

            if pos + 1 >= end:
                raise Lz77Error("input exhausted reading a back-reference")
            length = (data[pos] >> 4) + 3
            disp = ((data[pos] & 0x0F) << 8 | data[pos + 1]) + 1
            pos += 2

            start = len(out) - disp
            if start < 0:
                raise Lz77Error(f"back-reference before start of output ({start})")
            # Overlapping copies are legal and common — copy byte by byte.
            for _ in range(length):
                out.append(out[start])
                start += 1

    return bytes(out)


MIN_MATCH = 3
MAX_MATCH = 18
MAX_DISP = 4096

# Nintendo's encoder never emits a displacement of 1, though the format permits
# it. Mirrored so our output keeps the same shape.
MIN_DISP = 2


def _header(size: int) -> bytearray:
    if size >= 1 << 24:
        raise Lz77Error(f"{size} bytes exceeds the 24-bit size field")
    return bytearray([LZ77_TYPE, size & 0xFF, size >> 8 & 0xFF, size >> 16 & 0xFF])


def compress_literals(data: bytes) -> bytes:
    """Emit a valid stream with no back-references: ~1.125x the input.

    A fallback, and a control when debugging the real encoder.
    """
    out = _header(len(data))
    for i in range(0, len(data), 8):
        out.append(0)  # eight clear flag bits: all literals
        out += data[i : i + 8]
    return bytes(out)


# Candidate positions considered per match. Visited nearest-first with an early
# stop on a maximal match, so this rarely binds.
MAX_CANDIDATES = 256


@dataclass(frozen=True)
class Match:
    """A back-reference candidate: copy `length` bytes from `displacement` back."""

    length: int
    displacement: int

    @property
    def is_usable(self) -> bool:
        return self.length >= MIN_MATCH


NO_MATCH = Match(0, 0)


def _extend(data: bytes, pos: int, src: int, limit: int) -> int:
    """Length of the match at `src`, allowing the copy to overlap `pos`.

    Back-references resolve byte-by-byte, so a match may legally read bytes it
    has just produced; that is how run-length patterns are encoded.
    """
    n = 0
    while n < limit and data[src + n] == data[pos + n]:
        n += 1
    return n


def _longest_match(data: bytes, pos: int, end: int) -> Match:
    """Longest match at `pos`, or NO_MATCH.

    Candidates come from searching backwards for the 3-byte prefix, then
    extending with overlap allowed. Ties keep the smallest displacement.
    """
    limit = min(MAX_MATCH, end - pos)
    if limit < MIN_MATCH:
        return NO_MATCH

    lowest = max(0, pos - MAX_DISP)
    prefix = data[pos : pos + MIN_MATCH]
    best = NO_MATCH

    # Candidates must start at or before pos - MIN_DISP.
    search_end = pos - MIN_DISP + MIN_MATCH
    for _ in range(MAX_CANDIDATES):
        found = data.rfind(prefix, lowest, search_end)
        if found < 0:
            break

        length = _extend(data, pos, found, limit)
        if length > best.length:
            best = Match(length, pos - found)
            if length == limit:
                break

        search_end = found + MIN_MATCH - 1

    return best if best.is_usable else NO_MATCH


def compress(data: bytes) -> bytes:
    """Greedy LZ77 encoder."""
    out = _header(len(data))
    end = len(data)
    pos = 0

    while pos < end:
        flag_at = len(out)
        out.append(0)
        flags = 0

        for bit in range(7, -1, -1):
            if pos >= end:
                break
            match = _longest_match(data, pos, end)
            if match.is_usable:
                flags |= 1 << bit
                encoded = match.displacement - 1
                out.append((match.length - MIN_MATCH) << 4 | encoded >> 8)
                out.append(encoded & 0xFF)
                pos += match.length
            else:
                out.append(data[pos])
                pos += 1

        out[flag_at] = flags

    return bytes(out)
