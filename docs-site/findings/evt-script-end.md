---
title: An evt script that ends needs END_EVT, or the game hangs
description: END_SCRIPT (0x01) ends the instruction list; END_EVT (0x02) ends the running entry. Omitting the second leaves the entry alive and the game stops a few frames later
---

# An evt script that reaches its end needs `END_EVT`, or the game hangs

The `evt` VM has **two** terminators, and they do different things:

| opcode | name | ends |
|---|---|---|
| `0x01` | `EVT_OPC_END_SCRIPT` | the instruction **list** |
| `0x02` | `EVT_OPC_END_EVT` | the running **entry** |

✅ **A script whose body simply falls off its end, terminated with only
`END_SCRIPT`, leaves its evt entry alive — and the game stops advancing a few
frames later.**

## What the failure looks like

This is worth describing because it does not look like a script bug at all:

- Every value the script wrote is **correct**. Globals, work variables, whatever
  it set — all right.
- The module loaded, its hooks installed, its constructors ran.
- Then nothing moves. In our runs the `SEQ_GAME` frame counter stuck at 1 and
  the attract demo never left its first map.

A report block whose other fields all read "good" is the shape of thing that
gets recorded as a success. The first such run here was nearly written up as
one; only a frame counter stuck at 1 gave it away.

## The evidence

Three builds, one variable — how the script ends:

| script | result |
|---|---|
| `gw[21] = 0x5C0` (falls off the end) | ⛔ froze, stuck on the first map |
| `gw[21] = 0x5C0; return` (explicit `return`) | ✅ reached the second map at t+9s |
| the first one again, after emitting both terminators | ✅ reached the second map at t+9s |

The compiler under test emitted `END_EVT` for an explicit `return` but only
`END_SCRIPT` for a body that ran out — which is what predicted the middle row,
and made the whole thing a two-line test rather than a new instrument. A
control build with **no script at all** ran fine, which is what pointed at
scripts rather than at the module.

*(Source: bleck decision log D105 — the six-run bisection, five wrong
hypotheses — and D106, the cause.)*

### ✅ The game's own scripts agree

An independent corroboration, found later and by accident.
`DoorDesc[0].moveScript` in `he1_01` (`0x80D2FB70`, PAL rev 0) is an **empty
script**, and it is exactly two words:

```
00000002 00000001        ; END_EVT, then END_SCRIPT
```

The two words after it belong to `interactScript` at `0x80D2FB78`, 8 bytes
later. So the game's own do-nothing script is a `RETURN()` followed by an
`EVT_END()`, which is precisely the pattern the freeze was diagnosed into
(D116).

## ⚠️ This is easy to hit with the upstream macros

`spm-headers`' `mod/evt_cmd.h` defines:

```c
#define EVT_END() \
    0x1 };

#define RETURN() \
    EVT_HELPER_CMD(0, 2),
```

and the decomp-flavoured header is the same shape:

```c
#define EVT_END() \
    EVT_CMD_(EVT_OPC_END_SCRIPT) \
    };

#define RETURN() \
    EVT_CMD_(EVT_OPC_END_EVT),
```

So `EVT_END()` emits **only** `END_SCRIPT`. A hand-written script that does not
end with `RETURN()` before its `EVT_END()` has the bug. Nothing warns.

🔶 Whether every evt entry hangs the game this way, or only entries started on
the paths we used, is not established — what is measured is that the same
script froze in a map hook and in a `main`, and that adding the terminator fixed
both.

## Why nothing catches it

Every worked example anyone writes tends to loop forever (`loop { wait_ms }`),
wait and then change map, or otherwise never end. So the case a first-time
script author writes **first** — "do a thing" — is the one case that never gets
exercised. In this repository, 809 tests passed on both the broken and the fixed
compiler, because they compared the compiler's bytecode against itself rather
than against what the VM requires.

If you write an evt compiler, assert the property the VM imposes, not the bytes
you happen to emit.

## See also

- [How an evt instruction is encoded](evt-instruction-format.md)
- [Door descriptors](door-descriptors.md) — where the empty script above lives
