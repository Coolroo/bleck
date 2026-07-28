"""LZ77 (type 0x10) encoding and decoding."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bleck.formats import lz77


class TestHeader:
    def test_detects_type_marker(self):
        assert lz77.is_lz77(b"\x10\x00\x01\x00")
        assert not lz77.is_lz77(b"\x11\x00\x01\x00")
        assert not lz77.is_lz77(b"\x10")  # too short to hold a header

    def test_reads_declared_size(self):
        # 24-bit little-endian: 0x123456
        assert lz77.decompressed_size(b"\x10\x56\x34\x12") == 0x123456

    def test_rejects_wrong_type(self):
        with pytest.raises(lz77.Lz77Error, match="not LZ77"):
            lz77.decompressed_size(b"\x11\x00\x00\x00")

    def test_rejects_oversized_input(self):
        with pytest.raises(lz77.Lz77Error, match="24-bit"):
            lz77.compress_literals(b"\x00" * (1 << 24))


class TestRoundTrip:
    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"a",
            b"a" * 7,  # exactly under one flag block
            b"a" * 8,  # exactly one flag block
            b"a" * 9,  # one past a block boundary
            bytes(range(256)),
        ],
        ids=["empty", "single", "under-block", "block", "over-block", "all-bytes"],
    )
    def test_literals(self, payload: bytes):
        assert lz77.decompress(lz77.compress_literals(payload)) == payload

    @pytest.mark.parametrize(
        "payload",
        [b"", b"a", b"ab", b"abc", b"abcabc", b"x" * 5000],
        ids=["empty", "1", "2", "3", "repeat", "long-run"],
    )
    def test_greedy(self, payload: bytes):
        assert lz77.decompress(lz77.compress(payload)) == payload

    def test_compressible(self, compressible: bytes):
        packed = lz77.compress(compressible)
        assert lz77.decompress(packed) == compressible
        assert len(packed) < len(compressible), "repetitive data should shrink"

    def test_incompressible(self, incompressible: bytes):
        assert lz77.decompress(lz77.compress(incompressible)) == incompressible


class TestMatching:
    def test_encodes_overlapping_runs(self):
        """A match may extend past the current position, reading its own output."""
        payload = b"\xab" * 4096
        packed = lz77.compress(payload)
        assert lz77.decompress(packed) == payload
        # Each 18-byte match costs 2 bytes; a literal-only encoding would be ~4.6 KB.
        assert len(packed) < len(payload) // 4

    def test_never_emits_displacement_one(self):
        """Nintendo's encoder avoids disp=1; we mirror that."""
        packed = lz77.compress(b"\x00" * 512)
        for token in _tokens(packed):
            if token.is_match:
                assert token.displacement >= lz77.MIN_DISP

    def test_respects_format_bounds(self, compressible: bytes):
        for token in _tokens(lz77.compress(compressible)):
            if not token.is_match:
                continue
            assert lz77.MIN_MATCH <= token.length <= lz77.MAX_MATCH
            assert lz77.MIN_DISP <= token.displacement <= lz77.MAX_DISP

    def test_literals_are_larger_than_greedy(self, compressible: bytes):
        assert len(lz77.compress_literals(compressible)) > len(
            lz77.compress(compressible)
        )


class TestCorruption:
    def test_truncated_stream_raises(self):
        packed = bytearray(lz77.compress_literals(b"hello world"))
        with pytest.raises(lz77.Lz77Error, match="exhausted"):
            lz77.decompress(bytes(packed[:6]))

    def test_size_field_larger_than_data(self):
        # Claims 0xFFFFFF bytes but supplies almost none.
        with pytest.raises(lz77.Lz77Error, match="exhausted"):
            lz77.decompress(b"\x10\xff\xff\xff\x00abc")


@dataclass(frozen=True)
class Token:
    """One decoded unit: a literal byte, or a back-reference."""

    length: int
    displacement: int

    @property
    def is_match(self) -> bool:
        return self.displacement > 0


def _tokens(data: bytes) -> list[Token]:
    """Decode a stream into its literal and back-reference units."""
    expected = lz77.decompressed_size(data)
    pos, produced, out = 4, 0, []
    while produced < expected:
        flags = data[pos]
        pos += 1
        for bit in range(7, -1, -1):
            if produced >= expected:
                break
            if flags >> bit & 1:
                length = (data[pos] >> 4) + lz77.MIN_MATCH
                disp = ((data[pos] & 0x0F) << 8 | data[pos + 1]) + 1
                pos += 2
                produced += length
                out.append(Token(length, disp))
            else:
                pos += 1
                produced += 1
                out.append(Token(1, 0))
    return out
