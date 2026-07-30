"""Tags declared in source, folded into a mod's `code` block.

⚠️ The load-bearing tests are in `TestConflicts`. A declaration that parses, is
ignored, and still reports success is this repo's most-repeated bug (D126, four
times), so every silent-precedence path is asserted to raise instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.mods import registry
from bleck.mods.code import BLECK_INCLUDE
from bleck.mods.errors import ManifestError
from bleck.mods.manifest.code import tags
from bleck.script.syntax import lexer

HOOK_ONLY = "BLECK_HOOK(mapDataPtr, before)\nvoid watchMapData(void *work)\n{\n}\n"


def resolve(mod):
    """Force the merge, so `pytest.raises` has a call to wrap."""
    return mod.code


def a_mod(
    root: Path,
    name: str = "m",
    *,
    code: dict | None = None,
    sources: dict[str, str] | None = None,
    script: str | None = None,
):
    """A mod on disk with whatever sources and script the test needs."""
    where = root / name
    where.mkdir(parents=True, exist_ok=True)
    block: dict = {"target": "eu0", "module_id": 2}
    block.update(code or {})
    if sources is not None:
        block["sources"] = ["src"]
        (where / "src").mkdir(exist_ok=True)
        for filename, text in sources.items():
            (where / "src" / filename).write_text(text, encoding="utf-8")
    if script is not None:
        block["script"] = "scripts/main.evt"
        (where / "scripts").mkdir(exist_ok=True)
        (where / "scripts" / "main.evt").write_text(script, encoding="utf-8")
    (where / "mod.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "name": name,
                "version": "0.1.0",
                "description": name,
                "base": "eu0",
                "code": block,
            }
        ),
        encoding="utf-8",
    )
    return registry.load(root).require(name)


class TestHookTags:
    def test_a_tag_becomes_a_hook(self, tmp_path: Path):
        hooks = resolve(a_mod(tmp_path, sources={"a.c": HOOK_ONLY})).hooks
        assert len(hooks) == 1
        assert hooks[0].function == "mapDataPtr"
        assert hooks[0].call == "watchMapData"
        assert hooks[0].mode.value == "before"

    def test_the_call_comes_from_the_definition_not_the_tag(self, tmp_path: Path):
        """⚠️ The whole point: the C name is read, never repeated by hand."""
        source = (
            "BLECK_HOOK(GetBasicPlayer, after)\nstatic u32 *someLongName(void *p)\n{\n}\n"
        )
        code = resolve(a_mod(tmp_path, sources={"a.c": source}))
        assert code.hooks[0].call == "someLongName"

    def test_comments_between_tag_and_definition_are_skipped(self, tmp_path: Path):
        source = (
            "BLECK_HOOK(mapDataPtr, replace)\n"
            "/* why this exists */\n"
            "// and more\n"
            "void takeOver(void)\n{\n}\n"
        )
        code = resolve(a_mod(tmp_path, sources={"a.c": source}))
        assert code.hooks[0].call == "takeOver"

    def test_several_tags_in_one_file(self, tmp_path: Path):
        source = (
            "BLECK_HOOK(mapDataPtr, before)\nvoid one(void)\n{\n}\n\n"
            "BLECK_HOOK(GetBasicPlayer, after)\nvoid two(void)\n{\n}\n"
        )
        code = resolve(a_mod(tmp_path, sources={"a.c": source}))
        assert [hook.call for hook in code.hooks] == ["one", "two"]

    def test_a_tag_above_nothing_is_refused(self, tmp_path: Path):
        mod = a_mod(tmp_path, sources={"a.c": "BLECK_HOOK(mapDataPtr, before)\n"})
        with pytest.raises(ManifestError, match="not above a function definition"):
            resolve(mod)

    def test_a_bad_mode_is_refused(self, tmp_path: Path):
        source = "BLECK_HOOK(mapDataPtr, sideways)\nvoid f(void)\n{\n}\n"
        mod = a_mod(tmp_path, sources={"a.c": source})
        with pytest.raises(ManifestError):
            resolve(mod)

    def test_an_untagged_source_contributes_nothing(self, tmp_path: Path):
        code = resolve(a_mod(tmp_path, sources={"a.c": "void plain(void)\n{\n}\n"}))
        assert code.hooks == []


class TestScriptTags:
    def test_a_map_attribute_becomes_a_map_hook(self, tmp_path: Path):
        code = resolve(
            a_mod(tmp_path, script='#[map("he1_04")]\nscript onLoad { wait(1) }\n')
        )
        assert len(code.maps) == 1
        assert code.maps[0].map_name == "he1_04"
        assert code.maps[0].script == "onLoad"

    def test_a_combo_attribute_becomes_a_binding(self, tmp_path: Path):
        code = resolve(
            a_mod(tmp_path, script='#[combo("dev")]\nscript warp { wait(1) }\n')
        )
        assert code.combos[0].combo == "dev"
        assert code.combos[0].script == "warp"

    def test_two_attributes_on_one_script(self, tmp_path: Path):
        text = '#[map("he1_04")]\n#[combo("dev")]\nscript both { wait(1) }\n'
        code = resolve(a_mod(tmp_path, script=text))
        assert code.maps[0].script == "both"
        assert code.combos[0].script == "both"

    def test_an_attribute_still_compiles(self):
        """⚠️ The lexer must skip `#[...]`, or a tagged script cannot build."""
        tokens = lexer.tokenize('#[map("he1_04")]\nscript main { wait(1) }\n')
        assert not any(token.text.startswith("#") for token in tokens)

    def test_an_unknown_attribute_is_refused(self, tmp_path: Path):
        mod = a_mod(tmp_path, script='#[colour("red")]\nscript main { wait(1) }\n')
        with pytest.raises(ManifestError, match="unknown attribute"):
            resolve(mod)

    def test_a_trailing_attribute_is_refused(self, tmp_path: Path):
        mod = a_mod(tmp_path, script='script main { wait(1) }\n#[map("he1_04")]\n')
        with pytest.raises(ManifestError, match="no script after it"):
            resolve(mod)


#: One hook declared in mod.json, and the same one declared as a tag. Every
#: conflict test is built from this pair.
JSON_HOOK = {"hooks": [{"function": "mapDataPtr", "call": "fromJson", "mode": "before"}]}
TAG_HOOK = {"a.c": "BLECK_HOOK(mapDataPtr, after)\nvoid fromTag(void)\n{\n}\n"}


class TestConflicts:
    def test_a_tag_and_mod_json_hooking_one_function_is_refused(self, tmp_path: Path):
        mod = a_mod(tmp_path, code=JSON_HOOK, sources=TAG_HOOK)
        with pytest.raises(ManifestError, match="hook conflict on 'hook:mapDataPtr'"):
            resolve(mod)

    def test_the_conflict_names_both_sites(self, tmp_path: Path):
        """A conflict a reader cannot locate is barely better than a silent one."""
        mod = a_mod(tmp_path, code=JSON_HOOK, sources=TAG_HOOK)
        with pytest.raises(ManifestError) as caught:
            resolve(mod)
        message = str(caught.value)
        assert "src/a.c:1" in message
        assert "code.hooks[0]" in message

    def test_a_map_declared_twice_is_refused(self, tmp_path: Path):
        mod = a_mod(
            tmp_path,
            code={"maps": {"he1_04": "fromJson"}},
            script='#[map("he1_04")]\nscript fromTag { wait(1) }\n',
        )
        with pytest.raises(ManifestError, match="map hook conflict"):
            resolve(mod)

    def test_two_tags_claiming_one_function_are_refused(self, tmp_path: Path):
        source = (
            "BLECK_HOOK(mapDataPtr, before)\nvoid one(void)\n{\n}\n\n"
            "BLECK_HOOK(mapDataPtr, after)\nvoid two(void)\n{\n}\n"
        )
        mod = a_mod(tmp_path, sources={"a.c": source})
        with pytest.raises(ManifestError, match="two tags declare a hook"):
            resolve(mod)

    def test_one_mod_function_may_serve_two_targets(self, tmp_path: Path):
        """Only the *game* function can be claimed once; the mod's need not be."""
        source = (
            "BLECK_HOOK(mapDataPtr, before)\nvoid shared(void)\n{\n}\n\n"
            "BLECK_HOOK(GetBasicPlayer, before)\nvoid shared2(void)\n{\n}\n"
        )
        assert len(resolve(a_mod(tmp_path, sources={"a.c": source})).hooks) == 2

    def test_non_overlapping_declarations_both_survive(self, tmp_path: Path):
        mod = a_mod(
            tmp_path,
            code={
                "hooks": [
                    {"function": "GetBasicPlayer", "call": "fromJson", "mode": "before"}
                ]
            },
            sources=TAG_HOOK,
        )
        assert {hook.call for hook in resolve(mod).hooks} == {"fromJson", "fromTag"}


class TestScanningScope:
    def test_a_source_the_mod_does_not_build_is_not_scanned(self, tmp_path: Path):
        """⛔ A tag in an unbuilt file must not take effect invisibly."""
        mod = a_mod(tmp_path, sources={"a.c": "void plain(void)\n{\n}\n"})
        stray = mod.root / "not-built"
        stray.mkdir()
        (stray / "b.c").write_text(
            "BLECK_HOOK(mapDataPtr, before)\nvoid ghost(void)\n{\n}\n", encoding="utf-8"
        )
        assert resolve(mod).hooks == []

    def test_a_mod_with_no_code_block_has_no_code(self, tmp_path: Path):
        where = tmp_path / "n"
        where.mkdir()
        (where / "mod.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "name": "n",
                    "version": "0.1.0",
                    "description": "n",
                    "base": "eu0",
                }
            ),
            encoding="utf-8",
        )
        assert resolve(registry.load(tmp_path).require("n")) is None

    def test_the_header_ships_with_the_package(self):
        """`#include <bleck.h>` must resolve, or every tagged mod fails to build."""
        header = BLECK_INCLUDE / "bleck.h"
        assert header.is_file()
        assert "#define BLECK_HOOK" in header.read_text(encoding="utf-8")


class TestTagsUnit:
    def test_scanning_records_where_a_tag_was_written(self, tmp_path: Path):
        source = tmp_path / "a.c"
        source.write_text(
            "\n\nBLECK_HOOK(mapDataPtr, before)\nvoid f(void)\n{\n}\n", encoding="utf-8"
        )
        found = tags.Tags()
        tags.scan_source(source, tmp_path, found)
        assert found.where("hook:mapDataPtr") == "a.c:3"
