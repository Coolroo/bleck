"""Several mods compiled into one module.

Step 2 of `docs/plan-merging.md`: the loader opens exactly one `/mod/mod.rel`,
so merging at compile time avoids unsolved runtime REL chaining (D39).

⚠️ None of this shows two mods' scripts actually *running* — that needs a game
and two probe slots (compare D51, which installed cleanly and still froze).
"""

from __future__ import annotations

import pytest

from bleck.mods.code import parts
from bleck.script import compile_source, emit
from bleck.script.emit import runtime_c
from bleck.script.errors import ScriptError

LOOPER = "script main {\n wait(1)\n}"
GREETER = "script main {\n gw[30] = 1\n}\nscript greet {\n gw[29] = 1\n}"


def part(name, source, **kwargs):
    return emit.ModPart(
        name=name,
        program=compile_source(
            source, scaffolding=emit.Scaffolding(require_entry=False)
        ).program,
        **kwargs,
    )


def merged(*parts, **kwargs):
    return emit.generate_merged(list(parts), **kwargs).text


class TestNamespacing:
    def test_two_mods_may_both_declare_main(self):
        """The collision the whole feature exists to allow."""
        out = merged(part("alpha", LOOPER), part("beta", GREETER))
        assert "bleck_alpha_script_main" in out
        assert "bleck_beta_script_main" in out

    def test_each_mod_gets_a_labelled_section(self):
        out = merged(part("alpha", LOOPER), part("beta", GREETER))
        assert "   alpha\n" in out
        assert "   beta\n" in out

    def test_strings_do_not_collide(self):
        """String indices are per-program, so two mods both have a string 0."""
        out = merged(
            part("alpha", 'script main {\n evt_seq_mapchange("mac_01", 0)\n}'),
            part("beta", 'script main {\n evt_seq_mapchange("he1_01", 0)\n}'),
        )
        assert "bleck_alpha_string_0" in out
        assert "bleck_beta_string_0" in out

    def test_colliding_slugs_name_both_mods(self):
        # Both reduce to `hard_mode`; unreported it is a baffling linker error.
        with pytest.raises(ScriptError) as caught:
            merged(part("hard-mode", LOOPER), part("hard mode", GREETER))
        message = str(caught.value)
        assert "hard-mode" in message and "hard mode" in message


class TestSharedRuntime:
    """One `_prolog`, one set of hooks, however many mods contributed."""

    @pytest.mark.parametrize(
        "symbol", ["void _prolog(void)", "bleck_after_seq", "bleck_hooks"]
    )
    def test_it_is_emitted_once(self, symbol):
        out = merged(part("alpha", LOOPER), part("beta", GREETER))
        assert out.count(symbol) >= 1
        assert out.count("void _prolog(void)") == 1

    def test_every_mods_entry_script_is_started(self):
        out = merged(part("alpha", LOOPER), part("beta", GREETER))
        table = out.split("bleck_entries[BLECK_ENTRY_COUNT]")[1]
        assert "bleck_alpha_script_main" in table
        assert "bleck_beta_script_main" in table
        assert "BLECK_ENTRY_COUNT 2" in out

    def test_a_mod_without_main_contributes_no_entry(self):
        """With one entry left, the single-mod form is emitted, not a table of one."""
        out = merged(
            part("alpha", LOOPER),
            part("beta", "script greet {\n gw[29] = 1\n}"),
        )
        assert "bleck_entries" not in out
        assert "evtEntry(bleck_alpha_script_main, 0, 0)" in out
        assert "bleck_beta_script_greet" in out  # compiled, just not free-running

    def test_map_hooks_are_unioned_across_mods(self):
        out = merged(
            part("alpha", GREETER, map_hooks=[emit.MapHook("aa4_01", "greet")]),
            part("beta", GREETER, map_hooks=[emit.MapHook("ls4_12", "greet")]),
        )
        assert "BLECK_MAP_COUNT 2" in out
        # Each row points at the mod that declared it, not at one namespace.
        assert "bleck_alpha_script_greet" in out
        assert "bleck_beta_script_greet" in out

    def test_combos_are_unioned_across_mods(self):
        out = merged(
            part("alpha", GREETER, combos=[emit.ComboHook("c1", 0x0300, "greet")]),
            part("beta", GREETER, combos=[emit.ComboHook("c2", 0x0C00, "greet")]),
        )
        assert "BLECK_COMBO_COUNT 2" in out
        assert "0x00000300u" in out and "0x00000C00u" in out

    def test_external_symbols_are_deduplicated(self):
        """Both mods call it; the module declares it once or the C is invalid."""
        source = 'script main {\n evt_seq_mapchange("mac_01", 0)\n}'
        out = merged(part("alpha", source), part("beta", source))
        assert out.count("extern void evt_seq_mapchange(void);") == 1


class TestDiscLevelChoices:
    def test_two_boot_maps_are_refused_naming_both(self):
        """A disc starts in one place."""
        with pytest.raises(ScriptError) as caught:
            merged(
                part("alpha", LOOPER, boot_script="main"),
                part("beta", GREETER, boot_script="main"),
            )
        message = str(caught.value)
        assert "alpha" in message and "beta" in message

    def test_one_boot_map_is_bound_to_its_own_mod(self):
        out = merged(part("alpha", LOOPER), part("beta", GREETER, boot_script="greet"))
        assert "evtEntry(bleck_beta_script_greet, 0, 0)" in out

    def test_the_banner_is_emitted_once(self):
        out = merged(
            part("alpha", LOOPER),
            part("beta", GREETER),
            banner=emit.Banner(text="mod_loaded: beta +1"),
        )
        assert out.count("bleck_draw_banner(void)") == 1
        assert "mod_loaded: beta +1" in out


class TestLimits:
    def test_the_map_cap_applies_to_the_union(self):
        """17 hooks each is fine alone; the union of 34 is not."""
        hooks = [emit.MapHook(f"m{i:02d}", "greet") for i in range(17)]
        with pytest.raises(ScriptError, match="at most 32"):
            merged(
                part("alpha", GREETER, map_hooks=hooks),
                part("beta", GREETER, map_hooks=hooks),
            )

    def test_merging_nothing_is_refused(self):
        with pytest.raises(ScriptError, match="no mods"):
            emit.generate_merged([])


class TestGeneratedCIsValid:
    def test_it_stays_ascii(self):
        # Catches a stray unicode character in the emitted C.
        merged(part("alpha", LOOPER), part("beta", GREETER)).encode("ascii")

    def test_declarations_precede_the_shared_runtime(self):
        """Scripts must be defined before the tables that point at them."""
        out = merged(part("alpha", GREETER, map_hooks=[emit.MapHook("aa4_01", "greet")]))
        assert out.index("const s32 bleck_alpha_script_greet[]") < out.index(
            "bleck_map_scripts"
        )


class TestModPrologCollision:
    """`bleck` emits a weak `mod_prolog`; exactly one mod may override it.

    Two is a duplicate symbol, reported by the linker against object files
    nobody wrote by hand — so bleck names the mods instead.
    """

    def _source(self, tmp_path, name, body):
        path = tmp_path / f"{name}.c"
        path.write_text(body, encoding="utf-8")
        return path

    def test_a_definition_is_found(self, tmp_path):
        source = self._source(
            tmp_path, "a", "void mod_prolog(void)\n{\n    probe[0] = 1;\n}\n"
        )
        assert parts.defines_mod_prolog(source)

    def test_a_declaration_is_not_a_definition(self, tmp_path):
        # `extern void mod_prolog(void);` collides with nothing.
        source = self._source(tmp_path, "a", "extern void mod_prolog(void);\n")
        assert not parts.defines_mod_prolog(source)

    def test_a_block_comment_mentioning_it_does_not_count(self, tmp_path):
        """Mods quote docs-site's "define `mod_prolog`" in comments; prose is
        not a definition."""
        source = self._source(
            tmp_path,
            "a",
            "/*\n    Your code defines mod_prolog(void) { ... } instead.\n*/\n"
            "void other(void) {}\n",
        )
        assert not parts.defines_mod_prolog(source)

    def test_a_line_comment_mentioning_it_does_not_count(self, tmp_path):
        source = self._source(
            tmp_path, "a", "// void mod_prolog(void) { }\nvoid other(void) {}\n"
        )
        assert not parts.defines_mod_prolog(source)

    def test_the_weak_definition_bleck_emits_is_still_a_definition(self):
        """The generated one matches too — hence the check runs on mod sources only."""
        assert "void mod_prolog(void)" in runtime_c.MOD_HOOK
