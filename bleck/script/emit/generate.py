"""Writing compiled scripts out as C, for the existing REL toolchain to build.

Game functions are declared `extern` and bound by `elf2rel` at REL-build time,
so `bleck` never writes a game address and ships no symbol list.
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
from bleck.script.emit import runtime_c, runtime_intercept, runtime_patch, runtime_trace

# Re-exported as `emit.MapHook` and friends.
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
    FunctionHook,
    MapHook,
    PatchKind,
    Scaffolding,
    ScriptPatch,
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

    Non-ASCII is escaped byte-wise from UTF-8 so the generated file stays pure
    ASCII and cannot be re-encoded by an editor.
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
            # Octal, not hex: a C hex escape swallows every following hex
            # digit, while octal is capped at three.
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
    # Four per line, so a bytecode change diffs to a small region.
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

    A merged module's hook table is a union across mods, so each row's symbol
    is resolved in its own namespace before the table is built.
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


@dataclass(frozen=True)
class _PatchKind:
    """What one selector kind contributes to the generated patch block."""

    constant: str
    resolver: str
    """The lookup helper, emitted once when any patch uses this kind."""

    resolve: str
    """The lines inside `bleck_apply_patches` that call it."""

    needs: tuple[PatchKind, ...] = ()
    """Other kinds whose resolver this one calls.

    `door` walks a map's init script, so it uses `bleck_map_init_script`. Without
    this a door-only module would emit a call to a helper it never defined.
    """


#: What each selector kind contributes to the generated C. Keyed by the enum, so
#: a new member that nobody wired up here is a `KeyError` at the one line that
#: uses it rather than a hand-written "this is a bug in bleck" branch.
_PATCH_KINDS = {
    PatchKind.MAP: _PatchKind(
        constant="BLECK_PATCH_MAP",
        resolver=runtime_patch.PATCH_MAP_RESOLVER,
        resolve=runtime_patch.PATCH_MAP_RESOLVE,
    ),
    PatchKind.ITEM: _PatchKind(
        constant="BLECK_PATCH_ITEM",
        resolver=runtime_patch.PATCH_ITEM_RESOLVER,
        resolve=runtime_patch.PATCH_ITEM_RESOLVE,
    ),
    PatchKind.DOOR: _PatchKind(
        constant="BLECK_PATCH_DOOR",
        resolver=runtime_patch.PATCH_DOOR_RESOLVER,
        resolve=runtime_patch.PATCH_DOOR_RESOLVE,
        needs=(PatchKind.MAP,),
    ),
}


def _patch_block(patches: list[ScriptPatch]) -> str:
    """The patch table, the guard, and the status a mod's C can read."""
    decls: list[str] = []
    seen: set[str] = set()
    for index, patch in enumerate(patches):
        decls.append(
            runtime_patch.PATCH_TARGET.format(index=index, name=_c_string(patch.target))
        )
    for patch in patches:
        if patch.call not in seen:
            seen.add(patch.call)
            decls.append(runtime_patch.PATCH_CALL.format(name=patch.call))

    # Only the kinds actually used, so an item-only module never references
    # `mapDataPtr` and vice versa. Declaration order stays stable.
    wanted = {p.kind for p in patches}
    for kind in list(wanted):
        wanted.update(_PATCH_KINDS[kind].needs)
    used = [kind for kind in _PATCH_KINDS if kind in wanted]
    rows = "".join(
        f"    {{{_PATCH_KINDS[patch.kind].constant}, bleck_patch_target_{index}, "
        f"{patch.index}, {patch.door_offset}, {patch.at}u, 0x{patch.expect:08X}u, "
        f"(const void *) &{patch.call}}},"
        f"  {patch.comment}\n"
        for index, patch in enumerate(patches)
    )
    return runtime_patch.PATCH_BLOCK.format(
        count=len(patches),
        decls="\n" + "\n".join(decls) + "\n",
        rows=rows,
        pending="".join("    BLECK_PATCH_PENDING,\n" for _ in patches),
        uncounted="".join("    BLECK_PATCH_UNCOUNTED,\n" for _ in patches),
        resolvers="".join(_PATCH_KINDS[name].resolver for name in used),
        resolve="".join(_PATCH_KINDS[name].resolve for name in used),
    )


def _hook_block(hooks: list[FunctionHook]) -> str:
    """The hook table, its derived guards, and the status a mod's C can read."""
    decls: list[str] = []
    seen: set[str] = set()
    for hook in hooks:
        for name, template in (
            (hook.symbol, runtime_c.HOOK_TARGET),
            (hook.call, runtime_c.HOOK_CALL),
        ):
            if name and name not in seen:
                seen.add(name)
                decls.append(template.format(name=name))

    # An intercepting hook branches to a generated wrapper, which calls both the
    # mod's function and the original. `replace` keeps branching straight at the
    # mod's function, so its output is unchanged.
    for index, hook in enumerate(hooks):
        if hook.intercepts:
            decls.append(
                runtime_c.HOOK_CALL.format(name=runtime_intercept.wrapper_name(index))
            )

    rows = "".join(
        f"    {{{_hook_address(hook)}, 0x{hook.expect:08X}u, "
        f"{1 if hook.guarded else 0}u, (const void *) &{_hook_branch(index, hook)}}},"
        f"  {hook.comment}\n"
        for index, hook in enumerate(hooks)
    )
    block = runtime_c.HOOK_BLOCK.format(
        count=len(hooks),
        decls="\n" + "\n".join(decls) + "\n",
        rows=rows,
        pending="".join("    BLECK_HOOK_PENDING,\n" for _ in hooks),
    )
    # Emitted unconditionally beside the table: a trace needs the derived guard
    # word that is already there, and `--gc-sections` drops the lot for a mod
    # that only replaces. Nothing declares a trace, so nothing can ask for it.
    block += runtime_trace.TRACE_BLOCK.format(
        traces="".join(runtime_trace.TRACE_ROW for _ in hooks)
    )
    wrappers = [
        runtime_intercept.wrapper(index, hook.call, hook.mode)
        for index, hook in enumerate(hooks)
        if hook.intercepts
    ]
    if not wrappers:
        return block
    return block + runtime_intercept.INTERCEPT_DECLS.format() + "\n" + "\n".join(wrappers)


def _hook_branch(index: int, hook: FunctionHook) -> str:
    """What the game's first instruction actually branches to."""
    return runtime_intercept.wrapper_name(index) if hook.intercepts else hook.call


def _hook_address(hook: FunctionHook) -> str:
    """Where the branch goes: the symbol if there is one, else the address.

    A named function is left to `elf2rel`, so the symbol list stays the single
    source of truth for addresses even though the guard beside it is baked.
    """
    if hook.symbol:
        return f"(void *) &{hook.symbol}"
    return f"(void *) 0x{hook.address:08X}u"


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

    Emitted as source and run through the ordinary compiler, so it gets the same
    string table and symbol-table checks as any other script. `map_name` is
    validated against the game's map list upstream, so it needs no escaping.
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


@dataclass(frozen=True)
class Runtime:
    """The shared runtime block's contents, resolved to C identifiers.

    One value rather than a handful of arguments, because all three `generate*`
    entry points fill in the same set.
    """

    banner: Banner | None = None
    boot: str = ""
    """The boot script's C identifier, if the module has one."""

    combos: list[BoundCombo] = field(default_factory=list)
    namespace: str = _PREFIX
    run_cxx_ctors: bool = False
    """Whether `_prolog` walks `.ctors`. See `runtime_c.CTOR_BLOCK`."""

    patches: list[ScriptPatch] = field(default_factory=list)
    """In-place edits to the game's own scripts, applied from `_prolog`."""

    function_hooks: list[FunctionHook] = field(default_factory=list)
    """Game functions branch-replaced by the mod's own, from `_prolog`."""


def _footer(entries: list[str], hooks: list[BoundHook], runtime: Runtime) -> str:
    """Assemble the shared runtime, from the pieces the module needs.

    Emitted **once** however many mods contributed: a second `_prolog` would be
    a second set of installs fighting over `seq_data`. Everything that needs a
    per-frame hook shares the one set installed here.
    """
    banner, boot, combos = runtime.banner, runtime.boot, list(runtime.combos)
    patches = list(runtime.patches)
    functions = list(runtime.function_hooks)
    # Before `mod_prolog`, so a mod's own C can read `bleck_patch_status[]`.
    apply_patches = "    bleck_apply_patches();\n" if patches else ""
    install_hooks = "    bleck_install_hooks();\n" if functions else ""
    run_ctors = "    bleck_run_ctors();\n" if runtime.run_cxx_ctors else ""

    if not entries and not hooks and banner is None and not boot and not combos:
        if not runtime.run_cxx_ctors and not patches and not functions:
            return runtime_c.PLAIN_PROLOG + runtime_c.ENTRY_POINTS
        head = runtime_c.CTOR_BLOCK if runtime.run_cxx_ctors else ""
        head += _patch_block(patches) if patches else ""
        head += _hook_block(functions) if functions else ""
        return (
            head + f"\nvoid _prolog(void)\n{{\n{run_ctors}{apply_patches}"
            f"{install_hooks}    mod_prolog();\n}}\n" + runtime_c.ENTRY_POINTS
        )

    parts = [runtime_c.SEQ_TABLE]
    body = ""
    if runtime.run_cxx_ctors:
        parts.append(runtime_c.CTOR_BLOCK)
    if patches:
        parts.append(_patch_block(patches))
    if functions:
        parts.append(_hook_block(functions))

    if banner is not None:
        parts.append(_banner_block(banner))
        body += "    if (bleck_banner_on[seq])\n        bleck_draw_banner();\n"
    if hooks:
        parts.append(_map_block(hooks, runtime.namespace))
        body += "    bleck_maps_on_seq(seq);\n"
    if combos:
        parts.append(_combo_block(combos))
        body += "    bleck_combos_on_seq(seq);\n"
    if len(entries) == 1:
        # The single-mod form.
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
    # Last: the boot script tears the world down a couple of seconds later, so
    # everything else due this frame must have run first.
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
    # Constructors run before `mod_prolog`, as statics do before `main`.
    parts.append(
        f"\nvoid _prolog(void)\n{{\n{runtime_c.SEQ_INSTALL}"
        f"{run_ctors}{apply_patches}{install_hooks}    mod_prolog();\n}}\n"
    )
    parts.append(runtime_c.ENTRY_POINTS)
    return "".join(parts)


def _program_section(program: CompiledProgram, prefix: str) -> list[str]:
    """One program's strings and script arrays, under its own namespace.

    Shared by the single-mod and merged paths so both emit identical per-program
    code.
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
        # Scripts may spawn each other in any order, so declare all first.
        parts.append(
            "\n".join(
                f"extern const s32 {prefix}script_{script.name}[];"
                for script in program.scripts
            )
        )
    parts.extend(_script_array(script, prefix) for script in program.scripts)
    return parts


def generate_bare(
    origin: str = "native sources",
    banner: Banner | None = None,
    run_cxx_ctors: bool = False,
    patches: list[ScriptPatch] | None = None,
    function_hooks: list[FunctionHook] | None = None,
) -> GeneratedSource:
    """Scaffolding for a mod that ships only native sources.

    The REL format still needs its three entry points; there is just no script
    to schedule.
    """
    text = (
        runtime_c.HEADER.format(origin=origin)
        + "\n"
        + runtime_c.MOD_HOOK
        + "\n"
        + runtime_c.CODE_PATCH
        + _footer(
            [],
            [],
            Runtime(
                banner=banner,
                run_cxx_ctors=run_cxx_ctors,
                patches=list(patches or []),
                function_hooks=list(function_hooks or []),
            ),
        )
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
    parts.append(runtime_c.CODE_PATCH)

    parts.extend(_program_section(program, plan.prefix))
    parts.append(
        _footer(
            [f"{plan.prefix}script_{entry}"] if entry else [],
            _bind_maps(hooks, plan.prefix),
            Runtime(
                banner=plan.banner,
                boot=(
                    f"{plan.prefix}script_{plan.boot_script}" if plan.boot_script else ""
                ),
                combos=_bind_combos(plan.combos, plan.prefix),
                namespace=plan.prefix,
                run_cxx_ctors=plan.run_cxx_ctors,
                patches=list(plan.patches),
                function_hooks=list(plan.function_hooks),
            ),
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
        """This mod's free-running script, if it declares one. Optional here,
        unlike a single-mod build."""
        names = [script.name for script in self.program.scripts]
        return ENTRY_SCRIPT if ENTRY_SCRIPT in names else ""


def _check_slugs(parts: list[ModPart]) -> None:
    """Two mods must not reduce to the same namespace.

    `hard-mode` and `hard mode` both become `hard_mode`, which would otherwise
    surface as a linker error naming a generated identifier nobody wrote.
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
    *,
    banner: Banner | None = None,
    run_cxx_ctors: bool = False,
    patches: list[ScriptPatch] | None = None,
    function_hooks: list[FunctionHook] | None = None,
) -> GeneratedSource:
    """Render several mods' programs as one C translation unit.

    The loader opens exactly one `/mod/mod.rel`, so merging happens at compile
    time rather than via runtime REL chaining (D39). Each mod keeps its own
    namespace; the shared runtime is emitted once, with hook tables that are the
    **union** across mods.

    `patches` is that union already: a patch names C functions rather than
    compiled scripts, so it needs no namespace and is passed whole.
    """
    if not parts:
        raise ScriptError("no mods to merge", Position())
    _check_slugs(parts)

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
    head.append(runtime_c.CODE_PATCH)

    runtime = Runtime(
        banner=banner,
        boot=boot,
        combos=combos,
        run_cxx_ctors=run_cxx_ctors,
        patches=list(patches or []),
        function_hooks=list(function_hooks or []),
    )
    text = "\n\n".join(head + sections + [_footer(entries, hooks, runtime)])
    _require_ascii(text)
    return GeneratedSource(
        text=text,
        entry_script=", ".join(entries),
        external_symbols=externals,
    )


def _require_ascii(text: str) -> None:
    """Guard the invariant that generated C is pure ASCII.

    Linux, macOS and Windows toolchains disagree on default source encoding.
    String contents are already escaped byte-wise, so a failure here means a
    non-ASCII comment template in this module -- a `bleck` bug.
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


def _check_map_hooks(program: CompiledProgram, hooks: list[MapHook]) -> None:
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


def _check_boot_script(program: CompiledProgram, name: str) -> None:
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
