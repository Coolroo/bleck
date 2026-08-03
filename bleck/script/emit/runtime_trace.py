"""The trace runtime: watching a hooked function instead of replacing it.

Held apart from `runtime_c` because it is an instrument rather than part of the
base runtime -- nothing in a mod's manifest asks for it, and `--gc-sections`
drops every byte of it unless a mod's own C calls in. `blocks.hook_block`
emits it straight after the hook table, which is where the derived guard word it
restores already lives (D96).

Templates are `str.format` patterns, so literal braces are doubled and the
output must be pure ASCII.
"""

from __future__ import annotations

#: The self-healing detour: watching a hooked function instead of replacing it.
#: Emitted straight after `HOOK_BLOCK`, so it exists only where hooks do, and
#: `--gc-sections` drops every byte of it for a mod that only replaces.
TRACE_BLOCK = """
/*
    Tracing a hooked function.

    A hook *replaces*, so a handler can record the arguments but never the
    return value, and disables the very function it is trying to study. A trace
    sidesteps that without a trampoline:

      1. record the arguments;
      2. RESTORE the original first instruction (write + flush);
      3. call the function through its own symbol -- now unpatched, so control
         reaches the real body instead of coming straight back here;
      4. RE-INSTALL the branch (write + flush);
      5. record the return value and hand it to the caller.

    Step 2 puts back the word bleck read out of the base disc's `main.dol` at
    build time -- the same derived guard `bleck_install_hooks` compared against.
    Nothing is re-derived at run time, and a hook with no derived guard cannot
    be traced: `bleck_trace_open` returns 0 rather than inventing a word.

    WHAT A TRACE CANNOT SEE

    FLOAT ARGUMENTS. The PowerPC EABI passes the first eight integer or pointer
    arguments in r3-r10 and floating-point ones separately in f1-f8.
    `bleck_trace_args` takes words, so a float argument is never recorded.
    WORSE: the handler's own prototype must still match the traced function
    exactly. Declaring `(u32, u32)` for a function taking `(int, float)` does
    not merely lose the float -- the handler then forwards garbage to the
    original. Declare the real signature; record what fits.

    FLOAT AND STRUCT RETURNS. `bleck_trace_result` records r3. A float return
    comes back in f1 and a struct returned by value is not in a register at all,
    so both read as whatever r3 happened to hold.

    ARGUMENTS PAST THE EIGHTH. Those are on the stack, relative to the caller's
    frame. The handler builds its own frame before forwarding, so they do not
    survive. A function with more than eight integer arguments must not be
    traced this way.

    NESTED CALLS. While the detour is open the branch is not installed, so a
    call the traced function makes to itself runs the original directly and is
    not counted. A recursive function's `calls` is its outermost calls only.

    REENTRANCY. `bleck_trace_open` restores *before* it counts, so the only
    window in which a second entry can reach the handler at all is between the
    branch being live and that restore landing. A second entry there writes the
    same word again -- the store is idempotent -- and `bleck_trace_close`
    re-installs the branch only when the depth returns to zero, so an inner
    frame cannot re-arm it underneath an outer one. Skipping the trace when
    already inside is NOT the fallback, because the handler would then have to
    invent a return value; nesting is made safe instead, and counted.

    `depth` is reported for the failure that safety cannot cover: if a traced
    function never returns -- a longjmp, a frozen frame -- `close` never runs,
    the branch is never re-installed and `calls` silently stops climbing. A
    non-zero `depth` at rest means the transcript is not to be trusted.

    COST. Two cache flushes per call, each `dcbst`/`sync`/`icbi`/`isync`. Cheap
    beside a map load and not obviously cheap beside a per-frame function --
    measure it against the same build untraced rather than assuming.

    A mod's own C uses it by declaring:

        extern void bleck_trace_args(u32 index, u32 a0, u32 a1, u32 a2, u32 a3);
        extern u32 bleck_trace_open(u32 index);
        extern void bleck_trace_close(u32 index);
        extern void bleck_trace_result(u32 index, u32 value);
        extern u32 bleck_hook_original(u32 index);

    and repeating the BleckTrace layout below, exactly as probes repeat SeqDef.
*/

#define BLECK_TRACE_ARGS 4
#define BLECK_TRACE_MAGIC 0xB1EC7ACEu

typedef struct
{{
    u32 magic;
    u32 calls;
    u32 nested;
    u32 blind;
    u32 depth;
    u32 first[BLECK_TRACE_ARGS];
    u32 last[BLECK_TRACE_ARGS];
    u32 firstResult;
    u32 lastResult;
}} BleckTrace;

/*
    Not static: a mod's own C reads the record. `magic` is non-zero so the array
    lands in .data -- the loader allocates this module's bss but does not
    document zeroing it, and a trace starting from garbage would read as a
    finding.
*/
BleckTrace bleck_traces[BLECK_HOOK_COUNT] = {{
{traces}}};

void bleck_trace_args(u32 index, u32 a0, u32 a1, u32 a2, u32 a3)
{{
    BleckTrace *trace;

    if (index >= BLECK_HOOK_COUNT)
        return;
    trace = &bleck_traces[index];
    if (trace->calls == 0)
    {{
        trace->first[0] = a0;
        trace->first[1] = a1;
        trace->first[2] = a2;
        trace->first[3] = a3;
    }}
    trace->last[0] = a0;
    trace->last[1] = a1;
    trace->last[2] = a2;
    trace->last[3] = a3;
    trace->calls += 1;
}}

void bleck_trace_result(u32 index, u32 value)
{{
    BleckTrace *trace;

    if (index >= BLECK_HOOK_COUNT)
        return;
    trace = &bleck_traces[index];
    if (trace->calls <= 1)
        trace->firstResult = value;
    trace->lastResult = value;
}}

/*
    Open the detour. Returns 1 when the original may be called and the caller
    must close it again, 0 when there is nothing to restore -- an unguarded
    hook, or one that never installed.

    A 0 means the original MUST NOT be called: its first instruction is still
    the branch back here, so calling it would recurse until the stack ran out.
*/
u32 bleck_trace_open(u32 index)
{{
    const BleckFunctionHook *hook;
    BleckTrace *trace;

    if (index >= BLECK_HOOK_COUNT)
        return 0;
    hook = &bleck_function_hooks[index];
    trace = &bleck_traces[index];
    if (!hook->guarded || bleck_hook_status[index] != BLECK_HOOK_INSTALLED)
    {{
        trace->blind += 1;
        return 0;
    }}
    if (trace->depth != 0)
        trace->nested += 1;
    /* Restore, then count. The order is the reentrancy argument above. */
    bleck_code_write(hook->at, hook->expect);
    trace->depth += 1;
    return 1;
}}

/* Re-arm the branch, once the outermost frame is done with the original. */
void bleck_trace_close(u32 index)
{{
    BleckTrace *trace;

    if (index >= BLECK_HOOK_COUNT)
        return;
    trace = &bleck_traces[index];
    if (trace->depth != 0)
        trace->depth -= 1;
    if (trace->depth == 0)
        bleck_code_hook(bleck_function_hooks[index].at,
                        bleck_function_hooks[index].call);
}}

/* The word bleck read at the function's entry, or 0 where it derived none. */
u32 bleck_hook_original(u32 index)
{{
    if (index >= BLECK_HOOK_COUNT || !bleck_function_hooks[index].guarded)
        return 0;
    return bleck_function_hooks[index].expect;
}}
"""

#: One trace record's initial state. `magic` keeps the array out of .bss.
TRACE_ROW = "    {BLECK_TRACE_MAGIC, 0, 0, 0, 0, {0, 0, 0, 0}, {0, 0, 0, 0}, 0, 0},\n"
