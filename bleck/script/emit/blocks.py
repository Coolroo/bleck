"""One C block at a time: a value in, a chunk of generated source out.

Split from `generate` because none of it needs the module-assembly logic.
Every function here takes scaffolding values and returns C text; `generate`
decides which blocks a module needs and joins them, and `merge` does the same
across several mods. ⚠️ **Nothing here may import `generate` back** — the
whole point of the seam is that a block does not know what surrounds it.

The templates themselves live in `runtime_c` and its `runtime_*` siblings.
This module is the arithmetic between a `Scaffolding` value and one of those
format strings: binding a script name to a C identifier, counting rows,
refusing a table that would overflow its guard word.
"""

from __future__ import annotations

from dataclasses import dataclass

from bleck.script.compiler.ir import (
    CompiledProgram,
    CompiledScript,
    Literal,
    ScriptWord,
    StringWord,
    SymbolWord,
    Word,
)
from bleck.script.emit import (
    runtime_c,
    runtime_intercept,
    runtime_patch,
    runtime_replace,
    runtime_trace,
)
from bleck.script.emit.scaffold import (
    _PREFIX,
    MAX_COMBOS,
    MAX_MAP_HOOKS,
    Banner,
    ComboHook,
    FunctionHook,
    MapHook,
    PatchKind,
    ScriptPatch,
    ScriptReplacement,
)
from bleck.script.errors import Position, ScriptError


def c_string(text: str) -> str:
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


def program_section(program: CompiledProgram, prefix: str) -> list[str]:
    """One program's strings and script arrays, under its own namespace.

    Shared by the single-mod and merged paths so both emit identical per-program
    code.
    """
    # pylint: disable=container-return  # ordered sections, joined by the caller
    parts: list[str] = []
    if program.strings:
        parts.append(
            "\n".join(
                f"static const char {prefix}string_{index}[] = {c_string(text)};"
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


def bind_maps(hooks: list[MapHook], namespace: str) -> list[BoundHook]:
    # pylint: disable=container-return
    return [
        BoundHook(map_name=h.map_name, symbol=f"{namespace}script_{h.script}")
        for h in hooks
    ]


def bind_combos(combos: list[ComboHook], namespace: str) -> list[BoundCombo]:
    # pylint: disable=container-return
    return [
        BoundCombo(name=c.name, mask=c.mask, symbol=f"{namespace}script_{c.script}")
        for c in combos
    ]


def bind_replacements(
    replacements: list[ScriptReplacement], namespace: str
) -> list[ScriptReplacement]:
    # pylint: disable=container-return
    """Resolve each swapped-in script to a C identifier in its own namespace."""
    return [
        ScriptReplacement(
            map_name=r.map_name,
            index=r.index,
            field_offset=r.field_offset,
            script=r.script,
            symbol=f"{namespace}script_{r.script}",
            expect_word=r.expect_word,
        )
        for r in replacements
    ]


def map_block(hooks: list[BoundHook], namespace: str = _PREFIX) -> str:
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
            prefix=prefix, index=index, name=c_string(hook.map_name)
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
        resolver=runtime_patch.PATCH_DOOR_RESOLVER + runtime_patch.PATCH_DOOR_VALUE,
        resolve=runtime_patch.PATCH_DOOR_RESOLVE,
        needs=(PatchKind.MAP,),
    ),
    PatchKind.NPC: _PatchKind(
        constant="BLECK_PATCH_NPC",
        resolver=runtime_patch.PATCH_NPC_RESOLVER,
        resolve=runtime_patch.PATCH_NPC_RESOLVE,
    ),
}


def patch_block(patches: list[ScriptPatch]) -> str:
    """The patch table, the guard, and the status a mod's C can read."""
    decls: list[str] = []
    seen: set[str] = set()
    for index, patch in enumerate(patches):
        decls.append(
            runtime_patch.PATCH_TARGET.format(index=index, name=c_string(patch.target))
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
        f"{patch.index}, {patch.field_offset}, {patch.at}u, 0x{patch.expect:08X}u, "
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


def replace_block(
    replacements: list[ScriptReplacement], patch_kinds: set[PatchKind]
) -> str:
    """The replacement table, its guard, and the pointer store.

    ⚠️ Emits `bleck_door_field` itself when no door *patch* already pulled it in.
    A module may replace a script without patching one, and the walk is shared:
    defining it twice would not compile.
    """
    decls = [
        runtime_replace.REPLACE_TARGET.format(index=index, name=c_string(entry.map_name))
        for index, entry in enumerate(replacements)
    ]
    # ⚠️ No `extern` for the swapped-in scripts. `program_section` has already
    # defined them earlier in this same file, and re-declaring one makes elf2rel
    # treat the mod's own script as a *game* symbol it must resolve.

    resolvers = ""
    if PatchKind.DOOR not in patch_kinds:
        if PatchKind.MAP not in patch_kinds:
            resolvers += runtime_patch.PATCH_MAP_RESOLVER
        resolvers += runtime_patch.PATCH_DOOR_RESOLVER

    rows = "".join(
        f"    {{bleck_replace_map_{index}, {entry.index}, {entry.field_offset}, "
        f"0x{entry.expect_word:08X}u, "
        f"(const void *) &{entry.symbol}}},"
        f"  /* {entry.selector} -> {entry.script} */\n"
        for index, entry in enumerate(replacements)
    )
    return resolvers + runtime_replace.REPLACE_BLOCK.format(
        count=len(replacements),
        decls="\n" + "\n".join(decls) + "\n",
        rows=rows,
        pending="".join("    BLECK_REPLACE_PENDING,\n" for _ in replacements),
        zeros="".join("    0,\n" for _ in replacements),
    )


def hook_block(hooks: list[FunctionHook]) -> str:
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


def banner_block(banner: Banner) -> str:
    return runtime_c.BANNER_BLOCK.format(
        text=c_string(banner.text),
        loader=c_string(banner.loader_text),
        flags=banner.flags,
    )


def combo_block(hooks: list[BoundCombo]) -> str:
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
