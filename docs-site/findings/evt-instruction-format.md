---
title: How an evt instruction is encoded
description: Header word, argument words, USER_FUNC's argc, operand bases, and how a user func reaches its arguments at run time
---

# How an evt instruction is encoded, and how `USER_FUNC` gets its arguments

An `evt` script is an array of 32-bit words. Every instruction is:

```
header = (argc << 16) | opcode      followed by argc words
```

so an instruction occupies `argc + 1` words. This is not our discovery — it is
`spm-headers`' `EVT_HELPER_CMD(parameter_count, opcode)` — but it is worth
stating because everything else on these pages is written in terms of it, and
because **`argc` counts words, not user-visible arguments**.

## `USER_FUNC` is opcode `0x5C` (92)

Its first data word is the **function pointer**; the rest are the arguments.
So for a call with *n* arguments the header is `((1 + n) << 16) | 0x5C`.

Header words measured in the wild (PAL rev 0):

| header | meaning | seen in |
|---|---|---|
| `0x0001005C` | `USER_FUNC`, no arguments | a two-word replacement patch |
| `0x0003005C` | `USER_FUNC`, 2 arguments | [the door descriptor setters](evt-door-argc.md) |
| `0x0004005C` | `USER_FUNC`, 3 arguments | 19 of the 33 [item use scripts](item-event-data-table.md) |
| `0x0005005C` | `USER_FUNC`, 4 arguments | `evt_hitobj_attr_onoff` in map init scripts |
| `0x00010072` | `DEBUG_PUT_MSG`, 1 argument | the head of `he1_01`'s map init script |
| `0x0002003C` | `MULF`, 2 arguments | the head of a [door's interact script](door-descriptors.md) |
| `0x0002001A` | opcode `0x1A`, 2 arguments | the head of that door's init script |
| `0x00000002` | `END_EVT` | [an empty script](evt-script-end.md) |
| `0x00000001` | `END_SCRIPT` | ditto |

## Operands are biased integers

From `spm-headers`' `evtmgr_cmd.h`, and worth repeating because a raw word out
of a memory dump is otherwise unreadable:

| operand kind | encoding |
|---|---|
| local work `LW(i)` | `i - 30000000` |
| global work `GW(i)` | `i - 50000000` |
| float literal | `(s32)(value * 1024) - 240000000` |
| pointer | `(s32) address` |

✅ Checked against a real instruction rather than taken on trust: the door
interact script's opening `MULF` has data words `0xFE363C80` and `0xF1B1E5C7`.
`0xFE363C80` is −30,000,000 exactly, i.e. **`LW(0)`**. 🔶 `0xF1B1E5C7` is
−239,999,545, which under the float rule is `455 / 1024` ≈ **0.444** — arithmetic
from the header, not a measurement of what the door does with it.

## How a user func reaches its arguments at run time

Measured from inside a hook that a patched `USER_FUNC` called, reading the live
`EvtEntry` (PAL rev 0, argc 1 — a call with no user arguments):

```
pCurData (+0x14)   80D2FF18   = &script[2], one word past the function pointer
pCurData[0]        0005005C   = the *next* instruction's header
entry + 0x08       01005C00   = flags 01, curDataLength 00, curOpcode 5C
```

✅ Two numbers agree on one mechanism: **the dispatcher consumes the function
pointer and leaves `pCurData` at the first user argument**, with
`curDataLength` counting only those. For argc 1 there are none, so
`curDataLength` is 0 and `pCurData` points past the pointer.

🔶 That `pCurData[0 .. n-1]` are the arguments for calls with *n* > 0 follows
from this but has not been read back directly.

*(Source: bleck decision log D92.)*

## Consequences for patching bytecode

Two properties that make in-place edits practical, both measured:

✅ **An instruction can be replaced by a `USER_FUNC` of the same `argc`, in
place, with nothing moving.** Take the matched header's top half and OR in
`0x5C`, write your function pointer into the first data word, and leave words
2..n untouched — they are passed through to your handler. Because the size is
taken from the word the guard just matched, it cannot diverge:

```c
script[at]     = (expect & 0xFFFF0000u) | 0x005Cu;   /* USER_FUNC, same argc */
script[at + 1] = (u32) handler;
```

This matters because each `EvtEntry` caches a `jumptable[]` of label positions.
Inserting or deleting a word moves labels; replacing one does not. It also means
the shortest patchable instruction is **two words** — a one-word instruction
like `END_EVT` cannot become a `USER_FUNC` without moving something.

✅ **No cache flush is needed.** evt bytecode is read as *data*, through the data
cache, so a plain store is enough. That is the opposite of
[patching PowerPC instructions](ppc-code-patching.md), where a store alone
silently does nothing.

✅ A patched vanilla script really does call into a loaded module: the word was
read back as changed, the hook's entry counter reached 1, and the map kept
running for 90 seconds afterwards. Returning `2` from a user func is the value
that lets the script advance normally (D89, D90).

⚠️ **Item and enemy scripts are shared.** Patching one is not patching one
thing — see [`itemEventDataTable`](item-event-data-table.md) (22 distinct
scripts across 33 entries) and [`npcEnemyTemplates`](npc-enemy-templates.md)
(280 templates sharing one death script).
