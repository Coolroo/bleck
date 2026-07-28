"""`bleck.yml` — the project config file.

Most of what is asserted here is *error quality*: a mistake must name the file,
say what was wrong, and list what would have been right.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bleck.common import config as cfg


class TestDiscovery:
    def test_the_nearest_file_wins(self, tmp_path: Path):
        """The closest config to the working directory overrides the ones above."""
        (tmp_path / "bleck.yml").write_text("combos:\n  outer: [1, 2]\n")
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (tmp_path / "a" / "bleck.yml").write_text("combos:\n  inner: [1, 2]\n")

        assert cfg.load(nested).combo_names == ["inner"]

    def test_it_searches_upward(self, tmp_path: Path):
        (tmp_path / "bleck.yml").write_text("combos:\n  outer: [1, 2]\n")
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)

        assert cfg.load(deep).combo_names == ["outer"]

    def test_no_file_is_not_an_error(self, tmp_path: Path):
        """Combos are opt-in; only *referring* to an undeclared one fails."""
        found = cfg.load(tmp_path)
        assert found.is_empty
        assert found.source is None

    def test_an_empty_file_is_not_an_error(self, tmp_path: Path):
        (tmp_path / "bleck.yml").write_text("")
        assert cfg.load(tmp_path).is_empty

    def test_it_records_where_it_came_from(self, tmp_path: Path):
        (tmp_path / "bleck.yml").write_text("combos:\n  x: [1, 2]\n")
        assert cfg.load(tmp_path).source == tmp_path / "bleck.yml"


class TestCombos:
    def test_buttons_resolve_to_a_combined_mask(self):
        found = cfg.parse("combos:\n  start_map: [1, 2]\n").combo("start_map")
        assert found.buttons == ("1", "2")
        assert found.mask == cfg.BUTTON_MASKS["1"] | cfg.BUTTON_MASKS["2"]

    def test_yaml_reads_bare_digits_as_numbers_and_they_still_work(self):
        """`1` and `2` are button *names*, but YAML parses them as ints."""
        assert cfg.parse("combos:\n  c: [1, 2]\n").combo("c").buttons == ("1", "2")

    def test_names_are_case_insensitive(self):
        assert cfg.parse("combos:\n  c: [A, Plus]\n").combo("c").mask == (
            cfg.BUTTON_MASKS["a"] | cfg.BUTTON_MASKS["plus"]
        )

    def test_an_unknown_button_lists_the_valid_ones(self):
        with pytest.raises(cfg.ConfigError) as caught:
            cfg.parse("combos:\n  c: [1, x]\n")
        message = str(caught.value)
        assert "'x'" in message
        assert "minus" in message  # the list of valid names

    def test_a_nunchuk_button_explains_itself(self):
        """`c` exists, in a struct bleck does not read — so not "unknown button"."""
        with pytest.raises(cfg.ConfigError, match="nunchuk"):
            cfg.parse("combos:\n  c: [1, z]\n")

    def test_a_single_button_is_refused_by_default(self):
        # It would fire while walking around.
        with pytest.raises(cfg.ConfigError, match="ordinary play"):
            cfg.parse("combos:\n  c: [home]\n")

    def test_a_single_button_is_allowed_when_meant(self):
        found = cfg.parse("combos:\n  c: {buttons: [home], allow_single: true}\n").combo(
            "c"
        )
        assert found.buttons == ("home",)

    def test_the_refusal_shows_the_override(self):
        with pytest.raises(cfg.ConfigError) as caught:
            cfg.parse("combos:\n  c: [home]\n")
        assert "allow_single" in str(caught.value)

    def test_a_repeated_button_is_refused(self):
        with pytest.raises(cfg.ConfigError, match="same button twice"):
            cfg.parse("combos:\n  c: [1, 1]\n")

    def test_an_empty_combo_is_refused(self):
        with pytest.raises(cfg.ConfigError, match="list of button names"):
            cfg.parse("combos:\n  c: []\n")


class TestConstants:
    def test_they_are_read(self):
        found = cfg.parse("constants:\n  test_map: he1_01\n").constant("test_map")
        assert found.value == "he1_01"

    def test_an_absent_name_is_none_not_an_error(self):
        assert cfg.parse("").constant("nope") is None


class TestMalformed:
    def test_bad_yaml_names_the_file(self):
        with pytest.raises(cfg.ConfigError) as caught:
            cfg.parse("combos: [unclosed\n", where="my-config.yml")
        assert "my-config.yml" in str(caught.value)

    def test_a_future_schema_version_says_what_is_supported(self):
        with pytest.raises(cfg.ConfigError, match="version 1"):
            cfg.parse("version: 99\n")

    def test_a_scalar_top_level_is_refused(self):
        with pytest.raises(cfg.ConfigError, match="mapping at the top level"):
            cfg.parse("just a string\n")

    def test_a_section_that_is_not_a_mapping_is_refused(self):
        with pytest.raises(cfg.ConfigError, match="'combos' must be a mapping"):
            cfg.parse("combos: [1, 2]\n")


class TestReturnedTypes:
    """C9001 forbids returning dicts; guard against a 'simplification' back."""

    def test_lookups_return_named_values(self):
        found = cfg.parse("combos:\n  c: [1, 2]\n")
        assert isinstance(found.combo("c"), cfg.Combo)
        assert not isinstance(found.combos, dict)

    def test_a_combo_can_describe_itself(self):
        # For listing what is available in an error message.
        assert "1 + 2" in cfg.parse("combos:\n  c: [1, 2]\n").combo("c").describe


class TestButtonTable:
    def test_every_mask_is_a_single_bit(self):
        """A mask covering two bits would silently make one combo match another."""
        for name, mask in cfg.BUTTON_MASKS.items():
            assert mask and not (mask & (mask - 1)), f"{name} is not one bit"

    def test_no_two_buttons_share_a_bit(self):
        assert len(set(cfg.BUTTON_MASKS.values())) == len(cfg.BUTTON_MASKS)
