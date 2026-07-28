"""Compiling a mod's script into the `mod.rel` its overlay ships.

This runs before the overlay is planned, because the plan is derived from a
walk of `overlay/` and the compiled module has to exist by then. The output goes
to `overlay/files/mod/mod.rel` and is then carried by the ordinary overlay
machinery -- a code mod is still just a mod, and nothing downstream needs to
know it was generated.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from bleck.backends import symbols as symbol_tables
from bleck.backends import toolchain
from bleck.common import config as project_config
from bleck.common import env
from bleck.common.errors import BleckError
from bleck.mods import registry as mod_registry
from bleck.mods.manifest import REL_DISC_PATH, CodeSpec
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
class CodeOverride:
    """Build-time changes to what a mod compiles, from the command line.

    Separate from the manifest because these are properties of *this build*,
    not of the mod: `--map` exists so a disc can be thrown at a level for one
    test without editing and un-editing `mod.json` around it. Anything worth
    keeping belongs in the manifest, where it is reviewable.
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
        # Said out loud because a boot map changes where the disc *goes*, which
        # is the kind of surprise worth naming in build output rather than
        # leaving someone to wonder why the attract demo stopped playing.
        where = f", boots at {self.boot_map}" if self.boot_map else ""
        return (
            f"{self.mod}: compiled {what} -> "
            f"{self.size} byte module ({self.toolchain}){where}"
        )


@dataclass(frozen=True)
class ScriptSource:
    """Script text on its way to the compiler, and where it came from.

    `path` is None when `bleck` generated the text itself, which is why the two
    are separate: an error position means something different in a file someone
    wrote than in one that only exists inside this process.
    """

    text: str
    path: Path | None
    origin: str

    @property
    def where(self) -> str:
        """What to name in an error message."""
        return str(self.path) if self.path is not None else self.origin


def mods_with_code(chain: Chain) -> list[Mod]:
    return [mod for mod in chain.mods if mod.manifest.has_code]


def build_chain(
    chain: Chain,
    workroot: Path | None = None,
    override: CodeOverride | None = None,
) -> list[CodeBuild]:
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

    # An override can give code to a chain that has none. That is the point:
    # `--map` has to work on a pure asset or placement mod, which is exactly the
    # kind of mod someone wants to look at inside a particular level.
    if not coded and override is not None and not override.is_empty:
        coded = [chain.target]

    root = workroot or mod_registry.build_root()
    return [build_mod(mod, root, override) for mod in coded]


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


def combo_hooks_for(mod: Mod, spec, settings) -> list[emit.ComboHook]:
    """Resolve each `code.combos` binding against `bleck.yml`.

    The manifest names a combination and the config says which buttons it is.
    Joining the two here means a mod never contains a button mask, so changing
    what `start_map` means is one edit in one file.
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


def banner_for(mod: Mod, spec=None) -> emit.Banner | None:
    """The on-screen label this mod should draw, if any.

    The text comes from the mod's own name unless the manifest overrides it, so
    the common case needs nothing declared: build a mod, and the disc says which
    mod it is.

    `spec` is passed explicitly when the build is working from something other
    than the manifest's own `code` block — a `--map` build of an asset mod has a
    synthesized spec, and that disc should still name itself.
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


def _script_text(mod: Mod, spec, boot_map: str) -> ScriptSource:
    """The script source to compile: the mod's own, the boot script, or both.

    A boot map is desugared into script source and appended, so a mod that
    already has a script keeps it and gains one, and a mod with no script at all
    still ends up with something the compiler can process. Appending rather than
    generating a second translation unit means one `evtEntry` table, one string
    table, and one place where a duplicate script name is an error.
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
