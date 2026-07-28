"""Which code build happens: one mod, or several merged into one module.

The two strategies live here; everything they share lives in `parts`.

⚠️ Compiling runs before the overlay is planned: the plan comes from walking
`overlay/`, and the output at `overlay/files/mod/mod.rel` has to exist by then.
"""

from __future__ import annotations

from pathlib import Path

from bleck.backends import symbols as symbol_tables
from bleck.backends import toolchain
from bleck.common import config as project_config
from bleck.common import env
from bleck.mods import registry as mod_registry

# Re-exported: callers reach these through `mods.code`.
# pylint: disable=unused-import
from bleck.mods.code.parts import (  # noqa: F401
    CODE_WORKDIR,
    CodeBuild,
    CodeError,
    CodeOverride,
    Part,
    ScriptSource,
    banner_for,
    collect_sources,
    combo_hooks_for,
    link_module,
    map_hooks_for,
    mods_defining_mod_prolog,
    needs_ctor_walk,
    patches_for,
    prepare,
    script_text,
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

    The Gecko loader opens exactly one `/mod/mod.rel`, so mods are merged at
    compile time rather than chained at runtime (D39, `docs/plan-merging.md`).
    """
    coded = mods_with_code(chain)

    # An override can give code to a chain that has none, so `--map` works on a
    # pure asset or placement mod.
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

    ⚠️ Every mod's `target` must agree: addresses differ per game version, so a
    mixed module would silently bind half its calls wrongly.
    """
    parts = [prepare(mod, override) for mod in mods]

    targets = {part.spec.target for part in parts}
    if len(targets) > 1:
        listed = ", ".join(f"{part.mod.name}={part.spec.target}" for part in parts)
        raise CodeError(
            f"these mods target different game versions ({listed}), so they "
            f"cannot share one module.\n"
            f"  Addresses differ per version; a merged build would bind half "
            f"its calls wrongly."
        )

    # `bleck` emits a weak `mod_prolog`, so one mod may override it; two is a
    # duplicate symbol the linker reports against unreadable object names.
    overriding = mods_defining_mod_prolog(parts)
    if len(overriding) > 1:
        listed = ", ".join(overriding)
        raise CodeError(
            f"{len(overriding)} mods define `mod_prolog` ({listed}), and only "
            f"one can.\n"
            f"  It is the hand-off `bleck` calls when the module loads, so a "
            f"merged disc has exactly one.\n"
            f"  Move the extra work into a sequence hook, or combine those mods."
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

    # One banner for the disc, named for the mod that was asked for rather than
    # a dependency it pulled in.
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
            run_cxx_ctors=any(needs_ctor_walk(part.sources) for part in parts),
            # Every mod's, not just the ones with a script: patches name C
            # functions, so a native-only mod contributes them too.
            patches=[patch for part in parts for patch in part.patches],
        )
    except ScriptError as exc:
        raise CodeError(f"merging {len(mods)} code mods:\n{exc}") from exc

    return link_module(generated.text, parts, target, workroot)


def build_mod(
    mod: Mod, workroot: Path, override: CodeOverride | None = None
) -> CodeBuild:
    """Compile one mod's script and native sources into its `mod.rel`."""
    spec = mod.manifest.code
    boot_map = override.boot_map if override else ""
    if spec is None:
        if not boot_map:
            raise CodeError(f"{mod.name} declares no code to build")
        # Nothing declared, but a boot map was asked for; defaults (eu0,
        # module 2) are all the generated script needs.
        spec = CodeSpec()
    boot_map = boot_map or spec.boot_map

    # The same table the link will use, so "that will not link" is said before
    # the toolchain runs (D61).
    table = symbol_tables.best_available(
        toolchain.symbols_file(spec.target), env.path(env.DECOMP_DIR), spec.target
    )
    sources = collect_sources(mod, spec)
    banner = banner_for(mod, spec)
    combos = combo_hooks_for(mod, spec, project_config.load())
    patches = patches_for(mod, spec, sources)
    source = script_text(mod, spec, boot_map)
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
                    run_cxx_ctors=needs_ctor_walk(sources),
                    patches=patches,
                ),
                symbol_table=table,
            )
        except ScriptError as exc:
            raise CodeError(f"{mod.name}:\n{exc.render(source.where)}") from exc
        generated_c = compiled.generated.text
    else:
        # Native-only: still needs the REL entry points and `mod_prolog`.
        generated_c = emit.generate_bare(
            origin=f"{mod.name} native sources",
            banner=banner,
            run_cxx_ctors=needs_ctor_walk(sources),
            patches=patches,
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
