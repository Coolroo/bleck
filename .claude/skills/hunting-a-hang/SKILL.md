---
name: hunting-a-hang
description: Use the moment the game freezes, hangs on a black screen, or Dolphin exits on its own — before bisecting anything. Most freezes in this game are asserts, and an assert names its own cause in one run. Covers hooking __assert2 at 0x8019c54c, the Shift-JIS trap, and example-mods/coin-nobudget.
---

# Hunting a hang

⚠️ **A hang that is really an assert names its own cause, and from outside the
two are indistinguishable.**

Four runs of bisecting narrowed one freeze to a single byte and no further.
Hooking `__assert2` turned it into `swdrv.c:505` in **one** run, in the game's
own words (D130):

```
swdrv.c:505
  (wp->gameCoinId - 1) < assign_tbl[i].num
  コインのフラグが溢れました        "the coin flags have overflowed"
```

**Do this first.** Every "the game froze" in this repository's history was worth
hooking `__assert2` for.

## The hook

`__assert2` is at **`0x8019c54c`** (eu0) and is in the symbol list, so name it
rather than the address. Its call sites pass `(file, line, func, expr)` in
`r3`–`r6`.

```json
"code": {
  "sources": ["src"], "target": "eu0", "module_id": 2, "boot": "an1_02",
  "hooks": [ { "function": "__assert2", "call": "on_assert", "mode": "before" } ]
}
```

`mode: "before"` runs your handler and then the original, so the assert still
does whatever it was going to do — you are watching, not replacing (D96, D97).

Handler side: copy all four arguments into the probe block, bounded and
NUL-padded, and count how many times the assert fired. A null pointer must
record nothing rather than faulting *inside the probe*.

`example-mods/coin-nobudget` is the worked example. Its report block:

```
+0x000 (  0)  magic 'ASRT'
+0x004 (  1)  SEQ_MAPCHANGE frames -- alive check
+0x008 (  2)  SEQ_GAME frames. Nonzero means the map finished loading
+0x00C (  3)  how many times __assert2 was entered
+0x010 (  4)  the line number of the FIRST one
+0x014 (  5)..( 20)  file, 64 bytes, NUL padded
+0x054 ( 21)..( 36)  func, 64 bytes
+0x094 ( 37)..( 52)  expr, 64 bytes
```

```bash
uv run python scripts/ingame.py coin-nobudget --words 53
```

Ask for **all** the words. A truncated read of a 53-word block is a wasted
2–3 minute run.

## ⚠️ Assert messages are Shift-JIS

Like the message files. Decoding the `expr` bytes as ASCII would have lost the
one sentence that explained everything in D130. Decode with `shift_jis` (or
`cp932`) when you reassemble the words on the host side.

## ⚠️ The frame counters are not decoration

`coin-nobudget` records `SEQ_MAPCHANGE` and `SEQ_GAME` frame counts alongside
the assert. That is the **alive check and the control**: without them, "no
assert fired" cannot be told apart from "the mod never ran", and "the map
froze" cannot be told apart from "the map never started loading".

This is the standing rule — *before trusting a negative result, produce a
positive one*. See `control-every-statistic`.

## When it is not an assert

- **Dolphin exits on its own.** `ingame.py` reports this explicitly rather than
  running out the clock, because a hard crash and a mod that did nothing look
  identical when the clock runs out.
- **The hook itself recursed.** A `before`/`after` hook on an address the DOL
  does not map is a build **error**, not a warning, precisely because the
  detour reaches the original by restoring a guard word and there is nothing to
  restore — left alone it recurses until the stack runs out (D97).
- **Nothing ran at all.** Check probe word 0 for the magic before believing any
  other word. See `ingame-testing`.

## Related

- `ingame-testing` — the rig, the probe block, and the ways a run lies
- `reading-the-game-live` — `code.hooks` modes and prototype hazards
- `decode-by-disassembly` — when the assert names a function you have no symbol
  for, and you need to read what it does
