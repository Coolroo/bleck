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
        assert [entry.name for entry in index.entries] == sorted(SAMPLE)

    def test_the_area_drops_the_room_number(self, base):
        index = maps.load(base)
        assert index.find("aa4_01").area == "aa4"
        assert index.find("dan_10").area == "dan"

    def test_areas_are_counted_largest_first(self, base):
        counts = maps.load(base).areas()
        assert counts[0].area == "aa4"
        assert counts[0].maps == 2
        # Ties break by name, so the listing is stable between runs.
        assert [area.area for area in counts[1:]] == ["dan", "ls2", "mac"]

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
