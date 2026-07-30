"""`code.replace` — a vanilla script repointed at one the mod compiled.

The refusals matter more than the acceptances here. A swap writes a pointer into
the game's own data, and the failure mode of getting it wrong is a frozen game
rather than an error — so every selector kind that has not been measured is
rejected by name, with the reason.
"""

from __future__ import annotations

import pytest

from bleck.mods.errors import ManifestError
from bleck.mods.manifest.codespec import _parse_code as parse_code
from bleck.mods.manifest.replacements import ScriptReplacement, build_replacement
from bleck.script import emit


def parse(replace: list[dict]) -> list[ScriptReplacement]:
    spec = parse_code({"sources": ["src"], "replace": replace}, "mod.json")
    assert spec is not None
    return spec.replacements


class TestWhatItAccepts:
    def test_a_door_interact_swap(self):
        found = parse([{"script": "door:he1_01:0:interact", "with": "my_door"}])[0]
        assert found.map_name == "he1_01"
        assert found.index == 0
        assert found.script == "my_door"
        assert found.field_offset == emit.DoorScript.INTERACT.offset

    def test_the_script_defaults_to_interact(self):
        """Matching `code.patches`, where omitting it means the same thing."""
        bare = parse([{"script": "door:he1_01:0", "with": "my_door"}])[0]
        named = parse([{"script": "door:he1_01:0:interact", "with": "my_door"}])[0]
        assert bare.field_offset == named.field_offset

    def test_init_and_move_resolve_to_their_own_fields(self):
        offsets = {
            name: parse([{"script": f"door:he1_01:0:{name}", "with": "s"}])[
                0
            ].field_offset
            for name in ("interact", "init", "move")
        }
        assert len(set(offsets.values())) == 3, offsets

    def test_absent_means_no_replacements(self):
        assert not parse([])
        spec = parse_code({"sources": ["src"]}, "mod.json")
        assert spec is not None and not spec.replacements


class TestTheGuard:
    def test_a_swap_is_unguarded_by_default(self):
        """⚠️ Honest rather than convenient: a door's interact script opens with
        MULF (D103), so a default guess would be wrong more often than right."""
        found = parse([{"script": "door:he1_01:0", "with": "s"}])[0]
        assert not found.guarded
        assert found.expect_word == 0

    def test_an_opcode_name_resolves_to_a_header_word(self):
        found = parse([{"script": "door:he1_01:0", "with": "s", "expect": "MULF"}])[0]
        assert found.guarded
        assert found.expect_word != 0

    def test_an_unknown_opcode_is_refused(self):
        with pytest.raises(ManifestError, match="NOT_AN_OPCODE"):
            parse([{"script": "door:he1_01:0", "with": "s", "expect": "NOT_AN_OPCODE"}])

    def test_expect_must_be_a_string(self):
        with pytest.raises(ManifestError, match="'expect'"):
            parse([{"script": "door:he1_01:0", "with": "s", "expect": 12}])


class TestWhatItRefuses:
    def test_a_map_init_script_is_refused_with_the_measurement(self):
        """⛔ D51 swapped exactly this and the map froze mid-load. The message
        has to say so, or someone will try it again."""
        with pytest.raises(ManifestError) as exc:
            parse([{"script": "map:he1_01", "with": "s"}])
        assert "D51" in str(exc.value)
        assert "code.maps" in str(exc.value)

    def test_an_item_script_is_refused_as_unproven(self):
        with pytest.raises(ManifestError) as exc:
            parse([{"script": "item:fire_burst", "with": "s"}])
        assert "SHARED" in str(exc.value)

    def test_an_npc_script_is_refused_as_unproven(self):
        with pytest.raises(ManifestError) as exc:
            parse([{"script": "npcdrv:2:onhit", "with": "s"}])
        assert "SHARED" in str(exc.value)

    def test_every_refusal_names_an_alternative(self):
        """A refusal that does not say what to do instead is a dead end."""
        for selector in ("map:he1_01", "item:fire_burst", "npcdrv:2:onhit"):
            with pytest.raises(ManifestError) as exc:
                parse([{"script": selector, "with": "s"}])
            assert "code.patches" in str(exc.value) or "code.maps" in str(exc.value)

    def test_a_bad_door_index_is_refused_against_the_catalog(self):
        """The same bounds check `code.patches` gets (D141)."""
        with pytest.raises(ManifestError):
            parse([{"script": "door:he1_01:99", "with": "s"}])

    def test_an_unknown_field_is_named(self):
        with pytest.raises(ManifestError, match="unknown field"):
            parse([{"script": "door:he1_01:0", "with": "s", "cal": "oops"}])

    def test_with_must_be_a_script_name(self):
        with pytest.raises(ManifestError, match="not a script name"):
            parse([{"script": "door:he1_01:0", "with": "not a name"}])

    @pytest.mark.parametrize("missing", ["script", "with"])
    def test_both_fields_are_required(self, missing: str):
        entry = {"script": "door:he1_01:0", "with": "s"}
        del entry[missing]
        with pytest.raises(ManifestError, match=missing):
            parse([entry])

    def test_a_non_list_is_refused_with_an_example(self):
        with pytest.raises(ManifestError, match="must be a list"):
            parse_code(
                {"sources": ["src"], "replace": {"script": "door:he1_01:0"}}, "mod.json"
            )


class TestItIsNotAPatch:
    """The two are different mechanisms and must not be conflated."""

    def test_a_replacement_carries_no_word_offset(self):
        """`at` is meaningless: the whole script is replaced, not one word."""
        with pytest.raises(ManifestError, match="unknown field"):
            parse([{"script": "door:he1_01:0", "with": "s", "at": 0}])

    def test_it_names_a_script_not_a_c_function(self):
        """`code.patches` calls a C function; a swap points at compiled bytecode."""
        found = build_replacement("door:he1_01:0", "my_door", "", "where")
        assert found.script == "my_door"
