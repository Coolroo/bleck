"""Writing compiled scripts out as C, for the existing REL toolchain to build.

Generating C rather than an object file directly is what lets this reuse the
whole proven path — devkitPPC, the relocatable link, `pyelf2rel` — instead of
becoming a second, parallel code generator that has to learn ELF and PowerPC
relocations by itself.

It also solves the address problem cleanly. Scripts refer to game functions by
name; the generated C declares them `extern` and takes their address, and
`elf2rel` binds each one through the symbol list at REL-build time. So no game
address is ever written by `bleck`, and no symbol list has to be redistributed
with it.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from bleck.script.compiler.ir import (
    CompiledProgram,
    CompiledScript,
    Literal,
    ScriptWord,
    StringWord,
    SymbolWord,
    Word,
)
from bleck.script.emit import runtime_c

# Re-exported: `emit.MapHook` and friends are how the rest of the toolkit has
# always named these, and the split is about where they live.
# pylint: disable=unused-import
from bleck.script.emit.scaffold import (  # noqa: F401
    _PREFIX,
    BOOT_DELAY_FRAMES,
    BOOT_SCRIPT,
    DEFAULT_BANNER_SEQUENCES,
    ENTRY_SCRIPT,
    MAX_COMBOS,
    MAX_MAP_HOOKS,
    SEQUENCE_NAMES,
    Banner,
    ComboHook,
    MapHook,
    Scaffolding,
    mod_slug,
    prefix_for,
)
from bleck.script.errors import Position, ScriptError


@dataclass(frozen=True)
class GeneratedSource:
    """C source for a compiled program, plus what it needs from the linker."""

    text: str
    entry_script: str
    external_symbols: list[str]

    @property
    def line_count(self) -> int:
        return len(self.text.splitlines())


def _c_string(text: str) -> str:
    """Escape a Python string as a C string literal.

    Non-ASCII is escaped byte-wise from UTF-8 rather than emitted raw, so the
    generated file stays pure ASCII and cannot be re-encoded by an editor into
    something the compiler reads differently.
    """
    out = ""
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if char == "\\":
            out += "\\\\"
        elif char == '"':
            out += '\\"'
        elif char == "\n":
            out += "\\n"
        elif char == "\t":
            out += "\\t"
        elif char == "\r":
            out += "\\r"
        elif 0x20 <= byte < 0x7F:
            out += char
        else:
            # Octal, not hex: a hex escape in C consumes every following hex
            # digit, so "\x41" followed by a literal 'B' would parse as one
            # oversized escape. Octal is capped at three digits.
            out += f"\\{byte:03o}"
    return f'"{out}"'


def _word_text(word: Word, prefix: str = _PREFIX) -> str:
    if isinstance(word, Literal):
        return str(word.value)
    if isinstance(word, SymbolWord):
        return f"(s32) &{word.name}"
    if isinstance(word, StringWord):
        return f"(s32) {prefix}string_{word.index}"
    if isinstance(word, ScriptWord):
        return f"(s32) {prefix}script_{word.name}"
    raise TypeError(f"unknown word type {type(word).__name__}")


def _script_array(script: CompiledScript, prefix: str = _PREFIX) -> str:
    lines = [
        f"/* {script.name}: {len(script.words)} words, "
        f"{script.slots_used} of 16 local slots used */",
        f"const s32 {prefix}script_{script.name}[] = {{",
    ]
    # Four per line: enough to be compact, few enough that a diff points at a
    # small region when bytecode changes.
    row: list[str] = []
    for word in script.words:
        row.append(_word_text(word, prefix))
        if len(row) == 4:
            lines.append("    " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("    " + ", ".join(row) + ",")
    lines.append("};")
    return "\n".join(lines)


@dataclass(frozen=True)
class BoundHook:
    """A map hook whose script has been resolved to a C identifier.

    The indirection exists because a merged module's hook table is a *union*
    across mods, and each row's script lives in whichever mod declared it. One
    namespace cannot name them all, so the symbol is resolved before the table
    is built rather than during.
    """

    map_name: str
    symbol: str


@dataclass(frozen=True)
class BoundCombo:
    """A combination whose script has been resolved to a C identifier."""

    name: str
    mask: int
    symbol: str

    @property
    def comment(self) -> str:
        return f"/* {self.name} */"


def _bind_maps(hooks: list[MapHook], namespace: str) -> list[BoundHook]:
    return [
        BoundHook(map_name=h.map_name, symbol=f"{namespace}script_{h.script}")
        for h in hooks
    ]


def _bind_combos(combos: list[ComboHook], namespace: str) -> list[BoundCombo]:
    return [
        BoundCombo(name=c.name, mask=c.mask, symbol=f"{namespace}script_{c.script}")
        for c in combos
    ]


def _map_block(hooks: list[BoundHook], namespace: str = _PREFIX) -> str:
    """Map names, the scripts they start, and the sequence watcher."""
    if len(hooks) > MAX_MAP_HOOKS:
        raise ScriptError(
            f"{len(hooks)} map hooks declared, but at most {MAX_MAP_HOOKS} are "
            f"supported -- `bleck_map_pending` tracks one bit each in a 32-bit "
            f"word, and the next one would shift past the end.",
            Position(),
        )
    prefix = f"{namespace}map_"
    tables = "".join(
        runtime_c.MAP_TABLE.format(
            prefix=prefix, index=index, name=_c_string(hook.map_name)
        )
        for index, hook in enumerate(hooks)
    )
    return runtime_c.MAP_BLOCK.format(
        count=len(hooks),
        tables=tables,
        name_list="".join(f"    {prefix}name_{i},\n" for i in range(len(hooks))),
        script_list="".join(f"    {h.symbol},\n" for h in hooks),
    )


def _banner_block(banner: Banner) -> str:
    return runtime_c.BANNER_BLOCK.format(text=_c_string(banner.text), flags=banner.flags)


def _combo_block(hooks: list[BoundCombo]) -> str:
    """Mask and script tables, plus the per-frame watcher."""
    if len(hooks) > MAX_COMBOS:
        raise ScriptError(
            f"{len(hooks)} button combinations declared, but at most "
            f"{MAX_COMBOS} are supported -- `bleck_combo_down` tracks one bit "
            f"each in a 32-bit word.",
            Position(),
        )
    return runtime_c.COMBO_BLOCK.format(
        count=len(hooks),
        masks="".join(f"    0x{hook.mask:08X}u,  {hook.comment}\n" for hook in hooks),
        scripts="".join(f"    {hook.symbol},\n" for hook in hooks),
    )


def boot_source(map_name: str, delay: int = BOOT_DELAY_FRAMES) -> str:
    """The script text a `code.boot` declaration desugars into.

    Generated as *source* and run through the ordinary compiler rather than
    emitted as bytecode. That is the difference between a feature and a special
    case: the map name goes through the same string table, the call goes through
    the same symbol-table check that would reject `evt_seq_mapchange` if it were
    not linkable, and the result shows up in build output as a script like any
    other.

    `map_name` is validated against the game's own map list before it gets here,
    so it cannot carry anything that needs escaping.
    """
    return (
        f"-- Generated by bleck from `code.boot`: start the game at {map_name}.\n"
        "--\n"
        "-- Edit mod.json, not this. See docs/testing.md.\n"
        f"script {BOOT_SCRIPT} {{\n"
        f"    wait({delay})\n"
        "    -- Door 0 means 'use the map's own default entrance', which\n"
        "    -- spm/map_data.h documents as the behaviour for a null door name.\n"
        f'    evt_seq_mapchange("{map_name}", 0)\n'
        "}\n"
    )


def _footer(
    entries: list[str],
    hooks: list[BoundHook],
    *,
    banner: Banner | None = None,
    boot: str = "",
    combos: list[BoundCombo] | None = None,
    namespace: str = _PREFIX,
) -> str:
    """Assemble the shared runtime, from the pieces the module needs.

    Emitted **once** however many mods contributed, which is the whole reason
    the hook tables are unions rather than per-mod: a second `_prolog` would be
    a second set of installs fighting over `seq_data`.

    A free-running script and a map hook want the same per-frame hook on the
    sequence table -- one to start and re-start itself, the other to notice
    where the game went. A mod using both installs one set of hooks, not two.
    """
    combos = list(combos or [])
    if not entries and not hooks and banner is None and not boot and not combos:
        return runtime_c.PLAIN_PROLOG + runtime_c.ENTRY_POINTS

    parts = [runtime_c.SEQ_TABLE]
    body = ""

    if banner is not None:
        parts.append(_banner_block(banner))
        body += "    if (bleck_banner_on[seq])\n        bleck_draw_banner();\n"
    if hooks:
        parts.append(_map_block(hooks, namespace))
        body += "    bleck_maps_on_seq(seq);\n"
    if combos:
        parts.append(_combo_block(combos))
        body += "    bleck_combos_on_seq(seq);\n"
    if len(entries) == 1:
        # The single-mod form, kept verbatim so a one-mod disc emits exactly
        # what it always has.
        parts.append(runtime_c.SCRIPT_START % entries[0])
        body += "    bleck_start_entry(seq);\n"
    elif entries:
        parts.append(
            runtime_c.SCRIPT_START_MANY.format(
                count=len(entries),
                entries="".join(f"    {name},\n" for name in entries),
            )
        )
        body += "    bleck_start_entry(seq);\n"
    # Last, so anything else due this frame has already run: the boot script
    # tears the world down a couple of seconds later.
    if boot:
        parts.append(runtime_c.BOOT_BLOCK.format(script=boot))
        body += "    bleck_boot_on_seq(seq);\n"

    parts.append(
        "\nstatic void bleck_after_seq(u32 seq, void *work)\n"
        "{\n"
        f"{body}"
        "\n    if (bleck_real_main[seq] != 0)\n"
        "        bleck_real_main[seq](work);\n"
        "}\n"
    )
    parts.append(runtime_c.SEQ_STUBS)
    parts.append(
        f"\nvoid _prolog(void)\n{{\n{runtime_c.SEQ_INSTALL}    mod_prolog();\n}}\n"
    )
    parts.append(runtime_c.ENTRY_POINTS)
    return "".join(parts)


def _program_section(program: CompiledProgram, prefix: str) -> list[str]:
    """One program's strings and script arrays, under its own namespace.

    Split out so the single-mod and merged paths emit *identical* per-program
    code and differ only in how many sections there are and what shared runtime
    follows them.
    """
    parts: list[str] = []
    if program.strings:
        parts.append(
            "\n".join(
                f"static const char {prefix}string_{index}[] = {_c_string(text)};"
                for index, text in enumerate(program.strings)
            )
        )
    if len(program.scripts) > 1:
        # Scripts may spawn each other in any order, so every array is declared
        # before any is defined.
        parts.append(
            "\n".join(
                f"extern const s32 {prefix}script_{script.name}[];"
                for script in program.scripts
            )
        )
    parts.extend(_script_array(script, prefix) for script in program.scripts)
    return parts


def generate_bare(
    origin: str = "native sources", banner: Banner | None = None
) -> GeneratedSource:
    """Scaffolding for a mod that ships only native C.

    The REL format still needs its three entry points, and the mod still needs
    somewhere to be called from, but there is no script to schedule.
    """
    text = (
        runtime_c.HEADER.format(origin=origin)
        + "\n"
        + runtime_c.MOD_HOOK
        + _footer([], [], banner=banner)
    )
    _require_ascii(text)
    return GeneratedSource(text=text, entry_script="", external_symbols=[])


def generate(
    program: CompiledProgram,
    origin: str = "a script",
    scaffolding: Scaffolding | None = None,
) -> GeneratedSource:
    """Render a compiled program as a single C translation unit."""
    plan = scaffolding or Scaffolding()
    hooks = list(plan.map_hooks)
    _check_map_hooks(program, hooks)
    _check_combo_hooks(program, plan.combos)
    _check_boot_script(program, plan.boot_script)
    entry = _entry_script(program, required=plan.needs_entry_script)

    parts = [runtime_c.HEADER.format(origin=origin)]

    if program.called_symbols:
        parts.append(
            "/* Game functions called by USER_FUNC, bound by elf2rel. */\n"
            + "\n".join(f"extern void {name}(void);" for name in program.called_symbols)
        )

    parts.append(
        "/* Started by the game's script scheduler. */\n"
        "extern void *evtEntry(const s32 *script, u32 priority, u8 flags);"
    )
    parts.append(runtime_c.MOD_HOOK)

    parts.extend(_program_section(program, plan.prefix))
    parts.append(
        _footer(
            [f"{plan.prefix}script_{entry}"] if entry else [],
            _bind_maps(hooks, plan.prefix),
            banner=plan.banner,
            boot=(f"{plan.prefix}script_{plan.boot_script}" if plan.boot_script else ""),
            combos=_bind_combos(plan.combos, plan.prefix),
            namespace=plan.prefix,
        )
    )

    text = "\n\n".join(parts)
    _require_ascii(text)
    return GeneratedSource(
        text=text,
        entry_script=entry,
        external_symbols=list(program.called_symbols),
    )


@dataclass(frozen=True)
class ModPart:
    """One mod's compiled contribution to a module shared with other mods."""

    name: str
    program: CompiledProgram
    map_hooks: list[MapHook] = field(default_factory=list)
    combos: list[ComboHook] = field(default_factory=list)
    boot_script: str = ""

    @property
    def prefix(self) -> str:
        return prefix_for(self.name)

    @property
    def entry(self) -> str:
        """This mod's free-running script, if it declares one.

        Optional here, unlike a single-mod build: a disc with three mods where
        only one loops is perfectly ordinary, and demanding `main` from the
        others would be ceremony.
        """
        names = [script.name for script in self.program.scripts]
        return ENTRY_SCRIPT if ENTRY_SCRIPT in names else ""


def _check_slugs(parts: list[ModPart]) -> None:
    """Two mods must not reduce to the same namespace.

    `hard-mode` and `hard mode` both become `hard_mode`, and the result would be
    two definitions of the same symbol -- a linker error naming a generated
    identifier nobody wrote, rather than the two mods that actually collided.
    """
    seen: dict[str, str] = {}
    for part in parts:
        slug = mod_slug(part.name)
        if slug in seen:
            raise ScriptError(
                f"mods {seen[slug]!r} and {part.name!r} both reduce to the "
                f"namespace {slug!r}, so their generated symbols would collide.\n"
                f"  Rename one of them.",
                Position(),
            )
        seen[slug] = part.name


def generate_merged(
    parts: list[ModPart],
    origin: str = "several mods",
    banner: Banner | None = None,
) -> GeneratedSource:
    """Render several mods' programs as one C translation unit.

    ⚠️ The point of the exercise: the Gecko loader opens exactly one
    `/mod/mod.rel`, but it does not care how many mods went into it. Merging at
    compile time satisfies that limit without any runtime REL chaining, which
    is the part nobody in this scene has solved (D39).

    Each mod keeps its own namespace, so two mods may both declare
    `script main`. What is emitted *once* is the shared runtime: one `_prolog`,
    one set of sequence hooks, and hook tables that are the **union** across
    mods rather than one table each.
    """
    if not parts:
        raise ScriptError("no mods to merge", Position())
    _check_slugs(parts)

    booting = [part for part in parts if part.boot_script]
    if len(booting) > 1:
        names = ", ".join(part.name for part in booting)
        raise ScriptError(
            f"{len(booting)} mods declare a boot map ({names}), but a disc "
            f"starts in one place.\n"
            f"  Keep it on one of them, or pass --map to override for a build.",
            Position(),
        )

    sections: list[str] = []
    entries: list[str] = []
    hooks: list[BoundHook] = []
    combos: list[BoundCombo] = []
    externals: list[str] = []
    boot = ""

    for part in parts:
        _check_map_hooks(part.program, part.map_hooks)
        _check_combo_hooks(part.program, part.combos)
        _check_boot_script(part.program, part.boot_script)

        sections.append(runtime_c.MOD_SECTION.format(name=part.name))
        sections.extend(_program_section(part.program, part.prefix))

        if part.entry:
            entries.append(f"{part.prefix}script_{part.entry}")
        hooks += _bind_maps(part.map_hooks, part.prefix)
        combos += _bind_combos(part.combos, part.prefix)
        if part.boot_script:
            boot = f"{part.prefix}script_{part.boot_script}"
        for name in part.program.called_symbols:
            if name not in externals:
                externals.append(name)

    head = [runtime_c.HEADER.format(origin=origin)]
    if externals:
        head.append(
            "/* Game functions called by USER_FUNC, bound by elf2rel. */\n"
            + "\n".join(f"extern void {name}(void);" for name in externals)
        )
    head.append(
        "/* Started by the game's script scheduler. */\n"
        "extern void *evtEntry(const s32 *script, u32 priority, u8 flags);"
    )
    head.append(runtime_c.MOD_HOOK)

    footer = _footer(entries, hooks, banner=banner, boot=boot, combos=combos)
    text = "\n\n".join(head + sections + [footer])
    _require_ascii(text)
    return GeneratedSource(
        text=text,
        entry_script=", ".join(entries),
        external_symbols=externals,
    )


def _require_ascii(text: str) -> None:
    """Guard the invariant that generated C is pure ASCII.

    Mods get built on Linux, macOS and Windows, whose compilers and editors do
    not agree on a default source encoding. String contents are already escaped
    byte-wise, so the only way a non-ASCII character reaches here is a comment
    template in this module -- which is a `bleck` bug, and better caught during
    generation than as a mojibake comment in someone else's build log.
    """
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:
        offending = text[exc.start : exc.end]
        raise ValueError(
            f"generated C contains non-ASCII {offending!r}; "
            "this is a bug in bleck's code templates"
        ) from exc


def _check_combo_hooks(program: CompiledProgram, hooks: list[ComboHook]) -> None:
    """Every combination's script has to exist, and be spelled the same twice.

    Same failure as a map hook: `mod.json` names a script, the source declares
    one, and nothing connects them until here. Without this the C compiler
    reports an undefined `bleck_script_wrap_home`, which says nothing about the
    manifest line that asked for it.
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


def _check_map_hooks(program: CompiledProgram, hooks: list[MapHook]) -> None:
    """Every attached script has to exist, and be named the same way twice.

    The manifest names a script; the source declares one. Nothing links the two
    until here, so a typo would otherwise reach the C compiler as an undefined
    symbol -- a message about `bleck_script_on_arrve` that says nothing about
    `mod.json`.
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


def _check_boot_script(program: CompiledProgram, name: str) -> None:
    """The boot script has to be in the program the caller compiled.

    `bleck` generates the source for it, so this failing means the generated
    text and the emitter disagree — a bug here rather than in anyone's mod. It
    is checked anyway because the alternative is an undefined C symbol, which
    surfaces as a linker error naming `bleck_script_bleck_boot` and nothing at
    all about the `--map` flag that asked for it.
    """
    if not name or any(script.name == name for script in program.scripts):
        return
    listed = ", ".join(script.name for script in program.scripts) or "none"
    raise ScriptError(
        f"boot script {name!r} is missing from the compiled program "
        f"(it declares: {listed}). This is a bug in bleck.",
        Position(),
    )


def _entry_script(program: CompiledProgram, required: bool = True) -> str:
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
