---
name: reading-the-game-live
description: Use when a question about the running game needs a value out of it — what a function is passed, what it returns, how often it is called, whether a code path is reached at all. Covers code.hooks (replace/before/after), the self-healing detour, the trace helpers, and the six things a trace physically cannot see.
---

# Reading the game live

The instrument is: a hook writes into a fixed RAM block, `scripts/ingame.py`
reads it back. This skill is the **hook** half — see `ingame-testing` for the
rig and the probe block, and `hunting-a-hang` for the assert special case.

Findings about what a function actually does go in **`docs/function-behaviour.md`**.

## Declaring a hook

```json
"code": {
  "sources": ["src"], "target": "eu0", "module_id": 2,
  "hooks": [
    { "function": "npcDispMain",    "call": "count_npcs",        "mode": "replace" },
    { "function": "mapDataPtr",     "call": "beforeMapDataPtr",  "mode": "before"  },
    { "function": "GetBasicPlayer", "call": "afterGetBasicPlayer","mode": "after"  }
  ]
}
```

- **`function`** — a symbol name resolved against the target's list **at build
  time**, or a raw address (`"0x801adef0"`). Name it: a rename or a wrong
  `target` then fails the build instead of branching into unrelated code.
- **`call`** — a function in the mod's own sources, checked against what those
  sources define, so a typo is caught before `elf2rel` calls it a missing *game*
  symbol.
- **`mode`** — all three work (D96, D97).

⚠️ A hook may instead be tagged in the source with `BLECK_HOOK(function, mode)`
above the function it names (D178). The two forms may not both claim one game
function; `bleck` refuses rather than picking a winner.

## Which mode

| mode | what happens | returns |
|---|---|---|
| `replace` | ⚠️ **the original never runs again this session** — your function is the whole implementation | yours |
| `before` | your function, then the original | **the original's** |
| `after` | the original, then your function | **the original's** |

`replace` is written out rather than defaulted to on purpose. Reaching for
`before` because you want the original to keep working is exactly the case that
must not silently get `replace`. A `replace` on `npcDispMain` stops NPCs being
drawn; on anything a sequence waits for, it stops the sequence.

`before`/`after` emit a **PowerPC assembly wrapper** per hook. Assembly, not C,
because nothing in the symbol list carries a signature: a C wrapper would have
to guess one, and ⛔ guessing `(u32,u32,u32,u32)` is not a near miss — the EABI
passes floats in `f1`–`f8` entirely separately from `r3`–`r10`, so a C wrapper
that never mentions a float would silently corrupt the original's arguments for
exactly the functions that take floats (D97). The wrapper saves `r3-r10` and
`f1-f8`, calls through `CTR` (a `bl` from the module to the DOL can be out of
26-bit range), and puts them back.

## The guard, and the statuses

`bleck` reads the instruction word at the target out of the base `main.dol` at
build time and generates it into a runtime guard. At install, the word there
must match or **nothing is written**.

```c
extern unsigned int bleck_hook_status[];   /* one per declared hook */
extern const unsigned int bleck_hook_count;
```

| status | meaning |
|---|---|
| 1 | pending — `bleck_install_hooks` has not run |
| 2 | installed |
| 3 | refused: the word there is not what the build read |
| 4 | misaligned |
| 5 | out of range — the branch cannot be encoded |

Hooks install from `_prolog`, **before** `mod_prolog`, so the mod's own C reads
a final answer. **Put the status into a probe word.** A wrong address costs a
status, not a corrupt branch — but only if you look.

⚠️ An address the DOL does not map (a REL address) gets `guarded = 0` and
installs unguarded under `replace`, with a build warning. Under `before`/`after`
it is a build **error**: the detour restores the guard word to reach the
original, and with nothing to restore it would recurse until the stack ran out.

## Tracing by hand, when the instrument is the point

`example-mods/fn-trace-probe` (D96). Five helpers are emitted beside the hook
table and dropped by `--gc-sections` unless called:

```c
extern void bleck_trace_args(u32 index, u32 a0, u32 a1, u32 a2, u32 a3);
extern u32  bleck_trace_open(u32 index);      /* 0 = do NOT call the original */
extern void bleck_trace_close(u32 index);
extern void bleck_trace_result(u32 index, u32 value);
extern u32  bleck_hook_original(u32 index);   /* the derived guard word */
extern BleckTrace bleck_traces[];  /* calls, nested, blind, depth, first[4],
                                      last[4], results */
```

```c
void *traceMapDataPtr(const char *mapName)
{
    void *result = 0;

    bleck_trace_args(0, (u32) mapName, 0, 0, 0);
    if (bleck_trace_open(0))
    {
        result = mapDataPtr(mapName);   /* unpatched right now */
        bleck_trace_close(0);
    }
    bleck_trace_result(0, (u32) result);
    return result;
}
```

`example-mods/intercept-probe` is the declared equivalent, and was built to tell
the two modes *apart* rather than merely show a hook installing — the
discriminator is that `lastResult` holds the *previous* call's value under
`before` and *this* call's under `after`.

⚠️ `depth` should be 0 at rest. A non-zero one means a frame never returned, the
branch was never re-installed, and the counts stopped climbing silently.

## ⛔ What a trace physically cannot see

- ⚠️ **The handler's prototype must match the target exactly**, and **nothing
  can check this** — a symbol list has no signatures. A mismatch corrupts the
  call, not just the record. The wrapper protects the *original* (every register
  is restored from the frame first); the handler still reads whatever it
  declared.
- **Float arguments.** They arrive in `f1`–`f8` and reach a handler correctly,
  but `bleck_trace_args` takes words, so they are **invisible to the record**.
- **Float and struct returns.** Only `r3` is recorded.
- ⛔ **More than eight integer arguments cannot be intercepted at all** — they
  sit in the caller's frame and the wrapper builds its own.
- ⛔ **Variadic functions.** CR bit 6 carries "were float arguments passed", and
  a non-variadic handler clears it.
- ⚠️ **Registers are not arguments.** A handler declared with eight `u32`s
  records eight words whatever the function's arity is. `effMain` takes none and
  all four of its recorded arguments read the same residue value.
- ⚠️ **A captured pointer is dereferenced later, not at the call.** Copy the
  bytes at call time if a specific call's string matters.

## Patching an instruction directly

```c
extern void bleck_code_store(void *at, u32 word);   /* store, NO flush */
extern void bleck_code_flush(void *at);             /* dcbst/sync/icbi/isync */
extern void bleck_code_write(void *at, u32 word);   /* store then flush */
extern s32  bleck_code_branch(const void *from, const void *to, u32 *out);
extern s32  bleck_code_hook(void *at, const void *to);
```

⚠️ **The flush is not optional and its absence is invisible.** A store lands in
the data cache; the instruction fetcher reads through the instruction cache. Two
identical patches differing only in the flush (D94) both read back `48000008` at
the patched address — and only the flushed one changed what the function
returned. Use `bleck_code_write` / `bleck_code_hook`; `bleck_code_store` exists
so that experiment can be repeated.

An out-of-range branch is **refused** (`2`), not masked, and writes nothing.

🔶 Every cache-flush result here is **Dolphin's cache model, not a real 750's**
(D94, D96, D97). Same for the 7–10 tick cost of the detour's two flushes.

## Related

- `ingame-testing` — the rig, the probe block, and the ways a run lies
- `hunting-a-hang` — `__assert2`, which is a hook like any other
- `decode-by-disassembly` — finding the function to hook when there is no symbol
- `control-every-statistic` — before believing a count a hook produced
