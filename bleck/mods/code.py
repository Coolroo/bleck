"""Compiling a mod's script into the `mod.rel` its overlay ships.

This runs before the overlay is planned, because the plan is derived from a
walk of `overlay/` and the compiled module has to exist by then. The output goes
to `overlay/files/mod/mod.rel` and is then carried by the ordinary overlay
machinery -- a code mod is still just a mod, and nothing downstream needs to
know it was generated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bleck.backends import symbols as symbol_tables
from bleck.backends import toolchain
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.mods import registry as mod_registry
from bleck.mods.manifest import REL_DISC_PATH
from bleck.mods.registry import Mod
from bleck.mods.resolver import Chain
from bleck.script import ScriptError, compile_source, emit

#: Where compile intermediates live, under the build root.
#:
#: ⚠️ Deliberately *not* inside the mod's staged disc directory. These used to
#: go to `<build root>/<mod>/code`, which `builder.stage` then deleted wholesale
#: on its way to mirroring the base — so `mod.c` and `mod.elf` were gone by the
#: time anyone wanted to read them, and `build_rel`'s promise to keep its
#: intermediates held only for `bleck mod check`, never for a real build. That
#: is exactly backwards: a full build is when a compile error is most likely.
#:
#: Dotted so it cannot collide with a mod named after it; mod names are
#: otherwise unrestricted.
CODE_WORKDIR = ".code"


class CodeError(BleckError):
    """A mod's script could not be turned into a module."""


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

    def describe(self) -> str:
        parts = []
        if self.scripts:
            parts.append(f"{self.script.name} [{', '.join(self.scripts)}]")
        if self.sources:
            names = ", ".join(path.name for path in self.sources)
            parts.append(f"{len(self.sources)} source(s) [{names}]")
        what = " + ".join(parts) or "nothing"
        return (
            f"{self.mod}: compiled {what} -> {self.size} byte module ({self.toolchain})"
        )


def mods_with_code(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_code]


def build_chain(chain: Chain, workroot: Path | None = None) -> list[CodeBuild]:
    """Compile every code mod in `chain`, newest last.

    Raises before touching anything if the chain contains more than one code
    mod: the Gecko loader opens exactly one `/mod/mod.rel`, so a second would be
    silently dropped rather than merged. Failing loudly here is the interim
    answer to that; chaining several modules together is a separate feature.
    """
    coded = mods_with_code(chain)
    if len(coded) > 1:
        names = ", ".join(mod.name for mod in coded)
        raise CodeError(
            f"this chain contains {len(coded)} code mods ({names}), but the "
            f"loader can only run one {REL_DISC_PATH}.\n"
            "  Combine their scripts into a single mod for now."
        )

    root = workroot or mod_registry.build_root()
    return [build_mod(mod, root) for mod in coded]


def collect_sources(mod: Mod, spec) -> list[Path]:
    """Resolve `code.sources` to actual `.c` files.

    An entry may name a file or a directory; a directory contributes every `.c`
    beneath it, sorted, so a build does not depend on filesystem ordering.
    """
    found: list[Path] = []
    for entry in spec.sources:
        path = mod.root / entry
        if path.is_dir():
            matched = sorted(path.rglob("*.c"))
            if not matched:
                raise CodeError(f"{mod.name}: no .c files under {path}")
            found += matched
        elif path.exists():
            found.append(path)
        else:
            raise CodeError(
                f"{mod.name}: no source at {path}\n"
                f"  mod.json lists {entry!r} in 'code.sources'"
            )
    return found


def map_hooks_for(mod: Mod) -> list[emit.MapHook]:
    """The map attachments this mod declares, as the emitter wants them.

    The manifest speaks in map and script *names*; the emitter needs the same
    pairing but validates it against what the source actually declares.
    """
    spec = mod.manifest.code
    if spec is None:
        return []
    return [
        emit.MapHook(map_name=hook.map_name, script=hook.script) for hook in spec.maps
    ]


def banner_for(mod: Mod) -> emit.Banner | None:
    """The on-screen label this mod should draw, if any.

    The text comes from the mod's own name unless the manifest overrides it, so
    the common case needs nothing declared: build a mod, and the disc says which
    mod it is.
    """
    spec = mod.manifest.code
    if spec is None or not spec.banner.enabled:
        return None
    return emit.Banner(
        text=spec.banner.label(mod.name),
        sequences=tuple(
            emit.SEQUENCE_NAMES.index(name) for name in spec.banner.sequences
        ),
    )


def build_mod(mod: Mod, workroot: Path) -> CodeBuild:
    """Compile one mod's script and native sources into its `mod.rel`."""
    spec = mod.manifest.code
    if spec is None:
        raise CodeError(f"{mod.name} declares no code to build")

    # The same table the link will use, so "that will not link" is said now
    # rather than after a compile and a toolchain run (D61).
    table = symbol_tables.best_available(
        toolchain.symbols_file(spec.target), env.path(env.DECOMP_DIR), spec.target
    )
    sources = collect_sources(mod, spec)
    script_path = mod.root / spec.script if spec.has_script else None
    banner = banner_for(mod)
    compiled = None

    if script_path is not None:
        if not script_path.exists():
            raise CodeError(
                f"{mod.name}: no script at {script_path}\n"
                f"  mod.json points 'code.script' at {spec.script!r}"
            )
        try:
            compiled = compile_source(
                script_path.read_text(encoding="utf-8"),
                origin=spec.script,
                map_hooks=map_hooks_for(mod),
                banner=banner,
                symbol_table=table,
            )
        except ScriptError as exc:
            raise CodeError(f"{mod.name}:\n{exc.render(str(script_path))}") from exc
        scaffolding = compiled.generated.text
    else:
        # Native-only: still needs the REL entry points and the `mod_prolog`
        # hand-off, just nothing to hand to the scheduler.
        scaffolding = emit.generate_bare(
            origin=f"{mod.name} native sources", banner=banner
        ).text

    headers = env.path(env.HEADERS_DIR)
    result = toolchain.build_rel(
        toolchain.BuildRequest(
            source=scaffolding,
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
        script=script_path or mod.root,
        output=output,
        size=result.size,
        toolchain=result.toolchain,
        scripts=compiled.script_names if compiled else [],
        called_symbols=list(compiled.program.called_symbols) if compiled else [],
        sources=sources,
    )
