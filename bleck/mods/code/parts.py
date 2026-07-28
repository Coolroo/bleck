"""The pieces a code build is made of, and the steps both paths share.

`__init__` decides which build happens — one mod, or several merged. This holds
what both need: the shared values, the resolution of a manifest's declarations
into what the emitter wants, and compiling and linking.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import languages, toolchain
from bleck.backends import symbols as symbol_tables
from bleck.common import config as project_config
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.mods.manifest import REL_DISC_PATH, CodeSpec
from bleck.mods.registry import Mod
from bleck.script import ScriptError, compile_source, emit

CODE_WORKDIR = ".code"


class CodeError(BleckError):
    """A mod's script could not be turned into a module."""


@dataclass(frozen=True)
class CodeOverride:
    """Build-time changes to what a mod compiles, from the command line.

    Properties of *this build*, not of the mod; anything worth keeping belongs
    in the manifest.
    """

    boot_map: str = ""
    """Overrides `code.boot`, and supplies one to a mod that has no code."""

    @property
    def is_empty(self) -> bool:
        return not self.boot_map


@dataclass(frozen=True)
class CodeBuild:
    """One mod's compiled code, and what it took to produce."""

    mod: str
    script: Path
    output: Path
    size: int
    toolchain: str
    scripts: list[str]
    called_symbols: list[str]
    sources: list[Path]
    """Native translation units compiled alongside the script."""

    boot_map: str = ""
    """The map this build starts the game at, if any."""

    def describe(self) -> str:
        parts = []
        if self.scripts:
            parts.append(f"{self.script.name} [{', '.join(self.scripts)}]")
        if self.sources:
            names = ", ".join(path.name for path in self.sources)
            parts.append(f"{len(self.sources)} source(s) [{names}]")
        what = " + ".join(parts) or "nothing"
        # Named in build output because a boot map changes where the disc goes.
        where = f", boots at {self.boot_map}" if self.boot_map else ""
        return (
            f"{self.mod}: compiled {what} -> "
            f"{self.size} byte module ({self.toolchain}){where}"
        )


@dataclass(frozen=True)
class ScriptSource:
    """Script text on its way to the compiler, and where it came from.

    `path` is None when `bleck` generated the text itself, so an error can
    point at a real file only when there is one.
    """

    text: str
    path: Path | None
    origin: str

    @property
    def where(self) -> str:
        """What to name in an error message."""
        return str(self.path) if self.path is not None else self.origin


#: What `code.sources` accepts, as a phrase for error messages.
_SUFFIX_LIST = ", ".join(languages.SOURCE_SUFFIXES)


def collect_sources(mod: Mod, spec) -> list[Path]:
    """Resolve `code.sources` to actual C and C++ files.

    A directory entry contributes every source beneath it, sorted, so a build
    does not depend on filesystem ordering.
    """
    found: list[Path] = []
    for entry in spec.sources:
        path = mod.root / entry
        if path.is_dir():
            # A set first: Windows globs case-insensitively, so `*.c` and `*.cc`
            # can both match the same file.
            seen = {
                match
                for suffix in languages.SOURCE_SUFFIXES
                for match in path.rglob(f"*{suffix}")
            }
            if not seen:
                raise CodeError(f"{mod.name}: no {_SUFFIX_LIST} files under {path}")
            found += sorted(seen)
        elif path.exists():
            found.append(path)
        else:
            raise CodeError(
                f"{mod.name}: no source at {path}\n"
                f"  mod.json lists {entry!r} in 'code.sources'"
            )
    _check_cxx_prolog(mod, found)
    return found


def needs_ctor_walk(sources: list[Path]) -> bool:
    """Whether these sources oblige `_prolog` to walk `.ctors`."""
    return any(language.needs_ctor_walk for language in languages.used_by(sources))


#: Comments, stripped first: mods quote "define `mod_prolog`" from the docs in
#: a comment, and matching that prose reports a false collision.
_C_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

#: A *definition*, not a declaration: the body brace is what makes it one.
#: `extern void mod_prolog(void);` collides with nothing.
_MOD_PROLOG_DEFINITION = re.compile(r"\bvoid\s+mod_prolog\s*\([^)]*\)\s*\{")


def defines_mod_prolog(source: Path) -> bool:
    """Whether a source file supplies its own `mod_prolog`.

    `bleck` emits a *weak* one (see `runtime_c.MOD_HOOK`), so one mod may
    override it; two is a duplicate symbol.
    """
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(_MOD_PROLOG_DEFINITION.search(_C_COMMENT.sub(" ", text)))


def _check_cxx_prolog(mod: Mod, sources: list[Path]) -> None:
    """A C++ `mod_prolog` must have C linkage, or it is never called.

    `bleck`'s weak definition has C linkage, so a mangled `mod_prolog` does not
    override it: the module links, loads, and silently runs nothing.
    """
    for source in sources:
        if languages.for_source(source) is not languages.CXX:
            continue
        if not defines_mod_prolog(source):
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        if 'extern "C"' in _C_COMMENT.sub(" ", text):
            continue
        raise CodeError(
            f"{mod.name}: {source} defines `mod_prolog` with C++ linkage, so "
            f"its name is mangled and bleck's own definition wins.\n"
            f'  Write `extern "C" void mod_prolog(void)` instead -- otherwise '
            f"the module loads and does nothing."
        )


def mods_defining_mod_prolog(parts: list[Part]) -> list[str]:
    """Which mods in a merge supply their own `mod_prolog`, by name."""
    return [
        part.mod.name
        for part in parts
        if any(defines_mod_prolog(source) for source in part.sources)
    ]


def map_hooks_for(mod: Mod) -> list[emit.MapHook]:
    """The map attachments this mod declares, as the emitter wants them."""
    spec = mod.manifest.code
    if spec is None:
        return []
    return [
        emit.MapHook(map_name=hook.map_name, script=hook.script) for hook in spec.maps
    ]


def combo_hooks_for(mod: Mod, spec, settings) -> list[emit.ComboHook]:
    """Resolve each `code.combos` binding against `bleck.yml`.

    Joined here so a mod never contains a button mask.
    """
    hooks: list[emit.ComboHook] = []
    for binding in spec.combos:
        found = settings.combo(binding.combo)
        if found is None:
            listed = ", ".join(settings.combo_names) or "none"
            close = difflib.get_close_matches(
                binding.combo, settings.combo_names, n=1, cutoff=0.6
            )
            hint = f"\n  Did you mean {close[0]!r}?" if close else ""
            raise CodeError(
                f"{mod.name}: mod.json uses combo {binding.combo!r}, but "
                f"{settings.where} defines no such combination "
                f"(it defines: {listed}).{hint}\n"
                f"  Add it under `combos:` there, e.g. "
                f"`{binding.combo}: [1, 2]`."
            )
        hooks.append(
            emit.ComboHook(name=found.name, mask=found.mask, script=binding.script)
        )
    return hooks


#: A function *definition*: same shape as `_MOD_PROLOG_DEFINITION`, but for any
#: name, so a typo can be matched against what the sources actually define.
#: One level of nesting, so a function-pointer parameter still matches. A
#: definition produced by a macro will not -- that costs a build error naming
#: what was found, not a silent miss.
_ANY_DEFINITION = re.compile(r"\b([A-Za-z_]\w*)\s*\((?:[^()]|\([^()]*\))*\)\s*\{")

#: `if (x) {` matches the pattern above and is not a function.
_NOT_A_FUNCTION = frozenset({"if", "for", "while", "switch", "catch", "return"})


def _defined_functions(sources: list[Path]) -> list[str]:
    """Every function these sources define, in order, comments stripped."""
    names: list[str] = []
    for source in sources:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in _ANY_DEFINITION.finditer(_C_COMMENT.sub(" ", text)):
            if match[1] not in names and match[1] not in _NOT_A_FUNCTION:
                names.append(match[1])
    return names


def patches_for(mod: Mod, spec, sources: list[Path]) -> list[emit.ScriptPatch]:
    """Resolve `code.patches` for the emitter, checking each `call` exists.

    Without this the typo reaches `elf2rel`, which reports it as a missing
    *game* symbol -- the mod's own function looks like an address it should
    have found in the symbol list.
    """
    if not spec.patches:
        return []
    defined = _defined_functions(sources)
    for index, patch in enumerate(spec.patches):
        if patch.call in defined:
            continue
        listed = ", ".join(defined) or "none"
        close = difflib.get_close_matches(patch.call, defined, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {close[0]!r}?" if close else ""
        raise CodeError(
            f"{mod.name}: 'code.patches[{index}].call' names {patch.call!r}, but "
            f"this mod's sources define no such function "
            f"(they define: {listed}).{hint}\n"
            f"  A patched instruction calls a function with evt's user-func "
            f"signature -- `s32 f(EvtEntry *entry, bool firstCall)` -- which "
            f"must return 2 for the script to advance."
        )
    return [
        emit.ScriptPatch(
            kind=patch.kind,
            target=patch.target,
            at=patch.at,
            expect=patch.expect_word,
            call=patch.call,
            item_id=patch.item_id,
        )
        for patch in spec.patches
    ]


def banner_for(mod: Mod, spec=None) -> emit.Banner | None:
    """The on-screen label this mod should draw, if any.

    The text defaults to the mod's own name. Pass `spec` when the build works
    from a synthesized `code` block rather than the manifest's own.
    """
    spec = spec if spec is not None else mod.manifest.code
    if spec is None or not spec.banner.enabled:
        return None
    return emit.Banner(
        text=spec.banner.label(mod.name),
        sequences=tuple(
            emit.SEQUENCE_NAMES.index(name) for name in spec.banner.sequences
        ),
    )


def script_text(mod: Mod, spec, boot_map: str) -> ScriptSource:
    """The script source to compile: the mod's own, the boot script, or both.

    A boot map is desugared into script source and *appended* rather than made
    a second translation unit, keeping one `evtEntry` and string table.
    """
    own = ""
    path = mod.root / spec.script if spec.has_script else None
    if path is not None:
        if not path.exists():
            raise CodeError(
                f"{mod.name}: no script at {path}\n"
                f"  mod.json points 'code.script' at {spec.script!r}"
            )
        own = path.read_text(encoding="utf-8")

    if not boot_map:
        return ScriptSource(text=own, path=path, origin=spec.script)

    generated = emit.boot_source(boot_map)
    if not own:
        return ScriptSource(text=generated, path=None, origin=f"code.boot -> {boot_map}")
    return ScriptSource(
        text=own.rstrip("\n") + "\n\n" + generated,
        path=path,
        origin=f"{spec.script} + code.boot -> {boot_map}",
    )


@dataclass(frozen=True)
class Part:
    """One mod compiled but not yet emitted."""

    mod: Mod
    spec: CodeSpec
    source: ScriptSource
    program: object | None
    """The `CompiledProgram`, or None for a mod that ships only native C."""

    sources: list[Path]
    boot_map: str
    combos: list[emit.ComboHook]
    patches: list[emit.ScriptPatch] = field(default_factory=list)

    @property
    def scripts(self) -> list[str]:
        return [s.name for s in self.program.scripts] if self.program else []


def prepare(mod: Mod, override: CodeOverride | None) -> Part:
    """Everything up to but not including emitting C.

    One mod and several reach a compiled program by this same path.
    """
    spec = mod.manifest.code
    boot_map = override.boot_map if override else ""
    if spec is None:
        if not boot_map:
            raise CodeError(f"{mod.name} declares no code to build")
        # Nothing declared, but a boot map was asked for; defaults (eu0,
        # module 2) are all the generated code needs.
        spec = CodeSpec()
    boot_map = boot_map or spec.boot_map

    # The same table the link will use, so "that will not link" is said before
    # the toolchain runs (D61).
    table = symbol_tables.best_available(
        toolchain.symbols_file(spec.target), env.path(env.DECOMP_DIR), spec.target
    )
    source = script_text(mod, spec, boot_map)
    program = None
    if source.text:
        try:
            # No scaffolding: this pass only needs the compiled program; what
            # the module does with it is decided at emission.
            program = compile_source(
                source.text,
                origin=source.origin,
                scaffolding=emit.Scaffolding(require_entry=False),
                symbol_table=table,
            ).program
        except ScriptError as exc:
            raise CodeError(f"{mod.name}:\n{exc.render(source.where)}") from exc

    sources = collect_sources(mod, spec)
    return Part(
        mod=mod,
        spec=spec,
        source=source,
        program=program,
        sources=sources,
        boot_map=boot_map,
        combos=combo_hooks_for(mod, spec, project_config.load()),
        patches=patches_for(mod, spec, sources),
    )


def link_module(
    generated_c: str, parts: list[Part], owner: Mod, workroot: Path
) -> CodeBuild:
    """Compile the generated C plus every part's native sources into one REL."""
    headers = env.path(env.HEADERS_DIR)
    spec = parts[-1].spec
    sources: list[Path] = []
    for part in parts:
        sources += part.sources

    result = toolchain.build_rel(
        toolchain.BuildRequest(
            source=generated_c,
            workdir=workroot / CODE_WORKDIR / owner.name,
            target=spec.target,
            module_id=spec.module_id,
            extra_sources=sources,
            include_dirs=[headers] if headers and headers.is_dir() else [],
        )
    )

    output = owner.overlay / REL_DISC_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.rel)

    scripts: list[str] = []
    for part in parts:
        scripts += part.scripts
    return CodeBuild(
        mod=", ".join(part.mod.name for part in parts),
        script=parts[-1].source.path or owner.root,
        output=output,
        size=result.size,
        toolchain=result.toolchain,
        scripts=scripts,
        called_symbols=[],
        sources=sources,
        boot_map=next((p.boot_map for p in parts if p.boot_map), ""),
    )
