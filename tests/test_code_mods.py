"""Where a mod meets the compiler: `code` in `mod.json`, and the build.

These are integration-shaped: manifest parsing, the one-REL-per-disc limit,
native sources alongside a script, and where build intermediates land.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.backends import toolchain
from bleck.mods import code, registry, resolver
from bleck.mods import manifest as mod_manifest
from bleck.script import evt
from bleck.script.compiler import (
    Literal,
    compile_program,
)
from bleck.script.parser import parse


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


#: The smallest useful program, for tests that only care about the scaffolding
#: the emitter wraps around every script.
SIMPLE = "script main {\n wait(1)\n}"


def header(opcode: evt.Opcode, count: int) -> int:
    return evt.instruction_header(opcode, count)


class TestManifestCodeBlock:
    """The `code` block that turns a mod into a code mod."""

    def test_absent_by_default(self):
        parsed = mod_manifest.Manifest.from_json('{"name": "m"}')
        assert parsed.code is None
        assert not parsed.has_code

    def test_omitted_from_output_when_absent(self):
        # An always-present empty block invites people to fill it in.
        assert "code" not in mod_manifest.Manifest(name="m").to_json()

    def test_parses_and_defaults(self):
        parsed = mod_manifest.Manifest.from_json(
            '{"name": "m", "code": {"script": "s/main.evt"}}'
        )
        assert parsed.code is not None
        assert parsed.code.script == "s/main.evt"
        assert parsed.code.target == "eu0"
        assert parsed.code.module_id == 2

    def test_round_trips(self):
        original = mod_manifest.Manifest(
            name="m",
            code=mod_manifest.CodeSpec(script="a.evt", target="us0", module_id=3),
        )
        assert mod_manifest.Manifest.from_json(original.to_json()).code == original.code

    def test_script_is_required(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"needs a 'script'"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": {}}')

    @pytest.mark.parametrize("module_id", [0, 1])
    def test_reserved_module_ids_are_rejected(self, module_id):
        # 0 is the game binary and 1 is its own REL; either would collide with
        # something already linked when the mod loads.
        raw = json.dumps(
            {"name": "m", "code": {"script": "a.evt", "module_id": module_id}}
        )
        with pytest.raises(mod_manifest.ManifestError, match=r"must be 2 or more"):
            mod_manifest.Manifest.from_json(raw)

    def test_module_id_must_be_a_number(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"whole number"):
            mod_manifest.Manifest.from_json(
                '{"name": "m", "code": {"script": "a.evt", "module_id": "two"}}'
            )

    def test_code_must_be_an_object(self):
        with pytest.raises(mod_manifest.ManifestError, match=r"must be an object"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": "yes"}')


class TestSeveralCodeMods:
    """The loader opens exactly one `/mod/mod.rel` — and does not care how many
    mods went into it.

    Two code mods used to be refused outright. They are now merged at compile
    time, which satisfies the loader's limit without any runtime REL chaining
    (`docs/plan-merging.md`).
    """

    def _mod(self, name: str, has_code: bool):
        spec = mod_manifest.CodeSpec(script="s.evt") if has_code else None
        return registry.Mod(
            manifest=mod_manifest.Manifest(name=name, code=spec), root=Path(name)
        )

    def test_two_code_mods_take_the_merged_path(self, monkeypatch):
        """Both reach the compiler, rather than one being refused."""
        merged: list[list[str]] = []

        def record(mods, _target, _root, _override=None):
            merged.append([m.name for m in mods])

        monkeypatch.setattr(code, "build_merged", record)
        chain = resolver.Chain(
            entries=[
                resolver.ChainEntry(self._mod("alpha", True), ""),
                resolver.ChainEntry(self._mod("beta", True), "alpha"),
            ]
        )
        code.build_chain(chain, workroot=Path("unused"))
        assert merged == [["alpha", "beta"]]

    def test_one_code_mod_still_takes_the_single_path(self, monkeypatch):
        """A one-mod disc must keep emitting what it always has, so it must not
        wander into the merging code at all."""
        seen: list[str] = []

        def refuse(*_args, **_kwargs):
            pytest.fail("a single code mod must not take the merged path")

        def record(mod, _root, _override=None):
            seen.append(mod.name)

        monkeypatch.setattr(code, "build_merged", refuse)
        monkeypatch.setattr(code, "build_mod", record)
        chain = resolver.Chain(entries=[resolver.ChainEntry(self._mod("solo", True), "")])
        code.build_chain(chain, workroot=Path("unused"))
        assert seen == ["solo"]

    def test_one_code_mod_alongside_asset_mods_is_fine(self):
        chain = resolver.Chain(
            entries=[
                resolver.ChainEntry(self._mod("textures", False), ""),
                resolver.ChainEntry(self._mod("behaviour", True), "textures"),
            ]
        )
        assert [m.name for m in code.mods_with_code(chain)] == ["behaviour"]


class TestNativeSources:
    """`code.sources`: native C compiled into the same module as the script.

    This exists because a script cannot reach ordinary game functions. Every
    evt builtin takes `(EvtEntry *, bool)`, so calling something like
    `mapDataPtr` -- which is how a mod attaches behaviour to a specific map --
    is only possible from C.
    """

    def _mod(self, tmp_path: Path, **code) -> registry.Mod:
        root = tmp_path / "m"
        (root / "src").mkdir(parents=True)
        spec = mod_manifest.CodeSpec(**code)
        return registry.Mod(
            manifest=mod_manifest.Manifest(name="m", code=spec), root=root
        )

    def test_a_named_file_is_collected(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src/hooks.c"])
        (mod.root / "src" / "hooks.c").write_text("void mod_prolog(void) {}")
        found = code.collect_sources(mod, mod.manifest.code)
        assert [p.name for p in found] == ["hooks.c"]

    def test_a_directory_contributes_every_c_file(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        for name in ("b.c", "a.c"):
            (mod.root / "src" / name).write_text("")
        found = code.collect_sources(mod, mod.manifest.code)
        # Sorted, so a build does not depend on filesystem ordering.
        assert [p.name for p in found] == ["a.c", "b.c"]

    def test_headers_are_not_mistaken_for_sources(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.c").write_text("")
        (mod.root / "src" / "shared.h").write_text("")
        assert [p.name for p in code.collect_sources(mod, mod.manifest.code)] == ["a.c"]

    def test_an_empty_directory_is_an_error(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        with pytest.raises(code.CodeError, match=r"no .c files"):
            code.collect_sources(mod, mod.manifest.code)

    def test_a_missing_file_names_the_manifest_entry(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src/absent.c"])
        with pytest.raises(code.CodeError, match=r"code.sources"):
            code.collect_sources(mod, mod.manifest.code)


MAP_SOURCE = "script on_arrive {\n gw[31] = 1\n}"


class TestBannerFromManifest:
    """Turning a mod's manifest into the banner it draws."""

    def _mod(self, tmp_path: Path, body: dict) -> registry.Mod:
        root = tmp_path / body["name"]
        (root / "src").mkdir(parents=True)
        (root / "src" / "a.c").write_text("void nothing(void) {}\n")
        (root / "mod.json").write_text(json.dumps(body))
        return registry.load(tmp_path).require(body["name"])

    def test_every_code_mod_gets_one_without_asking(self):
        """The point of the feature: no mod declares anything."""
        spec = mod_manifest.CodeSpec(sources=["src"])
        assert spec.banner.enabled
        assert spec.banner.label("coin-tick") == "mod_loaded: coin-tick"

    def test_the_label_names_the_mod(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {"schema": 1, "name": "speedrun", "code": {"sources": ["src"]}},
        )
        banner = code.banner_for(mod)
        assert banner is not None
        assert banner.text == "mod_loaded: speedrun"

    def test_it_can_be_turned_off(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {
                "schema": 1,
                "name": "quiet",
                "code": {"sources": ["src"], "banner": False},
            },
        )
        assert code.banner_for(mod) is None

    def test_a_custom_label_wins(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {
                "schema": 1,
                "name": "quiet",
                "code": {"sources": ["src"], "banner": {"text": "build 42"}},
            },
        )
        assert code.banner_for(mod).text == "build 42"

    def test_sequence_names_become_indices(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {
                "schema": 1,
                "name": "probe",
                "code": {
                    "sources": ["src"],
                    "banner": {"sequences": ["title", "game"]},
                },
            },
        )
        assert code.banner_for(mod).sequences == (1, 2)

    def test_an_unknown_sequence_is_rejected_by_name(self, tmp_path):
        with pytest.raises(mod_manifest.ManifestError) as excinfo:
            self._mod(
                tmp_path,
                {
                    "schema": 1,
                    "name": "typo",
                    "code": {"sources": ["src"], "banner": {"sequences": ["titel"]}},
                },
            )
        # The message has to list the alternatives, or a typo is a guessing game.
        assert "titel" in str(excinfo.value)
        assert "title" in str(excinfo.value)

    def test_an_empty_sequence_list_is_rejected(self, tmp_path):
        with pytest.raises(mod_manifest.ManifestError) as excinfo:
            self._mod(
                tmp_path,
                {
                    "schema": 1,
                    "name": "empty",
                    "code": {"sources": ["src"], "banner": {"sequences": []}},
                },
            )
        assert "banner" in str(excinfo.value)

    def test_a_default_banner_is_not_written_back_to_json(self):
        """Most manifests should look exactly as they did before banners existed."""
        spec = mod_manifest.CodeSpec(sources=["src"])
        assert "banner" not in spec.to_json()

    def test_a_customised_banner_round_trips(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {
                "schema": 1,
                "name": "custom",
                "code": {
                    "sources": ["src"],
                    "banner": {"text": "hi", "sequences": ["game"]},
                },
            },
        )
        again = mod_manifest.Manifest.from_json(
            mod.manifest.to_json(), source="round trip"
        )
        assert again.code.banner == mod.manifest.code.banner

    def test_disabling_round_trips_as_false(self):
        spec = mod_manifest.CodeSpec(
            sources=["src"], banner=mod_manifest.BannerSpec(enabled=False)
        )
        assert spec.to_json()["banner"] is False


class TestCodeIntermediates:
    """Where compile intermediates land, and why it is not obvious."""

    def test_they_are_not_inside_the_staged_disc(self, tmp_path, monkeypatch):
        """`build_rel` promises to keep its intermediates. It has to be able to.

        `builder.stage` deletes the mod's build directory wholesale before
        mirroring the base into it, so intermediates written underneath it were
        gone by the time a build finished. The promise held for
        `bleck mod check`, which never stages, and broke for every real build --
        exactly backwards, since a full build is when a compile error is most
        likely and reading the generated `mod.c` is the only way to make sense
        of the compiler's line numbers.
        """
        root = tmp_path / "mods" / "demo"
        (root / "src").mkdir(parents=True)
        (root / "src" / "a.c").write_text("void nothing(void) {}\n")
        (root / "mod.json").write_text(
            json.dumps({"schema": 1, "name": "demo", "code": {"sources": ["src"]}})
        )
        mod = registry.load(tmp_path / "mods").require("demo")

        seen: dict[str, Path] = {}

        def fake_build_rel(request):
            seen["workdir"] = request.workdir
            return toolchain.BuildResult(
                rel=b"\0", toolchain="fake", module_id=2, symbols_file=Path()
            )

        monkeypatch.setattr(code.toolchain, "build_rel", fake_build_rel)

        workroot = tmp_path / "build"
        code.build_mod(mod, workroot)

        staged = workroot / mod.name
        assert staged not in seen["workdir"].parents
        assert seen["workdir"] == workroot / code.CODE_WORKDIR / mod.name
