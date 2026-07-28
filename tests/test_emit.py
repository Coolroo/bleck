"""Turning a compiled program into one C translation unit.

Asserts the *shape* of the generated runtime: which hook runs when, what lands
in .data rather than .bss, and which mechanisms are ruled out (cited by D-number).
"""

from __future__ import annotations

import json

import pytest

from bleck.mods import manifest as mod_manifest
from bleck.script import compile_source, emit, evt
from bleck.script.compiler import (
    Literal,
    compile_program,
)
from bleck.script.errors import ScriptError
from bleck.script.syntax.parser import parse


def words(source: str, script: str = "main") -> list:
    """Compile `source` and return one script's words."""
    program = compile_program(parse(source), source)
    for compiled in program.scripts:
        if compiled.name == script:
            return compiled.words
    raise AssertionError(f"no script named {script}")


def values(source: str, script: str = "main") -> list[int]:
    """The words of a script, as plain integers. Fails on symbolic words."""
    return [word.value for word in words(source, script) if isinstance(word, Literal)]


#: The smallest useful program, for tests that only care about the scaffolding.
SIMPLE = "script main {\n wait(1)\n}"


def header(opcode: evt.Opcode, count: int) -> int:
    return evt.instruction_header(opcode, count)


class TestGeneratedC:
    def test_declares_called_functions_extern(self):
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "extern void evt_pouch_add_coins(void);" in out.text

    def test_takes_the_address_of_called_functions(self):
        # The linker resolves the name, so bleck never writes a game address.
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "(s32) &evt_pouch_add_coins" in out.text

    def test_no_game_addresses_appear(self):
        out = compile_source("script main {\n evt_pouch_add_coins(1)\n}").generated
        assert "0x80" not in out.text

    def test_entry_point_starts_the_main_script(self):
        out = compile_source("script main {\n wait(1)\n}").generated
        assert "void _prolog(void)" in out.text
        assert "evtEntry(bleck_script_main, 0, 0)" in out.text

    def test_prolog_only_arms_hooks(self):
        # evtEntry from _prolog does nothing (D38) and .init does not work
        # (D40); hooking .main does (D43).
        out = compile_source(SIMPLE).generated
        prolog = out.text.split("void _prolog(void)")[1]
        assert "seq_data[i].main = bleck_hooks[i]" in prolog
        assert "evtEntry" not in prolog

    def test_every_sequence_is_hooked(self):
        # A script does not survive a map change (D43), so something must
        # notice gameplay was left.
        out = compile_source(SIMPLE).generated
        for index in range(6):
            assert f"bleck_seq{index}" in out.text

    def test_leaving_gameplay_re_arms_the_start(self):
        # A script does not survive a map change (D43), so the start re-arms.
        out = compile_source(SIMPLE).generated
        body = out.text.split("static void bleck_start_entry")[1]
        assert "bleck_needs_start = 1" in body
        assert "bleck_needs_start = 0" in body
        assert "evtEntry(" in body

    def test_the_original_sequence_function_is_still_called(self):
        assert "bleck_real_main[seq](work)" in compile_source(SIMPLE).generated.text

    def test_saved_pointers_avoid_bss(self):
        # Nothing documents whether the loader zeroes bss, so initialisers are
        # non-zero to force .data.
        out = compile_source(SIMPLE).generated
        assert "static u32 bleck_needs_start = 1;" in out.text
        assert "(SeqFunc *) 1" in out.text

    def test_sequence_table_is_referenced_by_name(self):
        out = compile_source(SIMPLE).generated
        assert "extern SeqDef seq_data[];" in out.text
        assert "0x80" not in out.text

    def test_all_rel_entry_points_are_defined(self):
        out = compile_source("script main {\n wait(1)\n}").generated
        for symbol in ("_prolog", "_epilog", "_unresolved"):
            assert f"void {symbol}(void)" in out.text

    def test_missing_main_is_rejected(self):
        with pytest.raises(ScriptError, match=r"no script named 'main'"):
            compile_source("script helper {\n wait(1)\n}")

    def test_output_is_ascii(self):
        # Three host compilers disagree about default source encoding.
        out = compile_source(
            'script main {\n evt_msg_print_add(0, "café — ok")\n}'
        ).generated
        out.text.encode("ascii")

    def test_non_ascii_strings_survive_as_octal_escapes(self):
        out = compile_source('script main {\n evt_msg_print_add(0, "café")\n}').generated
        # 'é' is 0xC3 0xA9 in UTF-8 -> \303\251
        assert "\\303\\251" in out.text

    def test_quotes_and_backslashes_are_escaped(self):
        source = 'script main {\n evt_msg_print_add(0, "a\\"b\\\\c")\n}'
        assert '\\"' in compile_source(source).generated.text

    def test_forward_declares_scripts_when_several_exist(self):
        source = "script main {\n spawn helper\n}\nscript helper {\n wait(1)\n}"
        out = compile_source(source).generated
        assert "extern const s32 bleck_script_helper[];" in out.text


#: A script named the way a map hook expects to find it.
MAP_SOURCE = "script on_arrive {\n gw[31] = 1\n}"


class TestMapHooks:
    """Running a script when a named map is reached.

    Deliberately not the obvious mechanism: patching `MapData.initScript`
    deadlocks the map loader (D51).
    """

    def _generated(self, source=MAP_SOURCE, hooks=(("aa4_01", "on_arrive"),)):
        return compile_source(
            source,
            scaffolding=emit.Scaffolding(
                map_hooks=[emit.MapHook(map_name=m, script=s) for m, s in hooks]
            ),
        ).generated.text

    def test_it_does_not_touch_the_map_s_own_init_script(self):
        # Checks for the mechanism -- a lookup and a write into MapData.
        out = self._generated()
        assert "mapDataPtr" not in out
        assert "BLECK_MAP_INIT_OFFSET" not in out
        assert "->initScript" not in out

    def test_it_watches_where_the_game_says_it_is_going(self):
        out = self._generated()
        assert "seqWork.p0" in out
        assert 'bleck_map_name_0[] = "aa4_01"' in out

    def test_the_script_starts_on_gameplay_not_during_the_change(self):
        """evt state is rebuilt across a map change, so starting early is lost."""
        out = self._generated()
        watcher = out.split("static void bleck_maps_on_seq")[1]
        # The pending bit is set during the change...
        assert "bleck_map_pending |= (1 << i)" in watcher
        # ...and only spent once gameplay is back.
        assert "seq != BLECK_SEQ_GAME" in watcher
        assert watcher.index("bleck_map_pending |=") < watcher.index("evtEntry(")

    def test_a_map_hook_needs_no_main_script(self):
        """`main` is what the sequence hook free-runs; a map hook starts itself."""
        out = self._generated()
        assert "bleck_script_on_arrive" in out
        assert "bleck_start_entry" not in out

    def test_a_script_and_map_hooks_share_one_set_of_hooks(self):
        out = self._generated(
            source="script main {\n wait(1)\n}\nscript on_arrive {\n gw[31] = 1\n}",
        )
        assert out.count("seq_data[i].main = bleck_hooks[i]") == 1
        assert "bleck_maps_on_seq(seq)" in out
        assert "bleck_start_entry(seq)" in out

    def test_several_maps_each_get_a_bit(self):
        out = self._generated(
            source="script a {\n gw[31] = 1\n}\nscript b {\n gw[31] = 2\n}",
            hooks=(("aa4_01", "a"), ("ls4_12", "b")),
        )
        assert "BLECK_MAP_COUNT 2" in out
        assert 'bleck_map_name_1[] = "ls4_12"' in out
        assert "bleck_script_b," in out

    def test_an_unknown_script_is_rejected_against_the_source(self):
        # Manifest and source only meet at generation, so name both in the error.
        with pytest.raises(ScriptError) as caught:
            self._generated(hooks=(("aa4_01", "on_arrve"),))
        assert "on_arrve" in str(caught.value)
        assert "aa4_01" in str(caught.value)
        assert "on_arrive" in str(caught.value)  # the suggestion

    def test_map_names_survive_the_manifest_round_trip(self):
        spec = mod_manifest.CodeSpec(
            script="s.evt", maps=[mod_manifest.MapHook("aa4_01", "on_arrive")]
        )
        assert spec.to_json()["maps"] == {"aa4_01": "on_arrive"}

    def test_a_malformed_maps_block_is_rejected(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"code\.maps"):
            mod_manifest.Manifest.from_json(
                json.dumps(
                    {"schema": 1, "name": "x", "code": {"script": "s", "maps": []}}
                ),
                source="test",
            )


class TestBanner:
    """The on-screen label naming the loaded mod.

    A modded disc otherwise looks stock, so the banner is generated for every
    mod rather than opted into.
    """

    def test_it_draws_only_on_the_sequences_it_was_given(self):
        banner = emit.Banner(text="hi", sequences=(1,))
        assert banner.flags == "0, 1, 0, 0, 0, 0"

        both = emit.Banner(text="hi", sequences=(1, 2))
        assert both.flags == "0, 1, 1, 0, 0, 0"

    def test_it_defaults_to_the_title_screen(self):
        # Where someone actually looks to see which disc they put in.
        assert emit.Banner(text="hi").sequences == (emit.SEQUENCE_NAMES.index("title"),)

    def test_the_text_is_embedded_as_a_c_string(self):
        out = emit.generate_bare(banner=emit.Banner(text="mod_loaded: foo")).text
        assert 'bleck_banner_text[] = "mod_loaded: foo"' in out

    def test_a_sources_only_mod_gains_sequence_hooks_for_the_banner(self):
        """Drawing needs a per-frame hook even when there is no script — a
        native-only module otherwise installs none."""
        plain = emit.generate_bare().text
        assert "seq_data" not in plain

        with_banner = emit.generate_bare(banner=emit.Banner(text="x")).text
        assert "seq_data[i].main = bleck_hooks[i]" in with_banner
        assert "bleck_draw_banner()" in with_banner
        # No script machinery. Match the call, not the word: it appears in a
        # generated comment.
        assert "evtEntry(" not in with_banner

    def test_a_script_and_a_banner_share_one_set_of_hooks(self):
        out = compile_source(
            SIMPLE,
            scaffolding=emit.Scaffolding(banner=emit.Banner(text="x", sequences=(1, 2))),
        ).generated.text
        # One installer, not two layers of them.
        assert out.count("seq_data[i].main = bleck_hooks[i]") == 1
        assert out.count("static void bleck_after_seq") == 1
        # Both jobs happen in it.
        assert "bleck_draw_banner()" in out
        assert "evtEntry(" in out

    def test_it_draws_before_delegating_to_the_real_sequence_main(self):
        """Ordering copied from `spm-rel-loader`, the only known-working use."""
        out = emit.generate_bare(banner=emit.Banner(text="x")).text
        body = out.split("static void bleck_after_seq")[1]
        assert body.index("bleck_draw_banner()") < body.index("bleck_real_main[seq]")

    def test_the_colour_is_writable_because_the_game_overwrites_alpha(self):
        # fontmgr.h: "Warning: Overwrites color.a" -- const would write .rodata.
        out = emit.generate_bare(banner=emit.Banner(text="x")).text
        assert "static u8 bleck_banner_color[4]" in out
        assert "const u8 bleck_banner_color" not in out

    def test_nothing_the_banner_needs_lands_in_bss(self):
        """The loader's bss handling is undocumented, so nothing may rely on it."""
        out = emit.generate_bare(banner=emit.Banner(text="x")).text
        # Every banner object is either const (.rodata) or non-zero (.data).
        assert "static const char bleck_banner_text[]" in out
        assert "static const u8 bleck_banner_on[BLECK_SEQ_COUNT] = {" in out
        assert "bleck_banner_color[4] = {255, 255, 255, 255}" in out

    def test_generated_c_stays_ascii_for_an_awkward_mod_name(self):
        # Names come from a manifest someone else wrote.
        out = emit.generate_bare(banner=emit.Banner(text="mod_loaded: café")).text
        out.encode("ascii")


class TestGeneratedHandoff:
    """How generated scaffolding hands control to a mod's own C."""

    def test_the_hook_is_a_weak_definition_not_a_declaration(self):
        """A weak *declaration* leaves an undefined symbol, which `elf2rel`
        rejects with "Missing 1 required symbol(s): mod_prolog"."""
        out = compile_source(SIMPLE).generated.text
        assert "__attribute__((weak)) void mod_prolog(void)\n{\n}" in out
        assert "__attribute__((weak)) void mod_prolog(void);" not in out
        # With a definition present the address is never null; -Waddress flags a guard.
        assert "if (mod_prolog != 0)" not in out

    def test_generated_code_keeps_ownership_of_prolog(self):
        """Sequence hooks must be installed before the mod's own code runs."""
        out = compile_source(SIMPLE).generated.text
        prolog = out.split("void _prolog(void)")[1]
        assert prolog.index("seq_data[i].main") < prolog.index("mod_prolog()")

    def test_a_sources_only_module_still_has_the_entry_points(self):

        out = emit.generate_bare().text
        for symbol in ("_prolog", "_epilog", "_unresolved"):
            assert f"void {symbol}(void)" in out
        # Nothing to schedule, so no sequence machinery.
        assert "seq_data" not in out
        assert "evtEntry" not in out

    def test_a_sources_only_module_still_calls_the_mod(self):

        assert "mod_prolog();" in emit.generate_bare().text


class TestInstructionPatching:
    """The PowerPC write-and-flush helpers every module carries (D94)."""

    def sources(self) -> list[str]:
        """Every shape of generated module, so none can quietly lose them."""
        return [
            compile_source(SIMPLE).generated.text,
            emit.generate_bare().text,
            emit.generate_merged(
                [
                    emit.ModPart(
                        "a",
                        compile_source(
                            SIMPLE, scaffolding=emit.Scaffolding(require_entry=False)
                        ).program,
                    )
                ]
            ).text,
        ]

    def test_every_module_carries_them(self):
        for out in self.sources():
            for name in ("bleck_code_store", "bleck_code_flush", "bleck_code_write"):
                assert f"void {name}(" in out
            assert "s32 bleck_code_branch(" in out
            assert "s32 bleck_code_hook(" in out

    def test_the_flush_is_the_full_four_instruction_sequence(self):
        """`dcbst` alone leaves the fetcher reading a stale line, and a store
        with no flush was measured doing exactly nothing in-game (D94)."""
        out = compile_source(SIMPLE).generated.text
        flush = out.split("void bleck_code_flush")[1].split("\n}")[0]
        for instruction in ("dcbst 0,%0", "sync", "icbi 0,%0", "isync"):
            assert instruction in flush
        assert flush.index("dcbst") < flush.index("icbi")

    def test_the_unflushed_store_stays_unflushed(self):
        """It exists to be the control. A flush creeping in would make the
        experiment pass for the wrong reason."""
        out = compile_source(SIMPLE).generated.text
        store = out.split("void bleck_code_store")[1].split("\n}")[0]
        assert "dcbst" not in store and "icbi" not in store

    def test_an_out_of_range_branch_is_refused_not_truncated(self):
        """Masking a 26-bit field would emit a valid branch somewhere else."""
        out = compile_source(SIMPLE).generated.text
        assert "#define BLECK_CODE_MAX 0x01FFFFFC" in out
        assert "#define BLECK_CODE_MIN (-0x02000000)" in out
        assert "return BLECK_CODE_RANGE;" in out
        # The write is downstream of the encode, never beside it.
        hook = out.split("s32 bleck_code_hook")[1].split("\n}")[0]
        assert hook.index("if (status != BLECK_CODE_OK)") < hook.index("bleck_code_write")

    def test_the_branch_opcode_is_the_i_form(self):
        out = compile_source(SIMPLE).generated.text
        assert "#define BLECK_CODE_BRANCH 0x48000000U" in out
        assert "#define BLECK_CODE_DISP 0x03FFFFFCU" in out


class TestCxxConstructorWalk:
    """`.ctors` is emitted for C++ globals and nothing else walks it in a REL."""

    def _armed(self, **kwargs) -> str:
        return compile_source(
            SIMPLE, scaffolding=emit.Scaffolding(run_cxx_ctors=True, **kwargs)
        ).generated.text

    def test_a_c_only_module_gains_nothing(self):
        """C-only output has to stay byte-identical to before C++ existed."""
        out = compile_source(SIMPLE).generated.text
        assert "bleck_run_ctors" not in out
        assert ".ctors" not in out

    def test_the_markers_bracket_the_table(self):
        out = self._armed()
        # Plain `.ctors` first in link order, `.ctors.*` sorted after it.
        assert 'section(".ctors")' in out
        assert out.index('section(".ctors")') < out.index('section(".ctors.')

    def test_constructors_run_before_the_mod_takes_over(self):
        """Globals must be built before any of a mod's own code sees them."""
        prolog = self._armed().split("void _prolog(void)")[1]
        assert prolog.index("bleck_run_ctors()") < prolog.index("mod_prolog()")

    def test_null_entries_are_skipped(self):
        """Alignment padding between contributions is not a function pointer."""
        assert "if (*entry != 0)" in self._armed()

    def test_the_bounds_are_hidden_from_the_optimiser(self):
        """The markers are separate objects, so a folded compare could legally
        delete the whole loop; only the linker makes them one table."""
        # Only the walk's own asm counts: the cache-flush helper has one too.
        walk = self._armed().split("static void bleck_run_ctors")[1]
        assert walk.split("void _prolog")[0].count("__asm__") == 2

    def test_a_sources_only_module_can_arm_it_too(self):
        """A mod with C++ and no script still needs its globals constructed."""
        out = emit.generate_bare(run_cxx_ctors=True).text
        assert "bleck_run_ctors();" in out
        assert "seq_data" not in out

    def test_a_merged_module_walks_one_table(self):
        parts = [
            emit.ModPart(name=name, program=compile_source(SIMPLE).program)
            for name in ("alpha", "beta")
        ]
        out = emit.generate_merged(parts, run_cxx_ctors=True).text
        assert out.count("bleck_run_ctors(void)") == 1
        assert out.count('section(".ctors")') == 1
