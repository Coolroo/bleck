"""Several mods' programs as one C translation unit.

The loader opens exactly one `/mod/mod.rel`, so merging happens at **compile**
time rather than via runtime REL chaining (D39, D78). That is the whole reason
this module exists: `chainrel`'s unsolved runtime chaining is not on this path.

Each mod keeps its own namespace — `prefix_for` derives it from the mod name —
and the shared runtime is emitted once, with hook tables that are the **union**
across mods. ⚠️ **A second `_prolog` would be a second set of installs fighting
over `seq_data`**, which is why `generate.footer` is called once with everything
rather than once per mod.

Split from `generate` because this is a different composition of the same
pieces, not a variation on one. It reads `generate` for the footer and
`blocks` for the per-program sections; neither reads it back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bleck.script.compiler.ir import CompiledProgram
from bleck.script.emit import blocks, checks, runtime_c
from bleck.script.emit.blocks import BoundCombo, BoundHook
from bleck.script.emit.generate import (
    EVT_ENTRY_DECL,
    EXTERNS_COMMENT,
    GeneratedSource,
    Runtime,
    footer,
)
from bleck.script.emit.scaffold import (
    ENTRY_SCRIPT,
    Banner,
    ComboHook,
    FunctionHook,
    MapHook,
    ScriptPatch,
    ScriptReplacement,
    prefix_for,
)
from bleck.script.errors import Position, ScriptError


@dataclass(frozen=True)
class ModPart:
    """One mod's compiled contribution to a module shared with other mods."""

    name: str
    program: CompiledProgram
    map_hooks: list[MapHook] = field(default_factory=list)
    combos: list[ComboHook] = field(default_factory=list)
    boot_script: str = ""
    replacements: list[ScriptReplacement] = field(default_factory=list)

    @property
    def prefix(self) -> str:
        return prefix_for(self.name)

    @property
    def entry(self) -> str:
        """This mod's free-running script, if it declares one. Optional here,
        unlike a single-mod build."""
        names = [script.name for script in self.program.scripts]
        return ENTRY_SCRIPT if ENTRY_SCRIPT in names else ""


def _merged_head(origin: str, externals: list[str]) -> list[str]:
    """The shared preamble a merged module opens with."""
    # pylint: disable=container-return  # ordered sections, joined by the caller
    head = [runtime_c.HEADER.format(origin=origin)]
    if externals:
        head.append(
            EXTERNS_COMMENT
            + "\n".join(f"extern void {name}(void);" for name in externals)
        )
    head.append(EVT_ENTRY_DECL)
    head.append(runtime_c.MOD_HOOK)
    head.append(runtime_c.CODE_PATCH)
    return head


def generate_merged(
    parts: list[ModPart],
    origin: str = "several mods",
    *,
    banner: Banner | None = None,
    run_cxx_ctors: bool = False,
    patches: list[ScriptPatch] | None = None,
    function_hooks: list[FunctionHook] | None = None,
) -> GeneratedSource:
    """Render several mods' programs as one C translation unit.

    `patches` is the union already: a patch names C functions rather than
    compiled scripts, so it needs no namespace and is passed whole.
    """
    if not parts:
        raise ScriptError("no mods to merge", Position())
    checks.check_slugs([part.name for part in parts])

    booting = [part for part in parts if part.boot_script]
    if len(booting) > 1:
        raise ScriptError(
            f"{len(booting)} mods declare a boot map "
            f"({', '.join(part.name for part in booting)}), but a disc "
            f"starts in one place.\n"
            f"  Keep it on one of them, or pass --map to override for a build.",
            Position(),
        )

    sections: list[str] = []
    entries: list[str] = []
    hooks: list[BoundHook] = []
    combos: list[BoundCombo] = []
    swaps: list[ScriptReplacement] = []
    externals: list[str] = []
    boot = ""

    for part in parts:
        checks.check_map_hooks(part.program, part.map_hooks)
        checks.check_combo_hooks(part.program, part.combos)
        checks.check_boot_script(part.program, part.boot_script)

        sections.append(runtime_c.MOD_SECTION.format(name=part.name))
        sections.extend(blocks.program_section(part.program, part.prefix))

        if part.entry:
            entries.append(f"{part.prefix}script_{part.entry}")
        hooks += blocks.bind_maps(part.map_hooks, part.prefix)
        swaps += blocks.bind_replacements(part.replacements, part.prefix)
        combos += blocks.bind_combos(part.combos, part.prefix)
        if part.boot_script:
            boot = f"{part.prefix}script_{part.boot_script}"
        for name in part.program.called_symbols:
            if name not in externals:
                externals.append(name)

    runtime = Runtime(
        banner=banner,
        boot=boot,
        combos=combos,
        run_cxx_ctors=run_cxx_ctors,
        patches=list(patches or []),
        replacements=swaps,
        function_hooks=list(function_hooks or []),
    )
    text = "\n\n".join(
        _merged_head(origin, externals) + sections + [footer(entries, hooks, runtime)]
    )
    checks.require_ascii(text)
    return GeneratedSource(
        text=text,
        entry_script=", ".join(entries),
        external_symbols=externals,
    )
