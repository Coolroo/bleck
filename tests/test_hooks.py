"""`code.hooks`: a manifest declaration -> a branch over a game function.

The mechanism is measured (D94, D95); these check the declarative path expresses
it, that the guard is *derived* rather than invented, and that what cannot work
is refused before the toolchain runs.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from bleck.api import v1
from bleck.backends import dol
from bleck.backends.symbols import Symbol, SymbolTable
from bleck.mods import code
from bleck.mods import manifest as mod_manifest
from bleck.mods.registry import Mod
from bleck.script import compile_source, emit

HOOK = emit.FunctionHook(
    call="count_npcs",
    address=0x801ADEF0,
    symbol="npcDispMain",
    expect=0x9421FE40,
    guarded=True,
)

WHOLE = {"function": "npcDispMain", "call": "count_npcs", "mode": "replace"}

REPO = Path(__file__).resolve().parents[1]


def generated(hooks=(HOOK,)):
    return emit.generate_bare(origin="x", function_hooks=list(hooks)).text


def manifest(hook: dict) -> mod_manifest.Manifest:
    return mod_manifest.Manifest.from_json(
        json.dumps({"name": "m", "code": {"sources": ["src"], "hooks": [hook]}})
    )


def make_dol(
    tmp_path, address: int = 0x801ADEF0, word: int = 0x9421FE40, text: bool = True
):
    """A one-section DOL holding `word` at `address`, for guard derivation.

    `text=False` puts it in the first data slot instead, which is section 7 and
    so shifts each of the three tables by 7 words.
    """
    header = bytearray(0x100)
    body = bytearray(0x40)
    slot = 0 if text else dol.TEXT_SECTIONS
    struct.pack_into(">I", header, 0x00 + slot * 4, 0x100)  # file offset
    struct.pack_into(">I", header, 0x48 + slot * 4, address - 0x20)  # load address
    struct.pack_into(">I", header, 0x90 + slot * 4, len(body))  # size
    struct.pack_into(">I", body, 0x20, word)
    path = tmp_path / "sys" / "main.dol"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header) + bytes(body))
    return path


TABLE = SymbolTable(
    symbols=[
        Symbol(name="npcDispMain", address=0x801ADEF0, kind="function"),
        Symbol(name="effMain", address=0x800618B0, kind="function"),
    ],
    source=Path("spm.eu0.lst"),
)


class TestGeneratedCode:
    def test_the_branch_target_is_left_to_the_linker(self):
        """A named function keeps the symbol list as the one source of truth."""
        out = generated()
        assert "extern void npcDispMain(void);" in out
        assert "(void *) &npcDispMain" in out
        assert "0x801ADEF0" not in out

    def test_a_raw_address_is_written_out(self):
        """There is no symbol to leave to the linker, so the number is the input."""
        out = generated([emit.FunctionHook(call="f", address=0x80F60000)])
        assert "(void *) 0x80F60000u" in out

    def test_the_derived_guard_is_the_word_the_build_read(self):
        out = generated()
        assert "0x9421FE40u, 1u" in out
        assert "expect 9421FE40" in out

    def test_an_underived_guard_is_not_faked(self):
        """`guarded` off, and the row says so rather than carrying a zero word."""
        out = generated([emit.FunctionHook(call="f", address=0x80F60000)])
        assert "0x00000000u, 0u" in out
        assert "UNGUARDED" in out

    def test_the_guard_refuses_rather_than_writing_blind(self):
        body = generated().split("static void bleck_install_hooks")[1]
        refuse = body.index("BLECK_HOOK_REFUSED")
        assert body.index("*(volatile u32 *) hook->at != hook->expect") < refuse
        assert refuse < body.index("bleck_code_hook(hook->at, hook->call)")

    def test_a_bad_encoding_is_its_own_status(self):
        """Out of range must be distinguishable from a guard mismatch."""
        out = generated()
        assert "BLECK_HOOK_MISALIGNED" in out
        assert "BLECK_HOOK_OUT_OF_RANGE" in out

    def test_the_status_table_is_readable_from_a_mod(self):
        out = generated()
        # Not static, and not in .bss: the loader does not document zeroing it.
        assert "u32 bleck_hook_status[BLECK_HOOK_COUNT] = {" in out
        assert "static u32 bleck_hook_status" not in out
        assert "BLECK_HOOK_PENDING," in out
        assert "const u32 bleck_hook_count = BLECK_HOOK_COUNT;" in out

    def test_each_name_is_declared_once(self):
        second = emit.FunctionHook(
            call="other", address=0x801ADEF0, symbol="npcDispMain", guarded=True
        )
        out = generated([HOOK, second])
        assert out.count("extern void npcDispMain(void);") == 1
        assert "extern void other(void);" in out
        assert "#define BLECK_HOOK_COUNT 2" in out

    def test_it_is_installed_before_mod_prolog(self):
        """So a mod's own C can read the status it is about to report."""
        prolog = generated().split("void _prolog(void)")[1]
        assert prolog.index("bleck_install_hooks();") < prolog.index("mod_prolog();")

    def test_the_replacement_warning_is_in_the_generated_source(self):
        """The generated file is what a user opens when a hook misbehaves, so
        the mode that destroys the original has to say so there."""
        assert "THE ORIGINAL NEVER RUNS" in generated()

    def test_nothing_is_emitted_without_hooks(self):
        assert "bleck_install_hooks" not in emit.generate_bare(origin="x").text


class TestTrace:
    """The self-healing detour: watching a hooked function rather than
    replacing it (D96).

    Nothing declares a trace -- it is a pattern over `code.hooks` plus these
    helpers -- so what is checked here is that the helpers exist beside the
    table, that the restore uses the *derived* word, and that the ordering the
    reentrancy argument depends on is the ordering emitted.
    """

    def test_the_helpers_ride_along_with_the_table(self):
        out = generated()
        for name in (
            "u32 bleck_trace_open(u32 index)",
            "void bleck_trace_close(u32 index)",
            "void bleck_trace_args(u32 index",
            "void bleck_trace_result(u32 index",
            "u32 bleck_hook_original(u32 index)",
        ):
            assert name in out

    def test_a_record_exists_per_hook_and_stays_out_of_bss(self):
        out = generated([HOOK, emit.FunctionHook(call="other", address=0x800618B0)])
        rows = out.split("BleckTrace bleck_traces[BLECK_HOOK_COUNT] = {")[1]
        assert rows.split("};")[0].count("BLECK_TRACE_MAGIC") == 2
        assert "static BleckTrace bleck_traces" not in out

    @staticmethod
    def _body(signature: str) -> str:
        """The definition's body. The last match, because the block's own
        header comment shows each prototype first."""
        return generated().split(signature)[-1].split("\n}")[0]

    def test_the_restore_puts_back_the_derived_word(self):
        """Not a word read at run time: the same guard the install compared."""
        body = self._body("u32 bleck_trace_open(u32 index)")
        assert "bleck_code_write(hook->at, hook->expect);" in body

    def test_it_restores_before_it_counts(self):
        """The whole reentrancy argument. A second entry can only land before
        the restore, where repeating the same store is harmless."""
        body = self._body("u32 bleck_trace_open(u32 index)")
        assert body.index("bleck_code_write") < body.index("trace->depth += 1")

    def test_an_unguarded_hook_cannot_be_traced(self):
        """There is no original word to put back, so the original must not be
        called -- its first instruction is still the branch."""
        body = self._body("u32 bleck_trace_open(u32 index)")
        assert "if (!hook->guarded" in body
        assert "trace->blind += 1;" in body
        assert "return 0;" in body

    def test_the_branch_is_re_armed_only_at_depth_zero(self):
        body = self._body("void bleck_trace_close(u32 index)")
        assert body.index("trace->depth -= 1") < body.index("bleck_code_hook")
        assert "if (trace->depth == 0)" in body

    def test_the_float_hazard_is_written_down_where_it_is_used(self):
        """A float argument silently reading as nothing is exactly the sort of
        thing that becomes a wrong recorded fact."""
        out = generated()
        assert "FLOAT ARGUMENTS" in out
        assert "FLOAT AND STRUCT RETURNS" in out

    def test_nothing_is_emitted_without_hooks(self):
        assert "bleck_trace_open" not in emit.generate_bare(origin="x").text


class TestInterception:
    """`before` and `after` wrap the hook rather than replacing it (D97)."""

    def _wrapped(self, mode: str) -> str:
        hook = emit.FunctionHook(
            call="watch",
            address=0x801ADEF0,
            symbol="npcDispMain",
            expect=0x9421FE40,
            guarded=True,
            mode=mode,
        )
        return generated([hook])

    def test_replace_emits_no_wrapper_and_branches_straight_at_the_call(self):
        out = generated()
        assert "bleck_hook_wrap_0" not in out
        assert "(const void *) &count_npcs" in out

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_the_game_branches_to_the_wrapper_not_the_handler(self, mode):
        out = self._wrapped(mode)
        assert "(const void *) &bleck_hook_wrap_0" in out
        assert "(const void *) &watch" not in out

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_every_argument_register_is_saved_and_restored(self, mode):
        """The whole reason the wrapper is assembly.

        A generated C wrapper would have to guess a signature, and guessing an
        integer one drops f1-f8 -- silently, and only for the functions that
        take floats. If these disappear, that hazard is back.
        """
        out = self._wrapped(mode)
        for reg in range(3, 11):
            assert f"stw   {reg}," in out
            assert f"lwz   {reg}," in out
        for reg in range(1, 9):
            assert f"stfd  {reg}," in out
            assert f"lfd   {reg}," in out

    def test_before_runs_the_handler_ahead_of_the_original(self):
        out = self._wrapped("before")
        assert out.index("bl    watch") < out.index("bl    bleck_trace_open")

    def test_after_runs_the_handler_behind_the_original(self):
        out = self._wrapped("after")
        assert out.index("bl    bleck_trace_close") < out.index("bl    watch")

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_the_caller_receives_the_original_s_return_value(self, mode):
        """The result comes out of the frame slot the ORIGINAL wrote, and is
        reloaded last. So a handler cannot change what the game sees by
        returning something, whichever side of the original it runs on."""
        out = self._wrapped(mode)
        # Captured straight off the indirect call, from nowhere else.
        assert 'bctrl\\n"\n    "    stw   3, 0x68(1)' in out
        assert out.count("stw   3, 0x68(1)") == 1
        # Reloaded after the handler has had its turn, in both orderings.
        assert out.rindex("bl    watch") < out.rindex("lwz   3, 0x68(1)")

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_the_original_is_called_through_ctr_not_a_branch(self, mode):
        """A `bl` would be a 26-bit relative branch from the module to the DOL,
        which can be out of range."""
        out = self._wrapped(mode)
        assert "mtctr 0" in out
        assert "bctrl" in out
        assert "bl    npcDispMain" not in out

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_a_detour_that_cannot_open_does_not_call_the_original(self, mode):
        """Unreachable by construction -- the build refuses an unguarded
        interception -- but 'unreachable' and 'safe' are different claims."""
        out = self._wrapped(mode)
        assert "cmpwi 3, 0" in out
        assert "beq   .Lblind_0" in out

    def test_each_hook_gets_its_own_wrapper_and_index(self):
        first = emit.FunctionHook(
            call="a",
            address=0x801ADEF0,
            symbol="npcDispMain",
            expect=1,
            guarded=True,
            mode="before",
        )
        second = emit.FunctionHook(
            call="b",
            address=0x800618B0,
            symbol="effMain",
            expect=2,
            guarded=True,
            mode="after",
        )
        out = generated([first, second])
        assert "bleck_hook_wrap_0:" in out
        assert "bleck_hook_wrap_1:" in out
        assert "li    3, 1" in out  # the second wrapper passes its own index

    def test_a_replace_hook_beside_an_intercepting_one_keeps_its_own_shape(self):
        plain = emit.FunctionHook(
            call="taken_over",
            address=0x800618B0,
            symbol="effMain",
            expect=2,
            guarded=True,
        )
        watched = emit.FunctionHook(
            call="watch",
            address=0x801ADEF0,
            symbol="npcDispMain",
            expect=1,
            guarded=True,
            mode="before",
        )
        out = generated([plain, watched])
        assert "(const void *) &taken_over" in out
        assert "(const void *) &bleck_hook_wrap_1" in out
        assert "bleck_hook_wrap_0" not in out


class TestMerging:
    def _part(self, name):
        return emit.ModPart(
            name=name,
            program=compile_source(
                "script main {\n gw[30] = 1\n}",
                scaffolding=emit.Scaffolding(require_entry=False),
            ).program,
        )

    def test_the_table_is_the_union(self):
        second = emit.FunctionHook(
            call="other", address=0x800618B0, symbol="effMain", guarded=True
        )
        out = emit.generate_merged(
            [self._part("alpha"), self._part("beta")], function_hooks=[HOOK, second]
        ).text
        assert "#define BLECK_HOOK_COUNT 2" in out
        assert "extern void count_npcs(void);" in out
        assert "extern void other(void);" in out

    def test_a_merge_without_hooks_emits_none(self):
        assert "bleck_install_hooks" not in emit.generate_merged([self._part("a")]).text


class TestManifest:
    def test_it_parses_and_round_trips(self):
        parsed = manifest(WHOLE)
        assert parsed.code.hooks == [
            mod_manifest.FunctionHook(
                function="npcDispMain", call="count_npcs", mode="replace"
            )
        ]
        assert parsed.code.has_hooks
        again = mod_manifest.Manifest.from_json(parsed.to_json())
        assert again.code == parsed.code

    def test_mode_defaults_to_replace(self):
        assert manifest({"function": "npcDispMain", "call": "f"}).code.hooks[0].mode == (
            "replace"
        )

    def test_absent_when_unset(self):
        assert "hooks" not in mod_manifest.CodeSpec(script="a.evt").to_json()

    def test_a_raw_address_is_accepted(self):
        hook = manifest({**WHOLE, "function": "0x801adef0"}).code.hooks[0]
        assert hook.is_address
        assert hook.address == 0x801ADEF0

    def test_a_symbol_name_is_not_an_address(self):
        assert manifest(WHOLE).code.hooks[0].address == -1

    def test_a_misaligned_address_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="not 4-byte aligned"):
            manifest({**WHOLE, "function": "0x801adef2"})

    def test_an_address_outside_ram_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="not a game address"):
            manifest({**WHOLE, "function": "0x00001000"})

    def test_a_nonsense_function_says_what_the_field_takes(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "function": "npc disp main"})
        assert "symbol list" in str(caught.value)

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="unknown field"):
            manifest({**WHOLE, "at": 4})

    def test_an_object_instead_of_a_list_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"code\.hooks"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "s", "hooks": {}}}'
            )

    def test_a_call_that_is_not_an_identifier_is_refused(self):
        with pytest.raises(mod_manifest.ManifestError, match="not a C function name"):
            manifest({**WHOLE, "call": "count npcs"})


class TestMode:
    """`replace` takes the function over; `before` and `after` keep it."""

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_the_intercepting_modes_are_accepted(self, mode):
        hook = manifest({**WHOLE, "mode": mode}).code.hooks[0]
        assert hook.mode == mode
        assert hook.intercepts

    def test_replace_does_not_intercept(self):
        assert not manifest(WHOLE).code.hooks[0].intercepts

    def test_a_nonsense_mode_says_what_each_real_one_does(self):
        with pytest.raises(mod_manifest.ManifestError) as caught:
            manifest({**WHOLE, "mode": "around"})
        message = str(caught.value)
        assert "not a hook mode" in message
        # The names alone do not say which order they run in, which is the only
        # thing a reader picking between them needs.
        assert "the mod's function first, then the original" in message
        assert "the original first, then the mod's function" in message


class TestDol:
    """Guard derivation reads the game's own DOL, or admits it could not."""

    def test_a_section_maps_an_address_to_a_word(self, tmp_path):
        parsed = dol.read(make_dol(tmp_path))
        assert parsed.word_at(0x801ADEF0) == 0x9421FE40
        assert parsed.section_for(0x801ADEF0).name == "text0"

    def test_an_address_outside_every_section_has_no_word(self, tmp_path):
        parsed = dol.read(make_dol(tmp_path))
        assert parsed.word_at(0x80F60000) is None
        assert parsed.section_for(0x80F60000) is None

    def test_a_misaligned_address_has_no_word(self, tmp_path):
        assert dol.read(make_dol(tmp_path)).word_at(0x801ADEF2) is None

    def test_the_real_eu0_dol_reads(self):
        """The measured value, so a refactor cannot quietly change the mapping."""
        path = REPO / "work/extracted/eu0/sys/main.dol"
        if not path.is_file():
            pytest.skip("no extracted eu0 base")
        assert dol.read(path).word_at(0x801ADEF0) == 0x9421FE40

    def test_a_short_file_is_not_a_dol(self, tmp_path):
        path = tmp_path / "main.dol"
        path.write_bytes(b"\0" * 16)
        with pytest.raises(dol.DolError, match="too short"):
            dol.read(path)

    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(dol.DolError, match="no DOL at"):
            dol.read(tmp_path / "nope.dol")


class TestResolution:
    """Name to address, guard from the DOL, and `call` against the sources."""

    def _mod(self, tmp_path, body: str) -> Mod:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.c").write_text(body, encoding="utf-8")
        (tmp_path / "mod.json").write_text(
            json.dumps({"name": "m", "code": {"sources": ["src"]}}), encoding="utf-8"
        )
        return Mod(root=tmp_path, manifest=mod_manifest.read(tmp_path))

    def _resolve(self, tmp_path, monkeypatch, hook: dict, body: str):
        mod = self._mod(tmp_path, body)
        base = tmp_path / "base"
        make_dol(base)
        monkeypatch.setenv("BLECK_BASE_DIR", str(base))
        spec = manifest(hook).code
        return code.function_hooks_for(mod, spec, code.collect_sources(mod, spec), TABLE)

    def test_a_name_resolves_and_the_guard_is_derived(self, tmp_path, monkeypatch):
        found = self._resolve(tmp_path, monkeypatch, WHOLE, "void count_npcs(void) { }\n")
        assert found.hooks == [HOOK]
        assert not found.warnings

    def test_an_unknown_symbol_fails_the_build_and_suggests(self, tmp_path, monkeypatch):
        with pytest.raises(code.CodeError) as caught:
            self._resolve(
                tmp_path,
                monkeypatch,
                {**WHOLE, "function": "npcDispMainn"},
                "void count_npcs(void) { }\n",
            )
        message = str(caught.value)
        assert "'npcDispMain'" in message  # the suggestion
        assert "not in the symbol list" in message

    def test_a_call_the_sources_do_not_define_is_caught(self, tmp_path, monkeypatch):
        with pytest.raises(code.CodeError) as caught:
            self._resolve(
                tmp_path,
                monkeypatch,
                {**WHOLE, "call": "count_npc"},
                "void count_npcs(void) { }\n",
            )
        message = str(caught.value)
        assert "'count_npcs'" in message  # the suggestion
        assert "the original never runs" in message

    def test_an_address_the_dol_does_not_map_warns_rather_than_faking(
        self, tmp_path, monkeypatch
    ):
        found = self._resolve(
            tmp_path,
            monkeypatch,
            {**WHOLE, "function": "0x80f60000"},
            "void count_npcs(void) { }\n",
        )
        assert found.hooks[0].guarded is False
        assert found.hooks[0].expect == 0
        assert "no derived guard" in found.warnings[0]
        assert "REL address" in found.warnings[0]

    def test_an_address_in_the_dol_s_data_warns(self, tmp_path, monkeypatch):
        """eu0's data reaches 0x805B7720, so an address can look like code."""
        mod = self._mod(tmp_path, "void count_npcs(void) { }\n")
        base = tmp_path / "base"
        make_dol(base, address=0x804A0000, word=0x11223344, text=False)
        monkeypatch.setenv("BLECK_BASE_DIR", str(base))
        spec = manifest({**WHOLE, "function": "0x804a0000"}).code
        found = code.function_hooks_for(mod, spec, code.collect_sources(mod, spec), TABLE)
        assert found.hooks[0].guarded is True
        assert found.hooks[0].expect == 0x11223344
        assert "data, not code" in found.warnings[0]

    def test_no_base_dol_warns_with_the_path_it_looked_at(self, tmp_path, monkeypatch):
        mod = self._mod(tmp_path, "void count_npcs(void) { }\n")
        monkeypatch.setenv("BLECK_BASE_DIR", str(tmp_path / "absent"))
        spec = manifest(WHOLE).code
        found = code.function_hooks_for(mod, spec, code.collect_sources(mod, spec), TABLE)
        assert found.hooks[0].guarded is False
        assert "main.dol" in found.warnings[0]

    def test_nothing_declared_resolves_to_nothing(self, tmp_path):
        mod = self._mod(tmp_path, "void f(void) { }\n")
        spec = mod_manifest.CodeSpec(sources=["src"])
        found = code.function_hooks_for(mod, spec, code.collect_sources(mod, spec), TABLE)
        assert not found.hooks
        assert not found.warnings

    @pytest.mark.parametrize("mode", ["before", "after"])
    def test_interception_without_a_guard_is_refused_not_warned(
        self, tmp_path, monkeypatch, mode
    ):
        """`replace` installs unguarded with a warning; interception cannot.

        The detour reaches the original by restoring the guard word, so with
        nothing to restore this would build cleanly and then branch into itself
        at run time until the stack ran out.
        """
        with pytest.raises(code.CodeError) as caught:
            self._resolve(
                tmp_path,
                monkeypatch,
                {**WHOLE, "function": "0x80f60000", "mode": mode},
                "void count_npcs(void) { }\n",
            )
        message = str(caught.value)
        assert "until the stack ran out" in message
        assert "'replace'" in message  # what to do instead

    def test_the_mode_reaches_the_emitter(self, tmp_path, monkeypatch):
        found = self._resolve(
            tmp_path,
            monkeypatch,
            {**WHOLE, "mode": "after"},
            "void count_npcs(void) { }\n",
        )
        assert found.hooks[0].mode == "after"
        assert found.hooks[0].intercepts


class TestApi:
    def test_it_round_trips_through_the_json_contract(self):
        spec = manifest(WHOLE).code
        document = v1.Code.of(spec)
        assert document.hooks[0].function == "npcDispMain"
        assert document.hooks[0].mode == "replace"
        assert document.to_manifest().hooks == spec.hooks

    def test_the_contract_rejects_what_the_manifest_rejects(self):
        bad = v1.Hook(function="npcDispMain", call="f", mode="around")
        with pytest.raises(mod_manifest.ManifestError, match="not a hook mode"):
            bad.to_manifest()

    def test_the_contract_carries_an_intercepting_mode_through(self):
        hook = v1.Hook(function="npcDispMain", call="f", mode="after")
        assert hook.to_manifest().mode == "after"
