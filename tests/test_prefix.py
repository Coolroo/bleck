"""Namespacing generated identifiers, so several mods can share one module.

Step 1 of `docs/plan-merging.md`. Nothing merges yet — this only makes the
names *capable* of not colliding, which is the part that touches every emitted
identifier and is therefore worth landing on its own.

The load-bearing assertion is that a single-mod build is unchanged. Everything
else here is new surface.
"""

from __future__ import annotations

import pytest

from bleck.script import compile_source, emit
from bleck.script.errors import ScriptError

SOURCE = "script main {\n wait(1)\n}"


class TestSlug:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("hard-mode", "hard_mode"),
            ("tex-koopa", "tex_koopa"),
            ("Hard Mode", "hard_mode"),
            ("a.b.c", "a_b_c"),
            ("--leading", "leading"),
            ("trailing--", "trailing"),
        ],
    )
    def test_names_reduce_to_identifiers(self, name, expected):
        assert emit.mod_slug(name) == expected

    def test_a_leading_digit_is_moved_out_of_the_way(self):
        """Legal inside an identifier, not at the start of one — and mod names
        are otherwise unrestricted."""
        assert emit.mod_slug("2fast").startswith("m")

    def test_the_prefix_is_readable_not_hashed(self):
        """A build log, a disassembly and a linker error should all still say
        which mod a symbol came from."""
        assert emit.prefix_for("hard-mode") == "bleck_hard_mode_"

    def test_a_name_with_nothing_usable_is_refused(self):
        with pytest.raises(ScriptError, match="no characters usable"):
            emit.prefix_for("!!!")

    def test_two_names_can_collide_and_that_is_visible(self):
        """`hard-mode` and `hard mode` reduce to the same thing. Callers have to
        detect it; this test pins the fact so the collision check has something
        to be about."""
        assert emit.mod_slug("hard-mode") == emit.mod_slug("hard mode")


class TestNamespacedOutput:
    def _generated(self, prefix):
        return compile_source(
            SOURCE, scaffolding=emit.Scaffolding(prefix=prefix)
        ).generated.text

    def test_scripts_take_the_namespace(self):
        out = self._generated(emit.prefix_for("hard-mode"))
        assert "bleck_hard_mode_script_main" in out
        assert "bleck_script_main" not in out

    def test_strings_take_the_namespace(self):
        out = compile_source(
            'script main {\n evt_seq_mapchange("mac_01", 0)\n}',
            scaffolding=emit.Scaffolding(prefix=emit.prefix_for("m")),
        ).generated.text
        assert "bleck_m_string_0" in out

    def test_map_name_literals_take_the_namespace(self):
        out = compile_source(
            "script on_arrive {\n gw[31] = 1\n}",
            scaffolding=emit.Scaffolding(
                map_hooks=[emit.MapHook("aa4_01", "on_arrive")],
                prefix=emit.prefix_for("m"),
            ),
        ).generated.text
        assert "bleck_m_map_name_0" in out

    def test_two_mods_do_not_collide(self):
        """The whole point: both declare `main`, neither emits the same symbol."""
        one = self._generated(emit.prefix_for("alpha"))
        two = self._generated(emit.prefix_for("beta"))
        assert "bleck_alpha_script_main" in one
        assert "bleck_beta_script_main" in two
        assert "bleck_alpha_script_main" not in two


class TestSharedRuntimeIsNotNamespaced:
    """One-per-disc names must stay fixed however many mods contribute.

    The sequence hooks are installed once, in one `_prolog`. Namespacing them
    would not merely be unnecessary, it would be wrong — there would be several
    installs fighting over `seq_data`.
    """

    @pytest.mark.parametrize(
        "symbol",
        [
            "void _prolog(void)",
            "void _epilog(void)",
            "void _unresolved(void)",
            "mod_prolog",
            "bleck_after_seq",
            "bleck_seq0",
            "bleck_hooks",
            "bleck_real_main",
        ],
    )
    def test_it_keeps_its_fixed_name(self, symbol):
        out = compile_source(
            SOURCE, scaffolding=emit.Scaffolding(prefix=emit.prefix_for("hard-mode"))
        ).generated.text
        assert symbol in out


class TestMapHookCap:
    """`bleck_map_pending` is a u32 bitmask, one bit per hook.

    Exceeding it was silent: `1 << i` past bit 31 is undefined behaviour, and
    hooks would corrupt each other rather than anything failing. Unreachable
    with one mod; plausible once mods merge.
    """

    def _hooks(self, count):
        return [emit.MapHook(f"map_{i:02d}", "on_arrive") for i in range(count)]

    def test_thirty_two_is_allowed(self):
        out = compile_source(
            "script on_arrive {\n gw[31] = 1\n}",
            scaffolding=emit.Scaffolding(map_hooks=self._hooks(32)),
        ).generated.text
        assert "BLECK_MAP_COUNT 32" in out

    def test_thirty_three_is_refused(self):
        with pytest.raises(ScriptError, match="at most 32"):
            compile_source(
                "script on_arrive {\n gw[31] = 1\n}",
                scaffolding=emit.Scaffolding(map_hooks=self._hooks(33)),
            )

    def test_the_error_says_why(self):
        # "Too many" without the reason invites someone to just raise the limit.
        with pytest.raises(ScriptError) as caught:
            compile_source(
                "script on_arrive {\n gw[31] = 1\n}",
                scaffolding=emit.Scaffolding(map_hooks=self._hooks(33)),
            )
        assert "32-bit" in str(caught.value)


class TestDefaultIsUnchanged:
    """The constraint the whole step is measured against."""

    def test_the_default_prefix_is_what_was_always_emitted(self):
        assert emit.Scaffolding().prefix == "bleck_"

    def test_a_default_build_still_says_bleck_script_main(self):
        assert "bleck_script_main" in compile_source(SOURCE).generated.text
