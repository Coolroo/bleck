---
title: Patching PowerPC code at runtime — the cache flush is load-bearing
description: A store alone leaves the old instruction executing even though a debugger sees the new word, measured against a no-flush control, and Dolphin reproduces it
---

# The cache flush is load-bearing, measured against a control

To make a written PowerPC instruction actually execute on the Wii's 750-family
CPU you need, after the store:

```
dcbst   # push the data cache line to memory
sync
icbi    # invalidate the instruction cache line
isync
```

Everyone "knows" this. It is worth having a measurement anyway, because a check
that has never been shown to fail has not been tested — and this one had been
recorded as verified in this project on exactly that basis, from code that
worked with the flush present, which says nothing about whether it was needed.

## The experiment

Two pairs of trivial functions in a loaded module's own `.text`, patched
identically, differing **only** in whether the cache line was flushed. Each pair
is called once *before* the write, so the old body is already in the instruction
cache when the store lands — otherwise the no-flush case is not adversarial and
proves nothing.

The build was checked against `objdump` first, because a constant-folded call
would have made a working patch invisible: the bodies are two-instruction leaves
(`lis r3,imm; blr`) and every call goes through a `volatile` function pointer,
compiling to `bctrl`.

| | pair A — no flush | pair B — flush |
|---|---|---|
| encoded word | `48000008` | `48000008` |
| return **before** the write | `A11A0000` | `B11B0000` |
| return **after** the write | **`A11A0000` — unchanged** | **`B22B0000` — the jump took** |
| first instruction, read back | `48000008` | `48000008` |

⚠️ **Read the last two rows together.** The unflushed word *is* in memory — a
debugger, or any load, sees the branch. The instruction fetcher does not, and
ran the old body anyway. That is exactly the failure mode this was expected to
have: a verification that passes for the wrong reason.

✅ **Dolphin reproduces the stale fetch** without being asked to. Its cache
model is faithful enough that "it worked in the emulator" is not, in this
particular case, a false comfort.

## ⚠️ Two hazards worth writing down

**Cache lines are 32 bytes.** Pair A and pair B sat 8 bytes apart, so they share
a line: pair B's `icbi` also invalidated pair A's. Pair A's clean result is only
clean because it was measured *before* pair B ran. Separate functions were not
enough; separate **measurement order** was.

**Encode the branch, and refuse rather than mask.**

```
0x48000000 | ((to - from) & 0x03FFFFFC)
```

The displacement field is 26 bits signed, so the valid range is
`-0x02000000 … +0x01FFFFFC`. Out of range must be **refused**, not masked —
masking produces a perfectly valid branch to somewhere else entirely. ✅ That
refusal was exercised deliberately (a hook aimed at `0x90000000` returned an
error and left the target word untouched), because a range check that has only
ever been skipped has not been tested either.

## ✅ It works on the game's own code, not just on the module's

A branch written over a DOL function's first instruction at module load time
was still there and still firing **62,480 times** across a 90-second run, tens
of thousands of frames later. That control is what excludes "something
overwrote it in between", which a readback alone cannot.

⚠️ In the same session, replacing `effMain` (the effect driver's per-frame
update, chosen as "cosmetic, cannot gate anything") wedged the game in
`SEQ_MAPCHANGE` for the full run. See
[undocumented functions](undocumented-functions.md) — **do not stub `effMain`**.

## Not established

- 🔶 **Hardware.** Every result here is Dolphin's cache model. Nothing has been
  run on a real Wii.
- ⛔ This is branch **replacement**: the original body is destroyed. Watching a
  function without breaking it is a different capability —
  [the self-healing detour](function-tracing.md).

*(Sources: bleck decision log D94, correcting D38's "verified" claim.)*

## Contrast: evt bytecode needs none of this

Patching the game's *script* bytecode is a plain store with no flush at all,
because bytecode is read as data through the data cache. See
[how an evt instruction is encoded](evt-instruction-format.md).
