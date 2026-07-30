---
title: Reproducing these findings
description: The exact commands behind every address and offset on this site, so any claim here can be checked against your own copy of the game rather than taken on trust
---

# Reproducing these findings

Every address, offset and behaviour published here was read out of a retail
disc. **None of it has to be believed.** This page gives the commands that
produce each one, so you can check them against your own copy.

**All addresses are PAL rev 0 (`R8PP01`, "eu0")** and do not transfer to other
builds.

## What you need

- Your own legally-obtained disc, extracted (`bleck extract <disc>`)
- `powerpc-eabi-objdump`, from devkitPPC — for disassembly only
- For the runtime measurements: Dolphin and `dolphin-memory-engine`

Nothing here needs a symbol name that the game does not carry, and most of it
needs no symbol at all — which is the point of the method below.

---

## The method, in four steps

`eu0`'s public symbol list names a few thousand functions in a game with far
more, so most of this started from something that is **not** a symbol. The
sequence that kept working:

```bash
# 1. Find a string. Assert __FILE__s are the best lead: they name a
#    translation unit and sit next to the condition that failed.
uv run python scripts/dolscan.py strings swdrv.c
#    0x80326277  0swdrv.c

# 2. Find the code that builds that address.
uv run python scripts/dolscan.py xref 0x80326278 --window 0x60
#    0x800380B4  r3 = 0x80326278
#    ...

# 3. Read it.
uv run python scripts/dolscan.py dis 0x800386e0 24

# 4. Where a struct field is involved, find who reads it.
uv run python scripts/dolscan.py calls 0x40 0x800de9b8
#    0x800E17A4  lwz r5,0x40(..)  ->  bl 0x800DE9B8
```

⚠️ **Step 2 needs a real tool, not `grep`.** The game builds most addresses as a
base register plus an offset — `lis`/`addi` to a base, then `addi` off it — so a
search for a single two-instruction pair finds *nothing*. `xref` tracks register
values across `lis`/`addis`/`addi`, and `--window` reports bases near the target
as well as exact hits.

`scripts/dolscan.py` is about 250 lines and does only this.

---

## Claim by claim

### The coin-flag budget

`swdrv_assign_tbl` at **`0x80326178`** — 32 entries of `{const char *mapName,
s32 num}`, summing to 853.

Found by the four steps above, starting from the `swdrv.c` assert string. Read
it back directly:

```python
ptr, num = struct.unpack('>Ii', at(0x80326178 + i * 8, 8))
#  [0] an3_01   27
#  [1] an3_03   6
#  [2] an3_12   24
```

⚠️ The **structure** is not ours: `spm-headers` declares `AssignTblEntry` and
`MAX_COIN_MAP 32`, and our read matches it exactly — which is a useful check on
the read, not a coincidence to hide. What is not published anywhere else is the
address, the contents, and what happens when the budget is exceeded.

### That overflowing it hangs the game

Not inferred — the game says so. `__assert2` is at `0x8019c54c` and its call
sites pass `(file, line, func, expr)`. Hook it and record the arguments:

```json
"hooks": [ { "function": "__assert2", "call": "on_assert", "mode": "before" } ]
```

```
swdrv.c:505
  (wp->gameCoinId - 1) < assign_tbl[i].num
  コインのフラグが溢れました
```

`mods/coin-nobudget` is the worked example. ⚠️ Assert messages are **Shift-JIS**;
decoding as ASCII discards the sentence that explains the failure.

### The item loader and its 512 ceiling

```bash
uv run python scripts/dolscan.py strings setup_data.c   # 0x80323BB0
uv run python scripts/dolscan.py xref 0x80323BB0        # 0x800297A8
uv run python scripts/dolscan.py dis 0x80029730 40      # setupReadItemInfo
uv run python scripts/dolscan.py dis 0x8017a9c8 40      # its caller
```

The caller allocates `8192` bytes, then `memcpy`s `count * 16` where `count`
came from the file. That is the ceiling, and nothing clamps it.

### `EvtDoorWork`'s internals

`spm-headers` declares this struct as `u16 flags` followed by
`u8 unknown_0x2[0x57c - 0x2]`. Each offset below was read out of the function
that uses it, so each has its own citation:

```bash
uv run python scripts/dolscan.py dis 0x800e11b0 14   # active desc, +0x2D8, flag bit 11
uv run python scripts/dolscan.py dis 0x800e4118 40   # zone array, +0x36C / +0x370
uv run python scripts/dolscan.py dis 0x800e45c8 40   # event slots, +0x374
```

✅ `evt_door_wp` = `0x805AE020` **is** in the published symbol list, and our
computed value matched it — an independent check on the arithmetic, which we got
wrong once and caught this way.

### The door census

```bash
uv run python scripts/dump_doors.py --out doorcatalog.json
```

One boot, reading every map from outside the emulator: 368 maps, **35**
scriptable `DoorDesc`s, **691** loading zones.

✅ **Cross-validated by two unrelated mechanisms.** The same numbers for
`he1_01` were produced first by C running *inside* the game walking its own map
data, and then by Python reading the emulator's memory from *outside*. They
agree on door name, group, and all three zone destinations.

### The runtime behaviour

Booting, walking a probe block and shutting down is
[the rig](method.md). Each behavioural claim names the mod that produced it:
`mods/door-swap`, `mods/zone-event`, `mods/coin-nobudget`, `mods/mr-l`.

---

## Where this disagrees with published headers

Worth stating plainly, because it is the sharpest evidence that these were
measured rather than copied: **`spm-headers` is wrong in places, and we
reproduce the game's behaviour rather than its declarations.**

| | published | measured |
|---|---|---|
| `evt_door_set_door_descs` argc | `EVT_DECLARE_USER_FUNC(..., 1)`, i.e. 2 | **3** |
| `evt_door.h`'s own comment | `(DoorDesc *descs, s32 count)` — implying 3 | agrees with the measurement, not the macro |

Two of this project's earlier conclusions were wrong *because* they trusted the
declared count, and the decision log records both being retracted. A copy would
have inherited the error and stopped there.

## What is *not* ours

Being precise about this costs nothing and makes the rest credible:

- **Struct layouts** — `DoorDesc`, `MapDoorDesc`, `SetupItem`, `SwCoinEntry`,
  `AssignTblEntry` come from
  [`spm-headers`](https://github.com/SeekyCt/spm-headers) (MIT), attributed in
  `THIRD-PARTY-NOTICES.md`. Where we confirmed one against the disc, we say so.
- **Symbol names and addresses in the published `.lst`** — same source.
- **The game itself.** Addresses, offsets and observed behaviour are facts about
  a binary; the binary is Nintendo's, and nothing here reproduces any of it.

What this project adds is the addresses the lists do not carry, the contents of
tables nobody had dumped, the offsets upstream marks unknown, and the
behaviour — which is the part you cannot get from a header at all.

## The record itself

`docs/decision-log.md` is chronological, dated and append-only, and it includes
the wrong turns: hypotheses that failed, a conclusion retracted the day after it
was published, an arithmetic error that froze the game, and a bug found only by
building a real mod after 1,017 unit tests passed.

⚠️ **The mistakes are the load-bearing part.** A finding arrived at by
measurement has a history of being wrong first; one that was copied does not.
