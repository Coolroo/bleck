---
title: Tracing a game function without a trampoline
description: A self-healing detour records arguments and return values while the original still runs, works on functions a trampoline cannot relocate, and has a specific list of blind spots
---

# Tracing a function without a trampoline

Replacing a function is easy and destroys it. Watching one — arguments, return
value, call count — while it still works normally usually means a **trampoline**:
relocate the displaced instruction somewhere else and branch back. Relocation is
where trampolines go wrong.

There is a simpler mechanism that needs no relocation at all, and it is the one
every measurement in [undocumented functions](undocumented-functions.md) was
taken with.

## The self-healing detour

Per call, inside your own handler:

1. record the arguments;
2. **restore** the original first instruction (store + cache flush);
3. call the function through its own symbol — now unpatched, so control reaches
   the real body instead of coming straight back;
4. **re-install** the branch (store + flush);
5. record the return value and hand it to the caller.

The word restored in step 2 is the one read out of the unmodified `main.dol` at
build time, so nothing is re-derived at run time and a hook with no known
original word cannot be traced at all.

```c
void *traceMapDataPtr(const char *mapName)
{
    void *result = 0;

    trace_args(0, (u32) mapName, 0, 0, 0);
    if (trace_open(0))                  /* restores the original word */
    {
        result = mapDataPtr(mapName);   /* unpatched right now */
        trace_close(0);                 /* re-installs the branch */
    }
    trace_result(0, (u32) result);
    return result;
}
```

## ✅ Why "no relocation" is the point

A trampoline has to copy the displaced instruction elsewhere, which breaks on
any function whose first instruction is PC-relative. That is not hypothetical in
this game: `func_800cd554`'s first word is `4BFF480C` = `b 0x800C1D60`, an
alternate entry point to `effSmallStarEntry`. A copied branch would jump to the
wrong place. ✅ Here it was hooked, restored and re-armed with no special
handling, because the word goes back exactly where it belongs.

⚠️ The known-broken shape is worth naming since people copy it:
`spm-rel-loader`'s `rel/include/patch.h` provides a `hookFunction` trampoline
that copies `instruction[0]` blindly, so it breaks on exactly this case and
leaks its trampoline. Read from the source, not measured. ⚠️ The same helper is
shared across several scene mods, and **two mods hooking the same function with
it silently clobber each other** — the hard part of multi-mod support, and
unaddressed as of our survey (2026-07).

## Reentrancy — safe by ordering, not by skipping

`trace_open` **restores before it counts**. The only window in which a second
entry can reach the handler at all is between the branch being live and the
restore landing; a second entry in that window writes the same word again, and
the store is idempotent. `trace_close` re-arms only when the nesting depth
returns to zero, so an inner frame cannot re-arm underneath an outer one.

⛔ **"Skip the trace when already inside" cannot work**, which is the obvious
design. Skipping still has to *return* something, and the handler cannot produce
the original's return value without calling it — and calling it with the branch
installed recurses until the stack runs out.

⚠️ While the detour is open the function is **not** hooked, so a call it makes to
itself runs the original directly and is not counted. A recursive function's
call count is its outermost calls only.

⚠️ Report the depth at rest. If a traced function never returns — a longjmp, a
frozen frame — `close` never runs, the branch is never re-installed, and the
call counter silently stops climbing. A non-zero depth means the transcript
cannot be trusted. It read 0 on every hook of every run here.

🔶 **Not atomic.** The depth is a plain word, so two threads entering the same
handler could interleave. The worst outcome available is a window with the
branch absent — undercounting — because both writes put back one of two valid
words. Nothing was observed; nothing was proven.

## ⚠️ What a trace cannot see

This list is the useful part, because every item on it produces a
plausible-looking number rather than an error:

- **Float arguments.** The EABI passes the first eight integer or pointer
  arguments in r3–r10 and floats separately in f1–f8. A word-based recorder
  never sees them. **Never write a float argument down as `0`.**
- 🔶 Floats nonetheless *survive* the detour, by construction rather than by
  care: f1–f8 are assigned independently, and a handler containing no
  floating-point code never writes them. Inferred from the ABI and from the
  handler compiling to no FPR use; not separately measured.
- **Float and struct returns.** Only r3 is recorded. A float return is in f1; a
  struct returned by value is not in a register at all.
- **Arguments past the eighth**, which sit on the caller's stack — the handler
  builds its own frame before forwarding.
- ⛔ **Variadic functions.** The EABI uses CR bit 6 to signal whether float
  arguments were passed, and a non-variadic handler clears it.
- ⚠️ **Registers are not arguments.** A handler declared with eight `u32`s
  records eight words whatever the function's real arity is. `effMain` takes
  none, and all four of its recorded "arguments" read `8050A128` — residue, not
  data — while its recorded "return value" is residue too, and drifts.
- ⚠️ **A captured pointer is dereferenced later, not at the call.** If you
  record a `char *` and print it after the run, you get whatever that buffer
  holds *now*. Copy the bytes at call time — see
  [`mapDataPtr`](undocumented-functions.md), where every caller passes the same
  buffer.
- ⚠️ **The handler's prototype must match the traced function exactly**, because
  it forwards the call. A mismatch corrupts the call rather than merely
  mis-recording it, and a symbol list has no signatures to check against.

## 🔶 Cost, and it is a Dolphin number

Each handler bracketed the detour with `mftb`, so the flush pair is timed apart
from the traced body:

| traced function | calls | ticks per open+close | ticks in the original |
|---|---|---|---|
| `mapDataPtr` | 19 | **6.7** | 792 |
| `effMain` | 28,635 | **9.0** | 791 |
| `GetBasicPlayer` | 24,406 | **10.4** | **0** |

So roughly 7–10 time-base ticks per call — ~110–170 ns if the Wii's 60.75 MHz
time base is what is being counted. That is **1.1%** against `effMain`, and
**unbounded** against a leaf like `GetBasicPlayer`, whose entire body is one
`addi` and a `blr` and measures zero. No frame-rate change was visible in any
run; 26,996 gameplay frames ran with two hooks installed.

🔶 These are Dolphin's cycle accounting, not hardware. Two `sync` instructions
costing ~9 ticks is not credible on a real 750, which has to drain its pipeline.
The *shape* — fixed cost, small against a real function, unbounded against a
leaf — should hold; the number will not.

*(Sources: bleck decision log D96, D97.)*
