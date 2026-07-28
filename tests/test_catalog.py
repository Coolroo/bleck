"""The builtin catalog, and the call validation it powers.

The catalog moves two failures earlier: an unknown name (previously `elf2rel`'s
"Missing 1 required symbol(s)") and a wrong argument count (previously silent).
"""

from __future__ import annotations

import pytest

from bleck.script import compile_source
from bleck.script.catalog import (
    Builtin,
    Catalog,
    build_catalog,
    load,
    parse_header,
)
from bleck.script.compiler import compile_program
from bleck.script.errors import ScriptError
from bleck.script.syntax.parser import parse

HEADER = """\
#pragma once

// evt_mario_set_pos(f32 x, f32 y, f32 z)
EVT_DECLARE_USER_FUNC(evt_mario_set_pos, 3)

// type 2 = no damage vector; flags and dmg taken from params
// type 3 = all data taken from params
EVT_DECLARE_USER_FUNC(evt_mario_take_damage, 6)

EVT_DECLARE_USER_FUNC(evt_sub_get_mapname, -1)

EVT_UNKNOWN_USER_FUNC(evt_pouch_get_arcade_tokens)
"""


def catalog_of(*builtins: Builtin) -> Catalog:
    return Catalog(builtins=list(builtins), source="test")


class TestParsingHeaders:
    def test_finds_declared_and_unknown_forms(self):
        found = {b.name: b for b in parse_header(HEADER, "spm")}
        assert set(found) == {
            "evt_mario_set_pos",
            "evt_mario_take_damage",
            "evt_sub_get_mapname",
            "evt_pouch_get_arcade_tokens",
        }

    def test_arity_is_captured(self):
        found = {b.name: b for b in parse_header(HEADER, "spm")}
        assert found["evt_mario_set_pos"].arity == 3
        assert found["evt_mario_take_damage"].arity == 6

    def test_variadic_and_unknown_both_become_none(self):
        """-1 is variadic, the other macro is unknown; neither can be checked."""
        found = {b.name: b for b in parse_header(HEADER, "spm")}
        assert found["evt_sub_get_mapname"].arity is None
        assert found["evt_pouch_get_arcade_tokens"].arity is None
        assert not found["evt_sub_get_mapname"].is_documented

    def test_signature_comment_is_captured(self):
        found = {b.name: b for b in parse_header(HEADER, "spm")}
        assert found["evt_mario_set_pos"].signature == (
            "evt_mario_set_pos(f32 x, f32 y, f32 z)"
        )

    def test_unrelated_prose_is_not_mistaken_for_a_signature(self):
        # The two comment lines above `evt_mario_take_damage` are not signatures.
        found = {b.name: b for b in parse_header(HEADER, "spm")}
        assert found["evt_mario_take_damage"].signature == ""

    def test_scanning_a_tree(self, tmp_path):
        (tmp_path / "spm").mkdir()
        (tmp_path / "spm" / "evt_mario.h").write_text(HEADER)
        catalog = build_catalog(tmp_path)
        assert len(catalog.builtins) == 4
        assert catalog.builtins[0].module == "evt_mario"

    def test_an_empty_tree_is_an_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_catalog(tmp_path)


class TestCatalog:
    def test_round_trips_through_json(self):
        # `to_json` sorts by name so a regenerated catalog diffs readably.
        original = build_catalog_from_text()
        restored = Catalog.from_json(original.to_json())
        assert sorted(restored.builtins, key=lambda b: b.name) == sorted(
            original.builtins, key=lambda b: b.name
        )

    def test_json_records_its_provenance(self):
        # Extracted from MIT-licensed headers; attribution rides with the data.
        text = build_catalog_from_text().to_json()
        assert "spm-headers" in text
        assert "MIT" in text

    def test_search_matches_names_and_signatures(self):
        catalog = build_catalog_from_text()
        assert [b.name for b in catalog.search("set_pos")] == ["evt_mario_set_pos"]
        # "f32" appears only in a signature, not in any name.
        assert catalog.search("f32")

    def test_suggest_finds_a_near_miss(self):
        catalog = build_catalog_from_text()
        assert "evt_mario_set_pos" in catalog.suggest("evt_mario_set_po")

    def test_suggest_declines_when_nothing_is_close(self):
        """A wrong suggestion is worse than none — it sends the reader hunting."""
        assert build_catalog_from_text().suggest("completely_unrelated") == []


def build_catalog_from_text() -> Catalog:
    return Catalog(builtins=parse_header(HEADER, "evt_mario"), source="test")


class TestCallValidation:
    def _compile(self, source: str, catalog: Catalog):
        return compile_program(parse(source), source, catalog)

    def test_a_correct_call_compiles(self):
        catalog = build_catalog_from_text()
        self._compile("script main {\n evt_mario_set_pos(1.0, 2.0, 3.0)\n}", catalog)

    def test_unknown_name_is_rejected_with_a_suggestion(self):
        catalog = build_catalog_from_text()
        with pytest.raises(ScriptError, match=r"Did you mean evt_mario_set_pos"):
            self._compile("script main {\n evt_mario_set_po(1.0)\n}", catalog)

    def test_unknown_name_with_no_near_miss_points_at_the_listing(self):
        catalog = build_catalog_from_text()
        with pytest.raises(ScriptError, match=r"bleck script builtins"):
            self._compile("script main {\n wildly_different(1)\n}", catalog)

    def test_wrong_argument_count_is_rejected(self):
        catalog = build_catalog_from_text()
        with pytest.raises(ScriptError, match=r"takes 3 argument\(s\), but 2"):
            self._compile("script main {\n evt_mario_set_pos(1.0, 2.0)\n}", catalog)

    def test_the_error_shows_the_documented_signature(self):
        catalog = build_catalog_from_text()
        with pytest.raises(ScriptError, match=r"f32 x, f32 y, f32 z"):
            self._compile("script main {\n evt_mario_set_pos(1.0)\n}", catalog)

    def test_undocumented_arity_is_not_checked(self):
        """Guessing would reject working code; upstream simply does not know."""
        catalog = build_catalog_from_text()
        self._compile("script main {\n evt_sub_get_mapname(1, 2, 3)\n}", catalog)

    def test_an_empty_catalog_disables_checking(self):
        """A missing catalog must not make every script uncompilable."""
        self._compile("script main {\n anything_at_all(1)\n}", catalog_of())


class TestShippedCatalog:
    """The catalog committed to the repo, used when none is passed."""

    def test_it_is_present_and_substantial(self):
        assert len(load().builtins) > 400

    def test_real_scripts_validate_against_it(self):
        compile_source("script main {\n evt_pouch_add_coins(1)\n}")

    def test_a_real_typo_is_caught(self):
        with pytest.raises(ScriptError, match=r"evt_pouch_add_coins"):
            compile_source("script main {\n evt_pouch_add_coin(1)\n}")
