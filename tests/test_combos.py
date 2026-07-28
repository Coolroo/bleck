"""Button combinations: `bleck.yml` + `code.combos` -> generated C.

A mod names a combination and `bleck.yml` says which buttons it is; the two
only meet at build time, so a mod never contains a button mask.
"""

from __future__ import annotations

import json

import pytest

from bleck.common import config as cfg
from bleck.mods import code
from bleck.mods import manifest as mod_manifest
from bleck.script import ScriptError, compile_source, emit

SOURCE = "script warp {\n gw[31] = 1\n}"


def generated(hooks, source=SOURCE):
    return compile_source(
        source, scaffolding=emit.Scaffolding(combos=hooks)
    ).generated.text


class TestGeneratedWatcher:
    def test_the_mask_reaches_the_table(self):
        out = generated([emit.ComboHook("start_map", 0x0C00, "warp")])
        assert "0x00000C00u,  /* start_map */" in out
        assert "bleck_script_warp," in out

    def test_it_tests_the_mask_rather_than_the_whole_word(self):
        """Bit 31 flips between frames untouched, so `held == mask` is flaky (D67)."""
        out = generated([emit.ComboHook("c", 0x0C00, "warp")])
        assert "(held & bleck_combo_masks[i]) == bleck_combo_masks[i]" in out
        assert "held == bleck_combo_masks" not in out

    def test_it_is_edge_triggered(self):
        """Otherwise a held combination fires sixty times a second."""
        out = generated([emit.ComboHook("c", 0x0C00, "warp")])
        watcher = out.split("static void bleck_combos_on_seq")[1]
        assert "(bleck_combo_down & bit) == 0" in watcher
        assert "bleck_combo_down |= bit" in watcher
        assert "bleck_combo_down &= ~bit" in watcher

    def test_nothing_fires_from_a_button_held_at_boot(self):
        # All-ones: every combo counts as already-held until seen released.
        assert "static u32 bleck_combo_down = 0xFFFFFFFFu;" in generated(
            [emit.ComboHook("c", 0x0C00, "warp")]
        )

    def test_it_waits_for_gameplay(self):
        """evtEntry needs the script VM; watching before gameplay hangs (D65)."""
        watcher = generated([emit.ComboHook("c", 0x0C00, "warp")]).split(
            "static void bleck_combos_on_seq"
        )[1]
        assert "seq != BLECK_SEQ_GAME" in watcher

    def test_the_null_check_is_present(self):
        # wpadGetWork returns null before wpadInit; reading through it faults.
        assert "if (work == 0)" in generated([emit.ComboHook("c", 0x0C00, "warp")])

    def test_a_combo_needs_no_main_script(self):
        out = generated([emit.ComboHook("c", 0x0C00, "warp")])
        assert "bleck_combos_on_seq(seq)" in out
        assert "bleck_start_entry" not in out

    def test_an_unknown_script_is_rejected_against_the_source(self):
        with pytest.raises(ScriptError) as caught:
            generated([emit.ComboHook("start_map", 0x0C00, "wrap")])
        message = str(caught.value)
        assert "start_map" in message and "wrap" in message
        assert "warp" in message  # the suggestion

    def test_more_than_thirty_two_is_refused(self):
        """One bit each in `bleck_combo_down`; the 33rd would shift past the end."""
        hooks = [emit.ComboHook(f"c{i}", 1 << 8, "warp") for i in range(33)]
        with pytest.raises(ScriptError, match="at most 32"):
            generated(hooks)

    def test_thirty_two_is_allowed(self):
        hooks = [emit.ComboHook(f"c{i}", 1 << 8, "warp") for i in range(32)]
        assert "BLECK_COMBO_COUNT 32" in generated(hooks)

    def test_none_of_it_is_emitted_without_combos(self):
        assert "bleck_combos_on_seq" not in emit.generate_bare(origin="x").text


class TestManifest:
    def test_it_parses_and_round_trips(self):
        raw = json.dumps(
            {"name": "m", "code": {"script": "s.evt", "combos": {"start_map": "warp"}}}
        )
        parsed = mod_manifest.Manifest.from_json(raw)
        assert parsed.code.combos == [mod_manifest.ComboBinding("start_map", "warp")]
        assert parsed.code.has_combos
        assert mod_manifest.Manifest.from_json(parsed.to_json()).code == parsed.code

    def test_absent_when_unset(self):
        assert "combos" not in mod_manifest.CodeSpec(script="a.evt").to_json()

    def test_a_list_is_refused(self):
        # An object makes a duplicate binding unwriteable rather than detectable.
        with pytest.raises(mod_manifest.ManifestError, match=r"code\.combos"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "s", "combos": []}}'
            )

    def test_a_binding_must_name_a_script(self):
        with pytest.raises(mod_manifest.ManifestError, match="must name a script"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "s", "combos": {"x": 1}}}'
            )


class TestResolution:
    """Joining `mod.json`'s name to `bleck.yml`'s buttons."""

    class _Mod:
        name = "demo"

    def _spec(self, combo="start_map"):
        return mod_manifest.CodeSpec(
            script="s.evt", combos=[mod_manifest.ComboBinding(combo, "warp")]
        )

    def test_the_mask_comes_from_the_config(self):
        settings = cfg.parse("combos:\n  start_map: [1, 2]\n")
        hooks = code.combo_hooks_for(self._Mod(), self._spec(), settings)
        assert hooks[0].mask == cfg.BUTTON_MASKS["1"] | cfg.BUTTON_MASKS["2"]
        assert hooks[0].script == "warp"

    def test_an_undeclared_combo_names_the_config_and_suggests(self):
        settings = cfg.parse("combos:\n  start_map: [1, 2]\n")
        with pytest.raises(code.CodeError) as caught:
            code.combo_hooks_for(self._Mod(), self._spec("strt_map"), settings)
        message = str(caught.value)
        assert "start_map" in message  # the suggestion
        assert "Add it under" in message  # and how to fix it

    def test_with_no_config_at_all_it_still_explains(self):
        with pytest.raises(code.CodeError, match="defines: none"):
            code.combo_hooks_for(self._Mod(), self._spec(), cfg.Config())
