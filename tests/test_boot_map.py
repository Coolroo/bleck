"""Booting the game straight into a chosen map.

Without it an unattended boot reaches only `aa4_01` and `ls4_12`, since
controller input cannot be injected (D48).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.mods import code, registry, resolver
from bleck.mods import manifest as mod_manifest
from bleck.script import ScriptError, compile_source, emit


class TestBootMap:
    """Starting the game at a chosen map instead of the attract demo."""

    def _generated(self, source="", boot="he1_01"):
        text = emit.boot_source(boot)
        if source:
            text = source + "\n\n" + text
        plan = emit.Scaffolding(boot_script=emit.BOOT_SCRIPT)
        return compile_source(text, scaffolding=plan).generated.text

    def test_the_map_name_reaches_the_bytecode(self):
        out = self._generated()
        assert '"he1_01"' in out
        assert "evt_seq_mapchange" in out

    def test_it_goes_through_the_game_s_own_map_change(self):
        """Arrive the way a door does, not by poking `seqWork.p0` (deadlock, D51)."""
        out = self._generated()
        assert "seqWork.p0 =" not in out
        assert "evt_seq_mapchange" in out

    def test_it_fires_once_and_is_never_re_armed(self):
        """A re-armed boot map is a loop: leaving it would bounce straight back."""
        out = self._generated()
        block = out.split("static void bleck_boot_on_seq")[1].split("}\n")[0]
        assert "bleck_boot_pending = 0" in block
        assert "= 1" not in block

    def test_the_flag_starts_in_data_not_bss(self):
        # Nothing documents whether the loader zeroes this module's bss.
        assert "static u32 bleck_boot_pending = 1;" in self._generated()

    def test_it_waits_before_asking(self):
        """The first map has only just loaded and its sequence is unwinding."""
        out = self._generated()
        assert str(emit.BOOT_DELAY_FRAMES) in out

    def test_a_boot_map_needs_no_main_script(self):
        # A placement or texture mod has no script at all and still needs this.
        out = self._generated()
        assert "bleck_start_entry" not in out
        assert "bleck_boot_on_seq(seq)" in out

    def test_it_coexists_with_a_mod_s_own_script(self):
        out = self._generated(source="script main {\n wait(1)\n}")
        assert out.count("seq_data[i].main = bleck_hooks[i]") == 1
        assert "bleck_start_entry(seq)" in out
        assert "bleck_boot_on_seq(seq)" in out

    def test_the_boot_script_runs_after_everything_else_that_frame(self):
        # It tears the world down shortly after, so let the frame finish first.
        out = self._generated(source="script main {\n wait(1)\n}")
        body = out.split("static void bleck_after_seq")[1]
        assert body.index("bleck_start_entry") < body.index("bleck_boot_on_seq")

    def test_a_missing_boot_script_is_a_bleck_bug_not_a_user_error(self):
        with pytest.raises(ScriptError) as caught:
            compile_source(
                "script main {\n wait(1)\n}",
                scaffolding=emit.Scaffolding(boot_script="bleck_boot"),
            )
        assert "bug in bleck" in str(caught.value)

    def test_the_generated_source_says_not_to_edit_it(self):
        assert "Edit mod.json" in emit.boot_source("he1_01")


class TestBootMapManifest:
    """`code.boot` in a manifest, and `--map` overriding it at build time."""

    def test_it_parses(self):
        parsed = mod_manifest.Manifest.from_json(
            '{"name": "m", "code": {"boot": "he1_01"}}'
        )
        assert parsed.code.boot_map == "he1_01"
        assert parsed.code.has_boot_map

    def test_boot_alone_is_enough_to_have_code(self):
        """There is something to compile: bleck generates the script."""
        parsed = mod_manifest.Manifest.from_json(
            '{"name": "m", "code": {"boot": "he1_01"}}'
        )
        assert parsed.has_code
        assert not parsed.code.has_script

    def test_it_round_trips(self):
        original = mod_manifest.Manifest(
            name="m", code=mod_manifest.CodeSpec(script="a.evt", boot_map="mac_01")
        )
        assert mod_manifest.Manifest.from_json(original.to_json()).code == original.code

    def test_absent_when_not_set(self):
        spec = mod_manifest.CodeSpec(script="a.evt")
        assert "boot" not in spec.to_json()

    @pytest.mark.parametrize("bad", ["He1_01", "he1 01", "../etc/passwd", '", 0) --'])
    def test_anything_that_is_not_a_map_name_is_rejected(self, bad):
        # The name is interpolated into generated script source.
        raw = json.dumps({"name": "m", "code": {"boot": bad}})
        with pytest.raises(mod_manifest.ManifestError, match="not a map name"):
            mod_manifest.Manifest.from_json(raw)

    def test_it_must_be_a_string(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"code\.boot"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": {"boot": 42}}')


class TestBootMapOverride:
    """`--map` is a property of one build, not of the mod."""

    def _chain(self, has_code: bool):
        spec = mod_manifest.CodeSpec(script="s.evt") if has_code else None
        mod = registry.Mod(
            manifest=mod_manifest.Manifest(name="target", code=spec), root=Path("target")
        )
        return resolver.Chain(entries=[resolver.ChainEntry(mod, "")])

    @pytest.fixture(name="built")
    def _built(self, monkeypatch) -> list[str]:
        """Names of the mods that reached the compiler."""
        seen: list[str] = []

        def record(mod, _workroot, _override=None):
            seen.append(mod.name)

        monkeypatch.setattr(code, "build_mod", record)
        return seen

    def test_it_gives_code_to_a_mod_that_has_none(self, built):
        """A placement or texture mod declares no `code` block but still boots."""
        code.build_chain(
            self._chain(has_code=False),
            workroot=Path("unused"),
            override=code.CodeOverride(boot_map="he1_01"),
        )
        assert built == ["target"]

    def test_without_an_override_a_mod_with_no_code_builds_nothing(self, built):
        assert not code.build_chain(self._chain(has_code=False), Path("unused"))
        assert built == []

    def test_an_empty_override_changes_nothing(self, built):
        code.build_chain(self._chain(has_code=False), Path("unused"), code.CodeOverride())
        assert built == []
