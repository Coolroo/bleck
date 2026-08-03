"""`code.patches`, `tables.doors` and `code.replace`, resolved for the emitter.

Split from `parts` because all three answer the same question — *what does this
mod want done to the game's own scripts* — and none of them needs the compiler,
the toolchain or the symbol table. They share `defined_functions`, which is why
that lives in `sources` rather than here.

⚠️ **A door table is code, not placement.** Enemy and coin tables become
setup-file data in `bleck/mods/build/edits.py`; these become patches, so they
are resolved here and `PLACEMENT_KINDS` excludes `DOORS` (D134).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from bleck.formats import tables
from bleck.mods.code.errors import CodeError
from bleck.mods.code.sources import defined_functions
from bleck.mods.manifest import CodeSpec, TableKind, codespec
from bleck.mods.registry import Mod
from bleck.script import emit


@dataclass(frozen=True)
class SourcedPatch:
    """One patch and where it was written, so an error can name the right place.

    A `ScriptPatch` deliberately does not carry a filename -- it is what a mod
    *declares*, not where -- but "code.patches[3]" is a lie when the patch came
    from row 4 of a CSV.
    """

    patch: codespec.ScriptPatch
    where: str


def door_patches(mod: Mod) -> list[SourcedPatch]:
    """A mod's `tables.doors` rows, as the patches `code.patches` would hold.

    Each row is turned back into the selector a manifest would spell and run
    through `build_patch`, so a table and an inline patch are validated by
    exactly the same code and refuse exactly the same things.
    """
    # pylint: disable=container-return
    out: list[SourcedPatch] = []
    for ref in mod.tables_of(TableKind.DOORS):
        path = mod.root / ref.path
        if not path.is_file():
            raise CodeError(
                f"{mod.name}: no table at {ref.path}, declared under "
                f"'tables.{ref.kind}' in mod.json"
            )
        table = tables.doors.read(path, source=ref.path, map_name=ref.map_name)
        for row in table.rows:
            where = f"{table.source}:{row.line}"
            out.append(
                SourcedPatch(
                    patch=codespec.build_patch(
                        row.selector, row.at, row.expect, row.call, where
                    ),
                    where=where,
                )
            )
    return out


def patches_for(mod: Mod, spec: CodeSpec, sources: list[Path]) -> list[emit.ScriptPatch]:
    """Resolve `code.patches` and `tables.doors` for the emitter, checking each
    `call` exists.

    Without this the typo reaches `elf2rel`, which reports it as a missing
    *game* symbol -- the mod's own function looks like an address it should
    have found in the symbol list.
    """
    # pylint: disable=container-return
    declared = [
        SourcedPatch(patch=patch, where=f"code.patches[{index}]")
        for index, patch in enumerate(spec.patches)
    ] + door_patches(mod)
    if not declared:
        return []
    defined = defined_functions(sources)
    for item in declared:
        if item.patch.call in defined:
            continue
        listed = ", ".join(defined) or "none"
        close = difflib.get_close_matches(item.patch.call, defined, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {close[0]!r}?" if close else ""
        raise CodeError(
            f"{mod.name}: {item.where} calls {item.patch.call!r}, but "
            f"this mod's sources define no such function "
            f"(they define: {listed}).{hint}\n"
            f"  A patched instruction calls a function with evt's user-func "
            f"signature -- `s32 f(EvtEntry *entry, bool firstCall)` -- which "
            f"must return 2 for the script to advance."
        )
    return [
        emit.ScriptPatch(
            kind=patch.kind,
            target=patch.emit_target,
            at=patch.at,
            expect=patch.expect_word,
            call=patch.call,
            index=patch.index,
            field_offset=patch.field_offset,
        )
        for patch in (item.patch for item in declared)
    ]


def replacements_for(_mod: Mod, spec: CodeSpec) -> list[emit.ScriptReplacement]:
    """Resolve `code.replace` for the emitter, checking each script exists.

    ⚠️ **This conversion is the whole point of the two types.** The manifest form
    holds what the author wrote; the emitter form holds a map name, an index and
    a field offset. The C symbol is left blank on purpose -- only the emitter
    knows the namespace, which is `bleck_` for one mod and a per-mod slug for a
    merged build. `emit.blocks.bind_replacements` fills it, as `bind_maps` does
    for hooks.
    """
    # pylint: disable=container-return
    if not spec.replacements:
        return []
    resolved = []
    for entry in spec.replacements:
        resolved.append(
            emit.ScriptReplacement(
                map_name=entry.map_name,
                index=entry.index,
                field_offset=entry.field_offset,
                script=entry.script,
                expect_word=entry.expect_word,
            )
        )
    return resolved
