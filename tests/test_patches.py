"""`code.patches`: a manifest declaration -> the guard and write in generated C.

The mechanism is measured (D89); these check the declarative path expresses it
and that the build-time guards reject what cannot work.
"""

from __future__ import annotations

import json
import re

import pytest

from bleck.api import v1
from bleck.mods import code
from bleck.mods import manifest as mod_manifest
from bleck.mods.registry import Mod
from bleck.script import compile_source, emit

PATCH = emit.ScriptPatch(
    kind=emit.PatchKind.MAP, target="he1_01", at=0, expect=0x00010072, call="on_map_init"
)

#: Item script 0's opening instruction: `USER_FUNC f, a, b, c`, argc 4 (D91).
ITEM_PATCH = emit.ScriptPatch(
    kind=emit.PatchKind.ITEM,
    target="0x41",
    at=0,
    expect=0x0004005C,
    call="on_item_use",
    item_id=0x41,
)


def generated(patches=(PATCH,)):
    return emit.generate_bare(origin="x", patches=list(patches)).text


def manifest(patch: dict) -> mod_manifest.Manifest:
    return mod_manifest.Manifest.from_json(
        json.dumps({"name": "m", "code": {"sources": ["src"], "patches": [patch]}})
    )


WHOLE = {"script": "map:he1_01", "at": 0, "expect": "DEBUG_PUT_MSG", "call": "hook"}


class TestGeneratedCode:
    def test_the_target_is_the_map_s_init_script(self):
        out = generated()
        assert "#define BLECK_MAP_INIT_SCRIPT 0x18" in out
        assert 'static const char bleck_patch_target_0[] = "he1_01";' in out
        assert "bleck_map_init_script(patch->target)" in out

    def test_the_replacement_carries_the_replaced_argument_count(self):
        """Same size by construction: the count comes from the matched header."""
        out = generated()
        assert "#define BLECK_USER_FUNC 0x005Cu" in out
        assert "#define BLECK_ARGC_MASK 0xFFFF0000u" in out
        assert (
            "script[patch->at] = (patch->expect & BLECK_ARGC_MASK) "
            "| BLECK_USER_FUNC;" in out
        )
        assert "script[patch->at + 1] = (u32) patch->call;" in out

    def test_at_one_argument_it_is_byte_for_byte_d90(self):
        """The general form must still emit D90's measured 0x0001005C."""
        out = generated()
        constants = dict(
            re.findall(
                r"#define (BLECK_USER_FUNC|BLECK_ARGC_MASK) (0x[0-9A-Fa-f]+)u", out
            )
        )
        word = (0x00010072 & int(constants["BLECK_ARGC_MASK"], 16)) | int(
            constants["BLECK_USER_FUNC"], 16
        )
        assert word == 0x0001005C

    def test_only_the_header_and_the_pointer_are_written(self):
        """Words 2..M are the original's arguments, carried through untouched."""
        body = generated().split("static void bleck_apply_patches")[1]
        assert "patch->at + 2" not in body

    def test_the_guard_refuses_rather_than_writing_blind(self):
        """A wrong offset must cost a status, not an undiagnosable freeze."""
        out = generated()
        assert "0x00010072u" in out
        body = out.split("static void bleck_apply_patches")[1]
        refuse = body.index("BLECK_PATCH_REFUSED")
        assert body.index("if (script[patch->at] != patch->expect)") < refuse
        assert refuse < body.index("script[patch->at] = (patch->expect")

    def test_a_null_script_is_its_own_status(self):
        """Otherwise "not linked yet" and "wrong instruction" look the same."""
        assert "BLECK_PATCH_NO_SCRIPT" in generated()

    def test_the_item_resolver_is_absent_from_a_map_only_module(self):
        """So a map patch leaves `itemEventDataTable` unreferenced."""
        out = generated()
        assert "itemEventDataTable" not in out
        assert "BLECK_PATCH_ITEM" in out  # the constant still exists

    def test_the_map_resolver_is_absent_from_an_item_only_module(self):
        out = generated([ITEM_PATCH])
        assert "mapDataPtr" not in out
        assert "itemEventDataTable[index].useScript" in out

    def test_the_status_table_is_readable_from_a_mod(self):
        out = generated()
        # Not static, and not in .bss: the loader does not document zeroing it.
        assert "u32 bleck_patch_status[BLECK_PATCH_COUNT] = {" in out
        assert "static u32 bleck_patch_status" not in out
        assert "BLECK_PATCH_PENDING," in out
        assert "const u32 bleck_patch_count = BLECK_PATCH_COUNT;" in out

    def test_the_hook_is_declared_once_per_name(self):
        second = emit.ScriptPatch(
            emit.PatchKind.MAP, "he2_01", 4, 0x00010072, "on_map_init"
        )
        out = generated([PATCH, second])
        assert out.count("extern void on_map_init(void);") == 1
        assert "#define BLECK_PATCH_COUNT 2" in out

    def test_it_is_applied_before_mod_prolog(self):
        """So a mod's own C can read the status it is about to report."""
        prolog = generated().split("void _prolog(void)")[1]
        assert prolog.index("bleck_apply_patches();") < prolog.index("mod_prolog();")

    def test_nothing_is_emitted_without_patches(self):
        assert "bleck_apply_patches" not in emit.generate_bare(origin="x").text


class TestMerging:
    """A merged module's patch table is the union across every mod."""

    def _part(self, name):
        return emit.ModPart(
            name=name,
            program=compile_source(
                "script main {\n gw[30] = 1\n}",
                scaffolding=emit.Scaffolding(require_entry=False),
            ).program,
        )

    def test_the_table_is_the_union(self):
        second = emit.ScriptPatch(
            emit.PatchKind.MAP, "ls4_12", 2, 0x00010072, "other_hook"
        )
        out = emit.generate_merged(
            [self._part("alpha"), self._part("beta")], patches=[PATCH, second]
        ).text
        assert "#define BLECK_PATCH_COUNT 2" in out
        assert "extern void on_map_init(void);" in out
        assert "extern void other_hook(void);" in out

    def test_a_merge_without_patches_emits_none(self):
        out = emit.generate_merged([self._part("alpha")]).text
        assert "bleck_apply_patches" not in out


class TestPatchKind:
    """The kind is half of a wire string -- `map:he1_01` -- so the enum has to
    survive a round trip through `mod.json` without leaking its member name."""

    @pytest.mark.parametrize("selector", ["map:he1_01", "item:0x41", "item:65"])
    def test_a_selector_round_trips_as_written(self, selector):
        expect = "USER_FUNC 4" if selector.startswith("item") else "DEBUG_PUT_MSG"
        written = manifest({**WHOLE, "script": selector, "expect": expect}).to_json()
        assert f'"script": "{selector}"' in written
        assert "PatchKind" not in written

    def test_the_supported_list_is_derived_from_the_members(self):
        """It used to be prose sitting two lines below the tuple it described,
        with nothing keeping them in step."""
        for kind in emit.PatchKind:
            assert kind.example in emit.SUPPORTED_SELECTORS

    def test_a_deferred_kind_is_not_a_member(self):
        """`door:` is recognised well enough to explain and refused anyway. As a
        member it would appear in every 'here is what works' list."""
        assert emit.PatchKind.parse("door") is None
        assert "door" in mod_manifest.DEFERRED_PATCH_KINDS
        assert "door" not in emit.SUPPORTED_SELECTORS


class TestManifest:
    def test_it_parses_and_round_trips(self):
        parsed = manifest(WHOLE)
        assert parsed.code.patches == [
            mod_manifest.ScriptPatch(
                kind=mod_manifest.PatchKind.MAP,
                target="he1_01",
                at=0,
                expect="DEBUG_PUT_MSG",
                expect_word=0x00010072,
                call="hook",
            )
        ]
        assert parsed.code.has_patches
        again = mod_manifest.Manifest.from_json(parsed.to_json())
        assert again.code == parsed.code

    def test_absent_when_unset(self):
        assert "patches" not in mod_manifest.CodeSpec(script="a.evt").to_json()

    def test_an_unknown_selector_names_what_is_supported(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "script": "npc:goomba"})
        message = str(caught.value)
        assert "map:<name>" in message
        assert "item:<id>" in message

    def test_a_bare_name_is_not_a_selector(self):
        with pytest.raises(mod_manifest.ManifestError, match="map:<name>"):
            manifest({**WHOLE, "script": "he1_01"})

    def test_door_is_refused_with_its_reason(self):
        """Deferred, not merely unimplemented: there is no lookup by name (D91)."""
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "script": "door:front"})
        message = str(caught.value)
        assert "evt_door_set_door_descs" in message
        assert "item:<id>" in message

    def test_a_negative_offset_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="cannot be negative"):
            manifest({**WHOLE, "at": -1})

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="unknown field"):
            manifest({**WHOLE, "with": "1"})

    def test_an_item_selector_resolves_to_an_id(self):
        parsed = manifest(
            {**WHOLE, "script": "item:0x41", "expect": "USER_FUNC 4"}
        ).code.patches[0]
        assert parsed.kind == "item"
        assert parsed.item_id == 0x41
        assert parsed.selector == "item:0x41"

    def test_a_decimal_item_id_works_too(self):
        parsed = manifest(
            {**WHOLE, "script": "item:65", "expect": "USER_FUNC 4"}
        ).code.patches[0]
        assert parsed.item_id == 65

    def test_a_map_patch_has_no_item_id(self):
        assert manifest(WHOLE).code.patches[0].item_id == -1

    def test_a_non_numeric_item_id_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "script": "item:fire-burst"})
        assert "item:0x41" in str(caught.value)

    def test_an_object_instead_of_a_list_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"code\.patches"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "s", "patches": {}}}'
            )


class TestExpect:
    """`expect` resolves to a header word, and sizes the replacement with it."""

    def test_a_raw_header_word_is_accepted(self):
        parsed = manifest({**WHOLE, "expect": "0x00010072"})
        assert parsed.code.patches[0].expect_word == 0x00010072

    def test_an_unknown_opcode_suggests(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "expect": "DEBUG_PUT_MSSG"})
        assert "DEBUG_PUT_MSG" in str(caught.value)

    def test_a_multi_word_opcode_is_now_accepted(self):
        """SET is three words. D90 refused it; the replacement now matches."""
        assert manifest({**WHOLE, "expect": "SET"}).code.patches[0].expect_word == (
            0x00020032
        )

    def test_a_one_word_opcode_is_refused_for_want_of_room(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "expect": "END_IF"})
        message = str(caught.value)
        assert "one word" in message
        assert "no room for the pointer" in message
        assert "jump table" in message

    def test_a_raw_one_word_header_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="no room for the pointer"):
            manifest({**WHOLE, "expect": "0x00000021"})

    def test_a_variadic_opcode_needs_its_count(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "expect": "USER_FUNC"})
        assert "variadic" in str(caught.value)
        assert "USER_FUNC 4" in str(caught.value)

    def test_a_variadic_opcode_with_a_count_resolves(self):
        parsed = manifest({**WHOLE, "expect": "USER_FUNC 4"})
        assert parsed.code.patches[0].expect_word == 0x0004005C
        assert parsed.code.patches[0].argument_count == 4

    def test_a_count_that_contradicts_the_table_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "expect": "DEBUG_PUT_MSG 3"})
        assert "always takes 1 argument" in str(caught.value)

    def test_a_count_that_matches_the_table_is_allowed(self):
        parsed = manifest({**WHOLE, "expect": "DEBUG_PUT_MSG 1"})
        assert parsed.code.patches[0].expect_word == 0x00010072

    def test_a_non_numeric_count_says_what_it_is_for(self):
        with pytest.raises(mod_manifest.ManifestError, match="argument count"):
            manifest({**WHOLE, "expect": "USER_FUNC four"})


class TestCallResolution:
    """The `call` has to be a function this mod actually defines."""

    def _mod(self, tmp_path, body: str) -> Mod:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.c").write_text(body, encoding="utf-8")
        (tmp_path / "mod.json").write_text(
            json.dumps({"name": "m", "code": {"sources": ["src"]}}), encoding="utf-8"
        )
        return Mod(root=tmp_path, manifest=mod_manifest.read(tmp_path))

    def test_a_defined_function_resolves(self, tmp_path):
        mod = self._mod(tmp_path, "int hook(void *e, int f) { return 2; }\n")
        spec = manifest(WHOLE).code
        patches = code.patches_for(mod, spec, code.collect_sources(mod, spec))
        assert patches == [
            emit.ScriptPatch(emit.PatchKind.MAP, "he1_01", 0, 0x00010072, "hook")
        ]

    def test_a_typo_is_caught_before_the_linker_and_suggests(self, tmp_path):
        mod = self._mod(tmp_path, "int hook(void *e, int f) { return 2; }\n")
        spec = manifest({**WHOLE, "call": "hokk"}).code
        with pytest.raises(code.CodeError) as caught:
            code.patches_for(mod, spec, code.collect_sources(mod, spec))
        message = str(caught.value)
        assert "'hook'" in message  # the suggestion
        assert "EvtEntry" in message  # and the signature it needs

    def test_a_declaration_is_not_a_definition(self, tmp_path):
        mod = self._mod(tmp_path, "int hook(void *e, int f);\n")
        spec = manifest(WHOLE).code
        with pytest.raises(code.CodeError, match="define no such function"):
            code.patches_for(mod, spec, code.collect_sources(mod, spec))

    def test_a_mention_in_a_comment_is_not_a_definition(self, tmp_path):
        mod = self._mod(tmp_path, "/* hook(a) { */\nint other(void) { return 0; }\n")
        spec = manifest(WHOLE).code
        with pytest.raises(code.CodeError, match="they define: other"):
            code.patches_for(mod, spec, code.collect_sources(mod, spec))

    def test_a_function_pointer_parameter_still_matches(self, tmp_path):
        mod = self._mod(tmp_path, "int hook(void (*cb)(void), int f) { return 2; }\n")
        spec = manifest(WHOLE).code
        assert code.patches_for(mod, spec, code.collect_sources(mod, spec))

    def test_control_flow_is_not_mistaken_for_a_definition(self, tmp_path):
        mod = self._mod(tmp_path, "int f(void) { if (1) { return 2; } return 0; }\n")
        spec = manifest({**WHOLE, "call": "if"}).code
        with pytest.raises(code.CodeError, match="they define: f"):
            code.patches_for(mod, spec, code.collect_sources(mod, spec))


class TestApi:
    def test_it_round_trips_through_the_json_contract(self):
        spec = manifest(WHOLE).code
        document = v1.Code.of(spec)
        assert document.patches[0].script == "map:he1_01"
        assert document.to_manifest().patches == spec.patches

    def test_an_item_patch_round_trips(self):
        spec = manifest({**WHOLE, "script": "item:0x41", "expect": "USER_FUNC 4"}).code
        document = v1.Code.of(spec)
        assert document.patches[0].script == "item:0x41"
        assert document.to_manifest().patches == spec.patches

    def test_the_contract_rejects_what_the_manifest_rejects(self):
        bad = v1.Patch(script="map:he1_01", at=0, expect="END_IF", call="hook")
        with pytest.raises(mod_manifest.ManifestError, match="no room"):
            bad.to_manifest()
