"""What has to be true before a module is written, and the message when it is not.

Split from `generate` because every check reads a `CompiledProgram` and some
manifest values, and none of them touches the C. They are grouped here because
they all guard the same seam: **nothing connects `mod.json` to the script source
until code generation**, so a name misspelled in the manifest would otherwise
reach the C compiler as an undefined symbol naming an identifier the author
never wrote.

Each raise carries a `difflib` suggestion for that reason — the failure has to
name the manifest key and the script list, because the compiler's version of it
names neither.
"""

from __future__ import annotations

import difflib

from bleck.script.compiler.ir import CompiledProgram
from bleck.script.emit.scaffold import (
    ENTRY_SCRIPT,
    ComboHook,
    MapHook,
    ScriptReplacement,
    mod_slug,
)
from bleck.script.errors import Position, ScriptError


def require_ascii(text: str) -> None:
    """Guard the invariant that generated C is pure ASCII.

    Linux, macOS and Windows toolchains disagree on default source encoding.
    String contents are already escaped byte-wise, so a failure here means a
    non-ASCII comment template in `runtime_c` -- a `bleck` bug.
    """
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        offending = text[exc.start : exc.end]
        raise ValueError(
            f"generated C contains non-ASCII {offending!r}; "
            "this is a bug in bleck's code templates"
        ) from exc


def check_slugs(names: list[str]) -> None:
    """Two mods must not reduce to the same namespace.

    `hard-mode` and `hard mode` both become `hard_mode`, which would otherwise
    surface as a linker error naming a generated identifier nobody wrote.
    """
    seen: dict[str, str] = {}
    for name in names:
        slug = mod_slug(name)
        if slug in seen:
            raise ScriptError(
                f"mods {seen[slug]!r} and {name!r} both reduce to the "
                f"namespace {slug!r}, so their generated symbols would collide.\n"
                f"  Rename one of them.",
                Position(),
            )
        seen[slug] = name


def check_combo_hooks(program: CompiledProgram, hooks: list[ComboHook]) -> None:
    """Every combination's script has to exist, and be spelled the same twice.

    Nothing connects `mod.json` to the source until here, so a typo would
    otherwise reach the C compiler as an undefined symbol.
    """
    names = [script.name for script in program.scripts]
    for hook in hooks:
        if hook.script in names:
            continue
        listed = ", ".join(names) or "none"
        suggestion = difflib.get_close_matches(hook.script, names, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {suggestion[0]!r}?" if suggestion else ""
        raise ScriptError(
            f"mod.json binds combo {hook.name!r} to script {hook.script!r}, "
            f"but this file declares no such script "
            f"(it declares: {listed}).{hint}",
            Position(),
        )


def check_map_hooks(program: CompiledProgram, hooks: list[MapHook]) -> None:
    """Every attached script has to exist, and be named the same way twice.

    Nothing links the manifest to the source until here, so a typo would
    otherwise reach the C compiler as an undefined symbol.
    """
    names = [script.name for script in program.scripts]
    for hook in hooks:
        if hook.script in names:
            continue
        listed = ", ".join(names) or "none"
        suggestion = difflib.get_close_matches(hook.script, names, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {suggestion[0]!r}?" if suggestion else ""
        raise ScriptError(
            f"mod.json attaches {hook.script!r} to map {hook.map_name!r}, "
            f"but this file declares no such script "
            f"(it declares: {listed}).{hint}",
            Position(),
        )


def check_replacements(
    program: CompiledProgram, replacements: list[ScriptReplacement]
) -> None:
    """Every swapped-in script has to exist in the program that was compiled.

    Same reason as `check_map_hooks`: nothing links the manifest to the source
    until here, so a typo would otherwise reach the C compiler as an undefined
    symbol naming an identifier the author never wrote.
    """
    names = [script.name for script in program.scripts]
    for entry in replacements:
        if entry.script in names:
            continue
        listed = ", ".join(names) or "none"
        close = difflib.get_close_matches(entry.script, names, n=1, cutoff=0.6)
        hint = f"\n  Did you mean {close[0]!r}?" if close else ""
        raise ScriptError(
            f"mod.json replaces {entry.selector} with {entry.script!r}, but "
            f"this file declares no such script (it declares: {listed}).{hint}\n"
            f"  A replacement names a script, not a C function: its whole "
            f"bytecode becomes the door's.",
            Position(),
        )


def check_boot_script(program: CompiledProgram, name: str) -> None:
    """The boot script has to be in the program the caller compiled.

    `bleck` generates its source, so a failure here is a bug in `bleck`; it is
    checked so it does not surface as an undefined C symbol instead.
    """
    if not name or any(script.name == name for script in program.scripts):
        return
    listed = ", ".join(script.name for script in program.scripts) or "none"
    raise ScriptError(
        f"boot script {name!r} is missing from the compiled program "
        f"(it declares: {listed}). This is a bug in bleck.",
        Position(),
    )


def entry_script(program: CompiledProgram, required: bool = True) -> str:
    """The free-running script the module starts, or `""` where none is needed."""
    names = [script.name for script in program.scripts]
    if ENTRY_SCRIPT in names:
        return ENTRY_SCRIPT
    if not required:
        return ""
    listed = ", ".join(names)
    raise ScriptError(
        f"no script named {ENTRY_SCRIPT!r} to start "
        f"(this file declares: {listed}). "
        f"Rename one to {ENTRY_SCRIPT!r}, or spawn the others from it",
        Position(),
    )
