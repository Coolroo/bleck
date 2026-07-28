"""Interception: running a mod's function *around* the original, not instead.

`code.hooks` with `mode: "replace"` needs no wrapper -- the branch lands
straight on the mod's function and the original is gone. `before` and `after`
need the original to run too, and that is what this generates.

WHY ASSEMBLY. The wrapper has to pass the target's arguments through to two
different functions without knowing what they are. `bleck` resolves a hook from
a symbol *name*; nothing in the symbol list carries a signature, so a generated C
wrapper would have to guess one. Guessing `(u32, u32, u32, u32)` looks harmless
and is not: the PowerPC EABI passes floating-point arguments in f1-f8, entirely
separately from r3-r10, and a C function that never mentions a float is free to
clobber those registers. The original would then be called with corrupted
arguments -- silently, and only for functions that happen to take floats.

Assembly sidesteps the guess. It saves r3-r10 and f1-f8, calls whatever it needs
to, and puts them back exactly as they arrived, so the handler and the original
both see the arguments the caller actually passed. Nothing here interprets them.

HOW THE ORIGINAL IS REACHED. Not by a trampoline. This reuses the self-healing
detour (D96): restore the first instruction, call the function, re-install the
branch. `bleck_trace_open` / `_close` already do that, with the reentrancy and
depth accounting they were written for, so interception inherits it rather than
repeating it.

The call itself is indirect through CTR, not `bl`. A `bl` would be a 26-bit
relative branch from the module to the DOL and could be out of range; the
address comes out of the hook table instead, where it is already correct.

WHAT IT COSTS. Two cache flushes per call, plus the saves -- the same bill D96
measured for a trace, and the reason `replace` stays the default. Measure a
per-frame function against the same build untraced rather than assuming.

WHAT IT STILL CANNOT SEE. `bleck_trace_args` records the first four *integer*
arguments only, so the trace record beside an intercepted hook has the same
blind spots as any other trace. The handler is unaffected: it receives every
register untouched, so a handler declared with the real signature -- floats
included -- gets the real arguments. Only the recording is partial.

⚠️ ARGUMENTS PAST THE EIGHTH live in the caller's stack frame. The wrapper
builds its own frame, so a handler cannot reach them, and the original still
can: the wrapper never touches the caller's frame, so the stack arguments are
still where the original expects them relative to *its* caller -- which is now
the wrapper. A function taking more than eight integer arguments must not be
intercepted. This is not checked; it cannot be, without signatures.
"""

from __future__ import annotations

#: Stack frame. 16-byte aligned, with the LR save word in the caller's frame at
#: `FRAME + 4` as the EABI requires.
#:
#:   0x08..0x24  r3-r10, the incoming integer arguments
#:   0x28..0x67  f1-f8, the incoming float arguments
#:   0x68        the original's integer return value
#:   0x70        the original's float return value
#:   0x78        the original's address, read from the hook table
FRAME = 0x80

#: Save the arguments exactly as they arrived. Anything that follows is free to
#: clobber the volatile registers, because this is what restores them.
_SAVE_ARGS = """
    stw   3, 0x08(1)
    stw   4, 0x0c(1)
    stw   5, 0x10(1)
    stw   6, 0x14(1)
    stw   7, 0x18(1)
    stw   8, 0x1c(1)
    stw   9, 0x20(1)
    stw   10, 0x24(1)
    stfd  1, 0x28(1)
    stfd  2, 0x30(1)
    stfd  3, 0x38(1)
    stfd  4, 0x40(1)
    stfd  5, 0x48(1)
    stfd  6, 0x50(1)
    stfd  7, 0x58(1)
    stfd  8, 0x60(1)
"""

#: Put them back. Used before every onward call, so each callee receives the
#: caller's arguments rather than whatever the previous callee left behind.
_LOAD_ARGS = """
    lwz   3, 0x08(1)
    lwz   4, 0x0c(1)
    lwz   5, 0x10(1)
    lwz   6, 0x14(1)
    lwz   7, 0x18(1)
    lwz   8, 0x1c(1)
    lwz   9, 0x20(1)
    lwz   10, 0x24(1)
    lfd   1, 0x28(1)
    lfd   2, 0x30(1)
    lfd   3, 0x38(1)
    lfd   4, 0x40(1)
    lfd   5, 0x48(1)
    lfd   6, 0x50(1)
    lfd   7, 0x58(1)
    lfd   8, 0x60(1)
"""

#: Record the first four integer arguments, and count the call. Shifts r3-r6 up
#: into `bleck_trace_args(index, a0, a1, a2, a3)`, top down so nothing is
#: overwritten before it is read.
_RECORD_ARGS = """
    mr    7, 6
    mr    6, 5
    mr    5, 4
    mr    4, 3
    li    3, {index}
    bl    bleck_trace_args
"""

#: Call the original through the detour, leaving its return value in the frame.
#:
#: `bleck_trace_open` returns 0 when there is nothing to restore, and the
#: original MUST NOT be called then: its first instruction would still be the
#: branch back here, so the call would recurse until the stack ran out. The build
#: refuses an unguarded interception, so this path is unreachable by
#: construction -- it returns zero rather than trusting that.
_CALL_ORIGINAL = """
    li    3, {index}
    bl    bleck_trace_open
    cmpwi 3, 0
    beq   .Lblind_{index}
    li    3, {index}
    bl    bleck_hook_target
    stw   3, 0x78(1)
{load}
    lwz   0, 0x78(1)
    mtctr 0
    bctrl
    stw   3, 0x68(1)
    stfd  1, 0x70(1)
    li    3, {index}
    lwz   4, 0x68(1)
    bl    bleck_trace_result
    li    3, {index}
    bl    bleck_trace_close
    b     .Lran_{index}
.Lblind_{index}:
    li    0, 0
    stw   0, 0x68(1)
    stw   0, 0x70(1)
    stw   0, 0x74(1)
.Lran_{index}:
"""

#: Hand control to the mod's own function, with the caller's arguments restored.
#: Its return value is discarded -- the original's is what propagates, so a
#: `before` handler cannot accidentally change what the caller receives.
_CALL_HANDLER = """
{load}
    bl    {call}
"""

_WRAPPER = """
    .section .text.{name}, "ax", @progbits
    .globl {name}
    .type {name}, @function
    .align 2
{name}:
    mflr  0
    stwu  1, -0x80(1)
    stw   0, 0x84(1)
{save}{record}{body}
    lwz   3, 0x68(1)
    lfd   1, 0x70(1)
    lwz   0, 0x84(1)
    mtlr  0
    addi  1, 1, 0x80
    blr
    .size {name}, .-{name}
"""

#: What a mod's C may call, and what the wrappers branch to. Declared here so the
#: hook table can name a wrapper the same way it names any other function.
INTERCEPT_DECLS = """
/*
    The address of a hooked function, straight out of the hook table. The
    wrappers call the original through this rather than through a `bl`, which
    would be a 26-bit relative branch and could be out of range.
*/
void *bleck_hook_target(u32 index)
{{
    if (index >= BLECK_HOOK_COUNT)
        return 0;
    return bleck_function_hooks[index].at;
}}
"""


def wrapper_name(index: int) -> str:
    """The symbol the hook table branches to for an intercepting hook."""
    return f"bleck_hook_wrap_{index}"


def wrapper(index: int, call: str, mode: str) -> str:
    """One wrapper's assembly, as a top-level `asm` block for the generated C.

    `before` runs the mod's function first and the original second; `after` is
    the same two calls in the other order. Both return the *original's* value.
    """
    load = _LOAD_ARGS.rstrip("\n")
    handler = _CALL_HANDLER.format(load=load, call=call)
    original = _CALL_ORIGINAL.format(index=index, load=load)
    body = handler + original if mode == "before" else original + handler
    text = _WRAPPER.format(
        name=wrapper_name(index),
        save=_SAVE_ARGS,
        record=_RECORD_ARGS.format(index=index),
        body=body,
    )
    return _as_c_asm(text, index, call, mode)


def _as_c_asm(text: str, index: int, call: str, mode: str) -> str:
    """Wrap assembly lines as a C `asm()` statement, one string literal a line.

    Kept in the generated `mod.c` rather than a separate `.S` so a build still
    produces one readable artifact -- the file a user is told to open when a hook
    misbehaves.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    quoted = "\n".join(f'    "{line}\\n"' for line in (_escape(x) for x in lines))
    return (
        f"/* {wrapper_name(index)}: {mode} -> {call}, hook {index}. "
        f"Saves r3-r10 and f1-f8 so both callees see the caller's arguments. */\n"
        f"asm(\n{quoted}\n);\n"
    )


def _escape(line: str) -> str:
    return line.replace("\\", "\\\\").replace('"', '\\"')
