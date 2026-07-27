"""U8 archive reading and writing."""

from __future__ import annotations

import pytest

from bleck.formats import lz77, u8


@pytest.fixture
def simple() -> list[u8.U8Item]:
    """A small tree exercising nesting, siblings, and a trailing top-level file."""
    return [
        u8.U8Item("dvd", None),
        u8.U8Item("dvd/map", None),
        u8.U8Item("dvd/map/a.bin", b"first"),
        u8.U8Item("dvd/map/b.bin", b"second" * 10),
        u8.U8Item("dvd/bg", None),
        u8.U8Item("dvd/bg/c.tpl", b"\x00\x20\xaf\x30" + b"pixels"),
        u8.U8Item("readme.txt", b"top level"),
    ]


class TestDetection:
    def test_recognises_magic(self, simple):
        assert u8.is_u8(u8.write(simple))

    def test_rejects_other_data(self):
        assert not u8.is_u8(b"not an archive at all")
        assert not u8.is_u8(b"")


class TestRoundTrip:
    def test_preserves_structure(self, simple):
        entries = u8.read_all(u8.write(simple))
        assert entries == simple

    def test_repack_is_byte_identical(self, simple):
        packed = u8.write(simple)
        assert u8.write(u8.read_all(packed)) == packed

    def test_empty_archive(self):
        packed = u8.write([])
        assert u8.is_u8(packed)
        assert u8.read_all(packed) == []

    def test_zero_length_file(self):
        entries = [u8.U8Item("empty.bin", b"")]
        assert u8.read_all(u8.write(entries)) == entries

    def test_paths_and_contents_survive(self, simple):
        by_path = {e.path: e for e in u8.read(u8.write(simple))}
        assert by_path["dvd/map/b.bin"].size == len(b"second" * 10)
        assert by_path["dvd"].is_dir
        assert not by_path["readme.txt"].is_dir


class TestLayout:
    def test_files_are_32_byte_aligned(self, simple):
        """SPM's archives align every file to 32 bytes."""
        packed = u8.write(simple)
        for entry in u8.read(packed):
            if not entry.is_dir:
                assert entry.offset % u8.DATA_ALIGN == 0

    def test_no_trailing_padding(self, simple):
        packed = u8.write(simple)
        last = max(
            (e.offset + e.size for e in u8.read(packed) if not e.is_dir), default=0
        )
        assert len(packed) == last

    def test_node_order_is_preserved(self, simple):
        """Order is load-bearing: byte-exact repacking depends on it."""
        packed = u8.write(simple)
        assert [i.path for i in u8.read_all(packed)] == [i.path for i in simple]

        reordered = [simple[i] for i in (0, 1, 3, 2, 4, 5, 6)]
        assert u8.write(reordered) != packed


class TestErrors:
    def test_read_rejects_non_archive(self):
        with pytest.raises(u8.U8Error, match="not a U8"):
            u8.read(b"nonsense data here")

    def test_extract_rejects_directory(self, simple):
        packed = u8.write(simple)
        directory = next(e for e in u8.read(packed) if e.is_dir)
        with pytest.raises(u8.U8Error, match="is a directory"):
            u8.extract(packed, directory)


@pytest.mark.gamedata
class TestRealArchive:
    """Against actual game data — decompression only; never compression."""

    def test_map_archive_repacks_identically(self, map_archive: bytes):
        raw = lz77.decompress(map_archive)
        assert u8.is_u8(raw)
        assert u8.write(u8.read_all(raw)) == raw

    def test_expected_members_present(self, map_archive: bytes):
        raw = lz77.decompress(map_archive)
        paths = [e.path for e in u8.read(raw) if not e.is_dir]
        assert "./dvd/map/aa1_01/map.dat" in paths
        assert "./dvd/setup/aa1_01.dat" in paths
        # Developer build paths survive on the disc.
        assert all(p.startswith("./dvd/") for p in paths)
