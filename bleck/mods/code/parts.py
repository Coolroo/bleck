"""The pieces a code build is made of, and the steps both paths share.

`__init__` decides which build happens — one mod, or several merged. This holds
what both need: the shared values, the resolution of a manifest's declarations
into what the emitter wants, and compiling and linking.

Four modules under it own the parts that stand alone, and none imports another
except downward:

| module | what it owns |
|---|---|
| `errors` | `CodeError`, so the four below can all raise it |
| `sources` | which files a mod compiles, and what they define |
| `patches` | `code.patches`, `tables.doors`, `code.replace` |
| `hooks` | `code.hooks` — name to address, and the guard word from the DOL |
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import symbols as symbol_tables
from bleck.backends import toolchain
from bleck.common import config as project_config
from bleck.common import env
from bleck.mods.code.errors import CodeError
from bleck.mods.code.hooks import ResolvedHooks, function_hooks_for
from bleck.mods.code.patches import patches_for, replacements_for
from bleck.mods.code.sources import (
    BLECK_INCLUDE,
    collect_sources,
    defines_mod_prolog,
)
from bleck.mods.manifest import REL_DISC_PATH, CodeSpec
from bleck.mods.registry import Mod
from bleck.script import ScriptError, compile_source, emit

CODE_WORKDIR = ".code"


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
        """⚠️ Gates whether a chain that declares no code is compiled as though
        the user had asked for it -- which must fail loudly when the toolchain
        is missing, unlike the banner-only build (D180)."""
        return not self.boot_map


@dataclass(frozen=True)
class CodeBuild:
    """One mod's compiled code, and what it took to produce."""

    mod: str
    script: Path
    output: Path
    size: int
    toolchain: str
    target: str
    """The game version this module binds against. Addresses differ per version."""

    scripts: list[str]
    called_symbols: list[str]
    sources: list[Path]
    """Native translation units compiled alongside the script."""

    boot_map: str = ""
    """The map this build starts the game at, if any."""

    warnings: list[str] = field(default_factory=list)
    """Things the build did that the user should know about, but not errors."""

    def describe(self) -> str:
        parts = []
        if self.scripts:
            parts.append(f"{self.script.name} [{', '.join(self.scripts)}]")
        if self.sources:
            names = ", ".join(path.name for path in self.sources)
            parts.append(f"{len(self.sources)} source(s) [{names}]")
        what = " + ".join(parts) or "the banner only"
        # Named in build output because a boot map changes where the disc goes.
        where = f", boots at {self.boot_map}" if self.boot_map else ""
        return (
            f"{self.mod}: compiled {what} -> "
            f"{self.size} byte module ({self.toolchain}){where}"
        )


@dataclass(frozen=True)
class CodeResult:
    """What compiling a chain produced, and anything it declined to produce.

    `notes` carries the scaffolding build that was skipped rather than failed.
    A disc with no code mods still compiles a module so it can draw its banner,
    and that module is the one thing here nobody asked for -- so when the
    toolchain to build it is missing, the build says so and carries on rather
    than failing a disc that would otherwise be fine.
    """

    builds: list[CodeBuild] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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


def mods_defining_mod_prolog(parts: list[Part]) -> list[str]:
    """Which mods in a merge supply their own `mod_prolog`, by name."""
    # pylint: disable=container-return
    return [
        part.mod.name
        for part in parts
        if any(defines_mod_prolog(source) for source in part.sources)
    ]


def map_hooks_for(mod: Mod) -> list[emit.MapHook]:
    """The map attachments this mod declares, as the emitter wants them."""
    # pylint: disable=container-return
    spec = mod.code
    if spec is None:
        return []
    return [
        emit.MapHook(map_name=hook.map_name, script=hook.script) for hook in spec.maps
    ]


def combo_hooks_for(
    mod: Mod, spec: CodeSpec, settings: project_config.Config
) -> list[emit.ComboHook]:
    """Resolve each `code.combos` binding against `bleck.yml`.

    Joined here so a mod never contains a button mask.
    """
    # pylint: disable=container-return
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


def banner_for(mod: Mod, spec: CodeSpec | None = None) -> emit.Banner | None:
    """The on-screen labels this disc should draw, if any.

    The text defaults to the mod's name and version. Pass `spec` when the
    build works from a synthesized `code` block rather than the manifest's own.
    """
    spec = spec if spec is not None else mod.code
    if spec is None or not spec.banner.enabled:
        return None
    return emit.Banner(
        text=spec.banner.label(mod.name, str(mod.manifest.version)),
        # Names to members. `_parse_banner` has already rejected anything
        # unknown, so this cannot be None -- but `.index()` would have raised
        # ValueError rather than said so.
        sequences=tuple(emit.Sequence[name.upper()] for name in spec.banner.sequences),
    )


def script_text(mod: Mod, spec: CodeSpec, boot_map: str) -> ScriptSource:
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
    replacements: list[emit.ScriptReplacement] = field(default_factory=list)
    function_hooks: ResolvedHooks = field(default_factory=ResolvedHooks)

    @property
    def scripts(self) -> list[str]:
        return [s.name for s in self.program.scripts] if self.program else []


def prepare(mod: Mod, override: CodeOverride | None) -> Part:
    """Everything up to but not including emitting C.

    One mod and several reach a compiled program by this same path.
    """
    spec = mod.code
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

    found = collect_sources(mod, spec)
    return Part(
        mod=mod,
        spec=spec,
        source=source,
        program=program,
        sources=found,
        boot_map=boot_map,
        combos=combo_hooks_for(mod, spec, project_config.load()),
        patches=patches_for(mod, spec, found),
        replacements=replacements_for(mod, spec),
        function_hooks=function_hooks_for(mod, spec, found, table),
    )


def link_module(
    generated_c: str, parts: list[Part], owner: Mod, workroot: Path
) -> CodeBuild:
    """Compile the generated C plus every part's native sources into one REL."""
    headers = env.path(env.HEADERS_DIR)
    spec = parts[-1].spec
    found: list[Path] = []
    for part in parts:
        found += part.sources

    result = toolchain.build_rel(
        toolchain.BuildRequest(
            source=generated_c,
            workdir=workroot / CODE_WORKDIR / owner.name,
            target=spec.target,
            module_id=spec.module_id,
            extra_sources=found,
            include_dirs=(
                ([headers] if headers and headers.is_dir() else []) + [BLECK_INCLUDE]
            ),
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
        target=parts[-1].spec.target,
        scripts=scripts,
        called_symbols=[],
        sources=found,
        boot_map=next((p.boot_map for p in parts if p.boot_map), ""),
        warnings=[note for part in parts for note in part.function_hooks.warnings],
    )
