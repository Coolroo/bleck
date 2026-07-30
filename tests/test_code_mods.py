"""Where a mod meets the compiler: `code` in `mod.json`, and the build.

These are integration-shaped: manifest parsing, the one-REL-per-disc limit,
native sources alongside a script, and where build intermediates land.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bleck.backends import languages, toolchain
from bleck.mods import code, registry, resolver
from bleck.mods import manifest as mod_manifest
from bleck.script import evt
from bleck.script.compiler import (
    Literal,
    compile_program,
)
from bleck.script.syntax.parser import parse


def _has_symbols() -> bool:
    try:
        toolchain.symbols_file("eu0")
    except toolchain.ToolchainError:
        return False
    return True


#: `code.prepare` eagerly resolves the third-party, deliberately unvendored
#: symbol list. Same contract as `game_data`: a fresh clone runs green.
needs_symbols = pytest.mark.skipif(
    not _has_symbols(),
    reason="no spm-headers symbol list; set BLECK_SYMBOLS_DIR",
)


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
        # 0 is the game binary and 1 its own REL; either would collide.
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
    """The loader opens exactly one `/mod/mod.rel`, so several code mods are
    merged at compile time (`docs/plan-merging.md`)."""

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
        """A one-mod disc must emit what it always has, never touching merging."""
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

    def test_the_disc_is_named_after_the_top_of_the_tree(self):
        """⚠️ The banner names the mod that was asked for, and only that one.

        A chain is one mod plus what it needs, so a disc built from `x` is
        `x-<version>` whether `x` pulled in three dependencies or none --
        those are `x`'s implementation, not co-authors of the disc (D180).
        """
        target = self._mod("x", True)
        chain = resolver.Chain(
            entries=[
                resolver.ChainEntry(self._mod("a", True), "x"),
                resolver.ChainEntry(self._mod("b", False), "x"),
                resolver.ChainEntry(target, ""),
            ]
        )
        banner = code.banner_for(chain.target, chain.target.code)
        assert banner is not None
        assert banner.text == "x-0.0.0"


class TestNativeSources:
    """`code.sources`: native C compiled into the same module as the script.

    Every evt builtin takes `(EvtEntry *, bool)`, so ordinary game functions
    are reachable only from C.
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

    def test_an_empty_directory_lists_every_accepted_suffix(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        with pytest.raises(code.CodeError) as caught:
            code.collect_sources(mod, mod.manifest.code)
        for suffix in languages.SOURCE_SUFFIXES:
            assert suffix in str(caught.value)

    def test_a_missing_file_names_the_manifest_entry(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src/absent.c"])
        with pytest.raises(code.CodeError, match=r"code.sources"):
            code.collect_sources(mod, mod.manifest.code)


class TestCxxSources:
    """C++ alongside C: collection, which compiler runs, and the ctor walk."""

    def _mod(self, tmp_path: Path, **code) -> registry.Mod:
        root = tmp_path / "m"
        (root / "src").mkdir(parents=True)
        spec = mod_manifest.CodeSpec(**code)
        return registry.Mod(
            manifest=mod_manifest.Manifest(name="m", code=spec), root=root
        )

    @pytest.mark.parametrize("suffix", sorted(languages.CXX.suffixes))
    def test_every_cxx_suffix_is_collected(self, tmp_path: Path, suffix: str):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / f"a{suffix}").write_text("")
        found = code.collect_sources(mod, mod.manifest.code)
        assert [p.name for p in found] == [f"a{suffix}"]

    def test_c_and_cxx_mix_in_one_mod(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        for name in ("z.c", "a.cpp", "m.cc"):
            (mod.root / "src" / name).write_text("")
        found = code.collect_sources(mod, mod.manifest.code)
        # Sorted across suffixes, not grouped by them, so the order is stable.
        assert [p.name for p in found] == ["a.cpp", "m.cc", "z.c"]

    def test_collection_order_does_not_depend_on_creation_order(self, tmp_path: Path):
        first = self._mod(tmp_path / "one", sources=["src"])
        second = self._mod(tmp_path / "two", sources=["src"])
        for name in ("b.cxx", "a.c", "c.cpp"):
            (first.root / "src" / name).write_text("")
        for name in ("c.cpp", "b.cxx", "a.c"):
            (second.root / "src" / name).write_text("")
        assert [p.name for p in code.collect_sources(first, first.manifest.code)] == [
            p.name for p in code.collect_sources(second, second.manifest.code)
        ]

    def test_headers_are_not_mistaken_for_sources(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.cpp").write_text("")
        (mod.root / "src" / "shared.hpp").write_text("")
        found = code.collect_sources(mod, mod.manifest.code)
        assert [p.name for p in found] == ["a.cpp"]

    def test_c_only_needs_no_ctor_walk(self):
        """The generated C must be unchanged for a mod that ships no C++."""
        assert not code.needs_ctor_walk([Path("a.c"), Path("b.c")])

    def test_one_cxx_source_arms_the_ctor_walk(self):
        assert code.needs_ctor_walk([Path("a.c"), Path("b.cpp")])

    def test_a_cxx_mod_prolog_must_have_c_linkage(self, tmp_path: Path):
        """A mangled `mod_prolog` links, loads and silently runs nothing."""
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.cpp").write_text("void mod_prolog(void)\n{\n}\n")
        with pytest.raises(code.CodeError) as caught:
            code.collect_sources(mod, mod.manifest.code)
        assert 'extern "C"' in str(caught.value)

    def test_an_extern_c_prolog_is_accepted(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.cpp").write_text(
            'extern "C" void mod_prolog(void)\n{\n}\n'
        )
        assert code.mods_defining_mod_prolog(
            [
                code.Part(
                    mod=mod,
                    spec=mod.manifest.code,
                    source=code.ScriptSource("", None, ""),
                    program=None,
                    sources=code.collect_sources(mod, mod.manifest.code),
                    boot_map="",
                    combos=[],
                )
            ]
        ) == ["m"]

    def test_a_c_prolog_is_still_accepted_without_extern_c(self, tmp_path: Path):
        mod = self._mod(tmp_path, sources=["src"])
        (mod.root / "src" / "a.c").write_text("void mod_prolog(void)\n{\n}\n")
        assert code.collect_sources(mod, mod.manifest.code)


class TestLanguageDrivers:
    """Which compiler runs, derived from the one that was found."""

    def _chain(self, compiler: str) -> toolchain.Toolchain:
        return toolchain.Toolchain(compiler, "devkitPPC", ["-mgcn"])

    def test_cxx_is_derived_from_the_located_gcc(self):
        found = self._chain("/opt/devkitpro/devkitPPC/bin/powerpc-eabi-gcc")
        assert found.derive_driver(languages.CXX).endswith("powerpc-eabi-g++")

    def test_the_exe_suffix_survives_the_swap(self):
        found = self._chain(r"C:\devkitPro\devkitPPC\bin\powerpc-eabi-gcc.exe")
        assert found.derive_driver(languages.CXX).endswith("powerpc-eabi-g++.exe")

    def test_c_uses_the_compiler_exactly_as_located(self):
        """So a compiler whose name holds no `gcc` still builds C."""
        assert (
            self._chain("/usr/bin/clang").derive_driver(languages.C) == "/usr/bin/clang"
        )

    def test_a_missing_cxx_compiler_names_the_path_and_the_fix(self):
        found = self._chain("/nowhere/powerpc-eabi-gcc")
        with pytest.raises(toolchain.ToolchainError) as caught:
            found.driver(languages.CXX)
        message = str(caught.value)
        assert "powerpc-eabi-g++" in message
        assert "bleck toolchain install" in message

    def test_an_underivable_name_says_so(self):
        with pytest.raises(toolchain.ToolchainError) as caught:
            self._chain("/usr/bin/clang").driver(languages.CXX)
        assert "no 'gcc' in clang" in str(caught.value)

    def test_cxx_flags_add_to_the_c_ones_rather_than_replacing_them(self):
        found = self._chain("powerpc-eabi-gcc")
        c_flags = found.compile_flags(languages.C)
        cxx_flags = found.compile_flags(languages.CXX)
        assert cxx_flags[: len(c_flags)] == c_flags
        # No libstdc++, no unwinder, no type info in a REL.
        assert cxx_flags[len(c_flags) :] == [
            "-fno-exceptions",
            "-fno-rtti",
            "-std=gnu++17",
        ]

    def test_the_default_language_keeps_the_old_c_signature(self):
        found = self._chain("powerpc-eabi-gcc")
        assert found.compile_flags() == found.compile_flags(languages.C)

    def test_cxx_leads_the_link_when_both_are_present(self):
        """g++ links a module holding C++ objects; gcc still links a C-only one."""
        both = languages.used_by([Path("a.c"), Path("b.cpp")])
        assert max(both, key=lambda lang: lang.link_priority) is languages.CXX
        only_c = languages.used_by([Path("a.c")])
        assert max(only_c, key=lambda lang: lang.link_priority) is languages.C

    def test_an_unknown_suffix_falls_back_to_c(self):
        """A hand-written .S must keep reaching the driver that handled it."""
        assert languages.for_source(Path("boot.S")) is languages.C

    def test_suffixes_are_claimed_by_exactly_one_language(self):
        claimed = [s for lang in languages.ALL for s in lang.suffixes]
        assert len(claimed) == len(set(claimed))
        assert claimed == [s.lower() for s in claimed]


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
        assert spec.banner.label("coin-tick", "1.2.3") == "coin-tick-1.2.3"

    def test_a_mod_with_no_code_at_all_still_gets_one(self):
        """⚠️ D176. A texture disc is the one nobody can identify by looking."""
        assert mod_manifest.CodeSpec().banner.enabled
        assert not mod_manifest.CodeSpec().is_inert

    def test_suppressing_it_needs_no_other_code(self):
        """⛔ Was refused as 'nothing to compile' until the banner became the
        thing being compiled -- leaving an asset-only mod no way to opt out."""
        raw = json.dumps({"name": "m", "code": {"banner": False}})
        spec = mod_manifest.Manifest.from_json(raw).code
        assert spec is not None
        assert not spec.banner.enabled

    def test_a_code_block_with_nothing_in_it_is_still_refused(self):
        """The escape hatch must not become a way to declare an empty block."""
        with pytest.raises(mod_manifest.ManifestError, match="nothing to compile"):
            mod_manifest.Manifest.from_json('{"name": "m", "code": {}}')

    def test_banner_off_and_nothing_else_builds_no_module(self):
        """⛔ An empty module has no sections and `elf2rel` dies on it."""
        raw = json.dumps({"name": "m", "code": {"banner": False}})
        assert mod_manifest.Manifest.from_json(raw).code.is_inert

    def test_banner_off_with_real_code_is_not_inert(self):
        spec = mod_manifest.CodeSpec(
            sources=["src"], banner=mod_manifest.BannerSpec(enabled=False)
        )
        assert not spec.is_inert

    def test_the_label_names_the_mod(self, tmp_path):
        mod = self._mod(
            tmp_path,
            {"schema": 1, "name": "speedrun", "code": {"sources": ["src"]}},
        )
        banner = code.banner_for(mod)
        assert banner is not None
        assert banner.text == "speedrun-0.0.0"

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
        # The message must list the alternatives.
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

    @needs_symbols
    def test_they_are_not_inside_the_staged_disc(self, tmp_path, monkeypatch):
        """Intermediates must survive staging, which wipes the build directory."""
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


class TestMergedModProlog:
    """Exactly one mod in a merge may define `mod_prolog`."""

    def _mod(self, tmp_path: Path, name: str, defines: bool) -> registry.Mod:
        root = tmp_path / name
        (root / "src").mkdir(parents=True)
        body = "void mod_prolog(void)\n{\n}\n" if defines else "void helper(void)\n{\n}\n"
        (root / "src" / "main.c").write_text(body, encoding="utf-8")
        spec = mod_manifest.CodeSpec(sources=["src"])
        return registry.Mod(
            manifest=mod_manifest.Manifest(name=name, code=spec), root=root
        )

    @needs_symbols
    def test_two_definitions_are_refused_naming_both(self, tmp_path: Path):
        mods = [
            self._mod(tmp_path, "alpha", True),
            self._mod(tmp_path, "beta", True),
        ]
        with pytest.raises(code.CodeError) as caught:
            code.build_merged(mods, mods[-1], tmp_path / "work")
        message = str(caught.value)
        assert "alpha" in message and "beta" in message
        # And says what to do instead.
        assert "sequence hook" in message

    @needs_symbols
    def test_one_definition_alongside_another_mod_is_fine(self, tmp_path: Path):
        """bleck's own definition is weak, so a single override wins."""
        mods = [
            self._mod(tmp_path, "alpha", True),
            self._mod(tmp_path, "beta", False),
        ]
        prepared = [code.prepare(mod, None) for mod in mods]
        assert code.mods_defining_mod_prolog(prepared) == ["alpha"]
