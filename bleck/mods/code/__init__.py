"""Which code build happens: one mod, or several merged into one module.

The two strategies live here; everything they share lives in `parts`.

Compiling runs before the overlay is planned, because the plan comes from a
walk of `overlay/` and the module has to exist by then. The output goes to
`overlay/files/mod/mod.rel` and is carried by the ordinary overlay machinery
-- a code mod is still just a mod.

"""

from __future__ import annotations

from pathlib import Path

from bleck.backends import symbols as symbol_tables
from bleck.backends import toolchain
from bleck.common import config as project_config
from bleck.common import env
from bleck.mods import registry as mod_registry

# Re-exported: callers have always reached these through `mods.code`.
# pylint: disable=unused-import
from bleck.mods.code.parts import (  # noqa: F401
    CODE_WORKDIR,
    CodeBuild,
    CodeError,
    CodeOverride,
    Part,
    ScriptSource,
    _link,
    _prepare,
    _script_text,
    banner_for,
    collect_sources,
    combo_hooks_for,
    map_hooks_for,
)
from bleck.mods.manifest import REL_DISC_PATH, CodeSpec
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain
from bleck.script import ScriptError, compile_source, emit


def mods_with_code(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_code]


def build_chain(
    chain: Chain,
    workroot: Path | None = None,
    override: CodeOverride | None = None,
) -> list[CodeBuild]:
    """Compile the chain's code mods into one `mod.rel`.

    ⚠️ Several code mods used to be refused outright, because the Gecko loader
    opens exactly one `/mod/mod.rel`. That limit is real and unchanged — but it
    is about how many RELs the *loader* opens, not how many mods went into one.
    Merging at compile time satisfies it without any runtime REL chaining, which
    is the part nobody in this scene has solved (D39). See `plan-merging.md`.
    """
    coded = mods_with_code(chain)

    # An override can give code to a chain that has none. That is the point:
    # `--map` has to work on a pure asset or placement mod, which is exactly the
    # kind of mod someone wants to look at inside a particular level.
    if not coded and override is not None and not override.is_empty:
        coded = [chain.target]
    if not coded:
        return []

    root = workroot or mod_registry.build_root()
    if len(coded) == 1:
        return [build_mod(coded[0], root, override)]
    return [build_merged(coded, chain.target, root, override)]


def build_merged(
    mods: list[Mod], target: Mod, workroot: Path, override: CodeOverride | None = None
) -> CodeBuild:
    """Compile several code mods into one `mod.rel`.

    ⚠️ Every mod's `target` must agree. Addresses differ per game version, so a
    module holding one mod built against `eu0` and another against `us0` would
    link half its calls to the wrong places — and would do it silently.
    """
    parts = [_prepare(mod, override) for mod in mods]

    targets = {part.spec.target for part in parts}
    if len(targets) > 1:
        listed = ", ".join(f"{part.mod.name}={part.spec.target}" for part in parts)
        raise CodeError(
            f"these mods target different game versions ({listed}), so they "
            f"cannot share one module.\n"
            f"  Addresses differ per version; a merged build would bind half "
            f"its calls wrongly."
        )

    contributions = [
        emit.ModPart(
            name=part.mod.name,
            program=part.program,
            map_hooks=map_hooks_for(part.mod),
            combos=part.combos,
            boot_script=emit.BOOT_SCRIPT if part.boot_map else "",
        )
        for part in parts
        if part.program is not None
    ]
    if not contributions:
        raise CodeError(
            "merging needs at least one mod with a script; these ship only "
            "native sources, which cannot yet be combined."
        )

    # One banner for the disc, named for the mod that was asked for, so it is
    # obvious which build is in the drive rather than which dependency it pulled.
    banner = banner_for(target, target.manifest.code or parts[-1].spec)
    if banner is not None and len(mods) > 1:
        banner = emit.Banner(
            text=f"{banner.text} +{len(mods) - 1}", sequences=banner.sequences
        )

    try:
        generated = emit.generate_merged(
            contributions,
            origin=f"{len(contributions)} mods: "
            + ", ".join(part.name for part in contributions),
            banner=banner,
        )
    except ScriptError as exc:
        raise CodeError(f"merging {len(mods)} code mods:\n{exc}") from exc

    return _link(generated.text, parts, target, workroot)


def build_mod(
    mod: Mod, workroot: Path, override: CodeOverride | None = None
) -> CodeBuild:
    """Compile one mod's script and native sources into its `mod.rel`."""
    spec = mod.manifest.code
    boot_map = override.boot_map if override else ""
    if spec is None:
        if not boot_map:
            raise CodeError(f"{mod.name} declares no code to build")
        # Nothing declared, but a boot map was asked for. Defaults are enough:
        # they name eu0 and module 2, which is all the generated script needs.
        spec = CodeSpec()
    boot_map = boot_map or spec.boot_map

    # The same table the link will use, so "that will not link" is said now
    # rather than after a compile and a toolchain run (D61).
    table = symbol_tables.best_available(
        toolchain.symbols_file(spec.target), env.path(env.DECOMP_DIR), spec.target
    )
    sources = collect_sources(mod, spec)
    banner = banner_for(mod, spec)
    combos = combo_hooks_for(mod, spec, project_config.load())
    source = _script_text(mod, spec, boot_map)
    compiled = None

    if source.text:
        try:
            compiled = compile_source(
                source.text,
                origin=source.origin,
                scaffolding=emit.Scaffolding(
                    map_hooks=map_hooks_for(mod),
                    banner=banner,
                    combos=combos,
                    boot_script=emit.BOOT_SCRIPT if boot_map else "",
                ),
                symbol_table=table,
            )
        except ScriptError as exc:
            raise CodeError(f"{mod.name}:\n{exc.render(source.where)}") from exc
        generated_c = compiled.generated.text
    else:
        # Native-only: still needs the REL entry points and the `mod_prolog`
        # hand-off, just nothing to hand to the scheduler.
        generated_c = emit.generate_bare(
            origin=f"{mod.name} native sources", banner=banner
        ).text

    headers = env.path(env.HEADERS_DIR)
    result = toolchain.build_rel(
        toolchain.BuildRequest(
            source=generated_c,
            workdir=workroot / CODE_WORKDIR / mod.name,
            target=spec.target,
            module_id=spec.module_id,
            extra_sources=sources,
            include_dirs=[headers] if headers and headers.is_dir() else [],
        )
    )

    output = mod.overlay / REL_DISC_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.rel)

    return CodeBuild(
        mod=mod.name,
        script=source.path or mod.root,
        boot_map=boot_map,
        output=output,
        size=result.size,
        toolchain=result.toolchain,
        scripts=compiled.script_names if compiled else [],
        called_symbols=list(compiled.program.called_symbols) if compiled else [],
        sources=sources,
    )
