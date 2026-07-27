"""Reading the game's map list off an extracted disc.

Map names are not a table this toolkit maintains -- they are archive filenames.
That is the property worth pinning: `files/map/aa4_01.bin` must yield exactly
`aa4_01`, because that string goes straight into `code.maps` and on to
`mapDataPtr`. An off-by-one in the suffix stripping would produce names that
look right and match nothing.
"""

from __future__ import annotations

import pytest

from bleck.backends import maps
from bleck.common.errors import BleckError

SAMPLE = ["aa4_01", "aa4_02", "mac_01", "dan_10", "ls2_03"]


@pytest.fixture(name="base")
def _base(tmp_path):
    directory = tmp_path / maps.MAP_DIR
    directory.mkdir(parents=True)
    for name in SAMPLE:
        (directory / f"{name}{maps.MAP_SUFFIX}").write_bytes(b"x" * 16)
    return tmp_path


class TestMapIndex:
    def test_the_name_is_the_archive_name(self, base):
        index = maps.load(base)
        assert sorted(entry.name for entry in index.entries) == sorted(SAMPLE)

    def test_the_area_drops_the_room_number(self, base):
        index = maps.load(base)
        assert index.find("aa4_01").area == "aa4"
        assert index.find("dan_10").area == "dan"

    def test_the_prefix_and_sublevel_split_apart(self, base):
        # `he1_01` is the game's own chapter "1-1", so both halves matter.
        index = maps.load(base)
        assert index.find("aa4_01").prefix == "aa"
        assert index.find("aa4_01").sublevel == 4
        assert index.find("mac_01").prefix == "mac"
        assert index.find("mac_01").sublevel == 0

    def test_areas_group_by_prefix_not_sublevel(self, base):
        counts = {area.area: area.maps for area in maps.load(base).areas()}
        assert counts["aa"] == 2
        assert counts["mac"] == 1

    def test_search_is_case_insensitive(self, base):
        index = maps.load(base)
        assert [entry.name for entry in index.search("AA4")] == ["aa4_01", "aa4_02"]

    def test_an_unknown_map_is_not_invented(self, base):
        assert maps.load(base).find("nope_01") is None

    def test_a_missing_disc_says_how_to_get_one(self, tmp_path):
        # This is the error a new checkout hits first, so it has to name the fix.
        with pytest.raises(BleckError, match="bleck extract"):
            maps.load(tmp_path)

    def test_non_archives_are_ignored(self, base):
        (base / maps.MAP_DIR / "notes.txt").write_text("not a map")
        assert len(maps.load(base).entries) == len(SAMPLE)


class TestChapters:
    """Turning `he1_01` into something a person recognises.

    The prefix-to-chapter mapping is fixed by two anchors in spm-headers --
    `he1_01_tippi_tutorial_evt` (chapter 1-1) and `sammerDefsCh6` -- with
    contiguous `mapData[]` runs between them. These guard the result, because
    the obvious reading of a prefix is not reliable: `sp` is chapter 5, not
    "space".
    """

    def test_sp_is_chapter_five_not_space(self):
        area = next(a for a in maps.AREAS if a.prefix == "sp")
        assert area.chapter == 5
        assert area.label == "Land of the Cragnons"

    def test_the_eight_chapters_are_numbered_once_each(self):
        numbered = sorted(a.chapter for a in maps.AREAS if a.is_chapter)
        assert numbered == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_the_anchors_that_fix_the_ordering(self):
        # If either of these moves, the whole interpolation between them is
        # invalid and every chapter number here becomes a guess.
        by_prefix = {a.prefix: a.chapter for a in maps.AREAS}
        assert by_prefix["he"] == 1
        assert by_prefix["wa"] == 6

    def test_a_chapter_map_reads_as_the_game_numbers_it(self, tmp_path):
        entry = maps.MapEntry(name="ta3_02", archive=tmp_path / "ta3_02.bin")
        assert entry.where == "Ch 3-3  The Bitlands"

    def test_a_non_chapter_map_just_says_where_it_is(self, tmp_path):
        entry = maps.MapEntry(name="mac_01", archive=tmp_path / "mac_01.bin")
        assert entry.where == "Flipside / Flopside"

    def test_an_unrecognised_prefix_is_not_invented(self, tmp_path):
        entry = maps.MapEntry(name="zz9_01", archive=tmp_path / "zz9_01.bin")
        assert entry.region.label == "unknown"
        assert not entry.region.is_chapter


class TestCatalog:
    """Map ids, which only the running game knows."""

    def test_the_committed_catalog_covers_the_whole_table(self):
        ids = maps._catalog_ids()  # pylint: disable=protected-access
        # spm/map_data.h: MAP_ID_MAX is 0x1d4.
        assert len(ids) == 0x1D4
        assert ids["he1_01"] == 26

    def test_ids_are_attached_to_maps_found_on_disc(self, tmp_path):
        directory = tmp_path / maps.MAP_DIR
        directory.mkdir(parents=True)
        (directory / "he1_01.bin").write_bytes(b"x")
        assert maps.load(tmp_path).find("he1_01").map_id == 26

    def test_a_map_absent_from_the_catalog_is_flagged_not_guessed(self, tmp_path):
        directory = tmp_path / maps.MAP_DIR
        directory.mkdir(parents=True)
        (directory / "zz9_01.bin").write_bytes(b"x")
        assert maps.load(tmp_path).find("zz9_01").map_id == -1
