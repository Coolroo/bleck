"""`code.hooks`: a game function's name, resolved to an address and a guard word.

Split from `parts` because this is the one part of a code build that reads the
**base disc's DOL**, and everything it does follows from that: the guard word
is the instruction actually sitting at the target, so a hook either has one
that `bleck` read or has none at all.

Three things are checked here and nowhere else — the symbol exists in the
target's list, the mod defines the function it says it does, and the guard
compares against a word read out of the base disc rather than one invented.

⚠️ **A hook whose address the DOL does not map installs unguarded**, and the
warning says which of the three reasons applies. Faking a guard would be worse
than not having one. ⛔ Interception (`before`/`after`) is *refused* in that
case rather than warned about: it reaches the original by restoring the first
instruction, so with no word to restore it would branch into itself until the
stack ran out (D96).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from bleck.backends import dol as dol_reader
from bleck.backends import symbols as symbol_tables
from bleck.mods import registry as mod_registry
from bleck.mods.code.errors import CodeError
from bleck.mods.code.sources import defined_functions
from bleck.mods.manifest import CodeSpec
from bleck.mods.manifest.codespec import FunctionHook
from bleck.mods.registry import Mod
from bleck.script import emit

#: Where the pristine DOL lives inside an extracted build.
DOL_PATH = "sys/main.dol"


@dataclass(frozen=True)
class ResolvedHooks:
    """`code.hooks` turned into what the emitter wants, plus what it could not do.

    A hook whose address the DOL does not map installs **unguarded**, and the
    warning says so. Faking a guard would be worse than not having one.
    """

    hooks: list[emit.FunctionHook] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _base_dol(base: Path) -> dol_reader.Dol | None:
    """The base disc's `main.dol`, or None when there is no readable one."""
    try:
        return dol_reader.read(base / DOL_PATH)
    except dol_reader.DolError:
        return None


def function_hooks_for(
    mod: Mod,
    spec: CodeSpec,
    sources: list[Path],
    table: symbol_tables.SymbolTable,
) -> ResolvedHooks:
    """Resolve `code.hooks`: name to address, and derive each guard word."""
    if not spec.hooks:
        return ResolvedHooks()

    defined = defined_functions(sources)
    base = mod_registry.base_root()
    dol = _base_dol(base)
    hooks: list[emit.FunctionHook] = []
    warnings: list[str] = []

    for index, hook in enumerate(spec.hooks):
        where = f"{mod.name}: 'code.hooks[{index}]'"
        _check_hook_call(hook, defined, where)
        address = _hook_address(hook, table, where)
        word = dol.word_at(address) if dol is not None else None
        if word is None:
            _check_interception_possible(hook, address, where)
            warnings.append(_no_guard_warning(hook, address, base, dol, where))
        else:
            warnings += _section_warning(hook, address, dol, where)
        hooks.append(
            emit.FunctionHook(
                call=hook.call,
                address=address,
                symbol="" if hook.is_address else hook.function,
                expect=word or 0,
                guarded=word is not None,
                mode=hook.mode,
            )
        )
    return ResolvedHooks(hooks=hooks, warnings=warnings)


def _check_interception_possible(hook: FunctionHook, address: int, where: str) -> None:
    """`before` and `after` need a guard word; `replace` does not.

    Interception reaches the original by restoring the function's first
    instruction, calling it, and re-installing the branch (D96). That word comes
    out of `main.dol` at build time, so an address the DOL does not map -- a REL
    address, say -- leaves nothing to restore.

    A `replace` hook installs unguarded with a warning, because it never needs to
    put the original back. Interception would build fine and then recurse into
    itself at run time until the stack ran out, so it is refused here instead.
    """
    if not hook.intercepts:
        return
    raise CodeError(
        f"{where}: 'mode' is {hook.mode!r}, but bleck could not read the "
        f"instruction at 0x{address:08X} out of the base disc's main.dol.\n"
        f"  {hook.mode!r} runs the original as well as your function, and it "
        f"reaches the original by putting that instruction back for the "
        f"duration of the call. With no word to restore there is nothing to "
        f"call, and the hook would branch into itself until the stack ran out.\n"
        f"  Addresses above the DOL belong to a REL, which is loaded per map "
        f"and is not on the disc as plain code.\n"
        f"  Use 'replace' if taking the function over is acceptable."
    )


def _check_hook_call(hook: FunctionHook, defined: list[str], where: str) -> None:
    """The mod has to define the function it hands the game control to.

    Without this the typo reaches `elf2rel`, which reports it as a missing
    *game* symbol -- the mod's own function looks like an address it should
    have found in the symbol list.
    """
    if hook.call in defined:
        return
    listed = ", ".join(defined) or "none"
    close = difflib.get_close_matches(hook.call, defined, n=1, cutoff=0.6)
    hint = f"\n  Did you mean {close[0]!r}?" if close else ""
    raise CodeError(
        f"{where}.call names {hook.call!r}, but this mod's sources define no "
        f"such function (they define: {listed}).{hint}\n"
        f"  {_signature_rule(hook)}"
    )


def _signature_rule(hook: FunctionHook) -> str:
    """Why the mod's function has to match the one it hooks -- which differs by
    mode, and gets the reasoning wrong in both directions if it does not."""
    if not hook.intercepts:
        return (
            f"A {hook.mode!r} hook takes {hook.function} over, so it must accept "
            f"the same arguments AND return what the caller expects -- the "
            f"original never runs."
        )
    return (
        f"A {hook.mode!r} hook runs alongside {hook.function}, so it must accept "
        f"the same arguments. Its return value is discarded: the caller receives "
        f"the original's."
    )


def _hook_address(
    hook: FunctionHook, table: symbol_tables.SymbolTable, where: str
) -> int:
    """The address a hook's `function` names, resolved against the target list."""
    if hook.is_address:
        return hook.address
    found = table.find(hook.function)
    if found is not None:
        return found.address
    names = [symbol.name for symbol in table.named]
    close = difflib.get_close_matches(hook.function, names, n=1, cutoff=0.6)
    hint = f"\n  Did you mean {close[0]!r}?" if close else ""
    raise CodeError(
        f"{where}.function names {hook.function!r}, which is not in the symbol "
        f"list for this target ({table.source}, {len(names)} named "
        f"symbols).{hint}\n"
        f"  `bleck symbols search {hook.function}` lists near matches.\n"
        f"  Resolving by name is the point: a wrong name fails the build "
        f"rather than branching into unrelated code."
    )


def _section_warning(
    hook: FunctionHook, address: int, dol: dol_reader.Dol, where: str
) -> list[str]:
    """A hook aimed at the DOL's *data* is almost certainly a wrong address.

    Warned rather than refused: the guard still makes it deterministic, and the
    DOL's data span is wide (eu0 reaches 0x805B7720), so an address that looks
    like code can land in it.
    """
    # pylint: disable=container-return
    section = dol.section_for(address)
    if section is None or section.is_text:
        return []
    return [
        f"{where}: {hook.function} resolves to {address:08X}, which is in "
        f"{dol.path.name}'s {section.name} -- data, not code.\n"
        f"  A hook writes a branch instruction there, so unless that word "
        f"really is code this is the wrong address."
    ]


def _no_guard_warning(
    hook: FunctionHook,
    address: int,
    base: Path,
    dol: dol_reader.Dol | None,
    where: str,
) -> str:
    """Say exactly why a hook is going in without a derived guard."""
    if dol is None:
        why = f"there is no readable DOL at {base / DOL_PATH}"
    elif dol.section_for(address) is None:
        why = (
            f"{address:08X} is outside {dol.path.name}, which loads "
            f"{dol.address_range} -- most likely a REL address, and REL text "
            f"is not in the base disc's DOL to read"
        )
    else:
        why = f"{address:08X} is inside the DOL but its word could not be read"
    return (
        f"{where}: hooking {hook.function} with no derived guard, because "
        f"{why}.\n"
        f"  It will install without checking what is there, so a wrong address "
        f"or the wrong game version corrupts an instruction instead of being "
        f"refused."
    )
