"""Format detection across nested containers."""

from __future__ import annotations

import struct

import pytest

from bleck.formats import detect as formats
from bleck.formats import lz77, u8


def _rel(sections: int = 19, version: int = 3) -> bytes:
    """A minimal blob shaped like a Nintendo REL header."""
    header = bytearray(0x4C)
    struct.pack_into(">I", header, 0x00, 1)  # module id
    struct.pack_into(">I", header, 0x0C, sections)
    struct.pack_into(">I", header, 0x10, 0x4C)  # sectionInfoOffset
    struct.pack_into(">I", header, 0x1C, version)
    return bytes(header)


class TestLeaves:
    def test_tpl(self):
        layer = formats.identify(struct.pack(">I", formats.TPL_MAGIC) + b"\x00" * 32)
        assert layer.name == "TPL"

    def test_brstm(self):
        assert formats.identify(b"RSTM" + b"\x00" * 32).name == "BRSTM"

    def test_brsar(self):
        assert formats.identify(b"RSAR" + b"\x00" * 32).name == "BRSAR"

    def test_rel(self):
        assert formats.identify(_rel(sections=23)).name == "REL v3 (23 sections)"

    def test_rel_rejected_on_bad_version(self):
        assert formats.identify(_rel(version=9)).name == "unknown"

    def test_unknown(self):
        assert formats.identify(b"\x99" * 64).name == "unknown"

    def test_tiny_input(self):
        assert formats.identify(b"ab").name == "unknown"


class TestNesting:
    def test_unwraps_lz77(self):
        payload = b"RSTM" + b"\x00" * 64
        layer = formats.identify(lz77.compress_literals(payload))
        assert layer.name == "LZ77"
        assert [c.name for c in layer.children] == ["BRSTM"]

    def test_unwraps_lz77_over_u8(self):
        archive = u8.write(
            [u8.U8Item("a.tpl", struct.pack(">I", formats.TPL_MAGIC) + b"\x00" * 8)]
        )
        layer = formats.identify(lz77.compress_literals(archive))
        assert layer.name == "LZ77"
        inner = layer.children[0]
        assert inner.name == "U8"
        assert "TPL" in inner.children[0].detail

    def test_reports_corrupt_inner_stream(self):
        # Valid header, truncated body.
        layer = formats.identify(b"\x10\xff\xff\xff\x00abc")
        assert layer.name == "LZ77"
        assert layer.children[0].name == "<corrupt>"


class TestRender:
    def test_indents_by_depth(self):
        archive = u8.write([u8.U8Item("a.bin", b"data")])
        lines = formats.render(formats.identify(archive))
        assert lines[0].startswith("U8")
        assert lines[1].startswith("  ")

    @pytest.mark.gamedata
    def test_real_map_archive(self, map_archive: bytes):
        lines = formats.render(formats.identify(map_archive))
        assert any("LZ77" in line for line in lines)
        assert any("U8" in line for line in lines)
        assert any("TPL" in line for line in lines)
