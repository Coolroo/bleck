---
title: Four functions, measured by tracing them
description: GetBasicPlayer returns arg0 + 0xD8; func_800cd554 is an alternate entry point; do not stub effMain; every mapDataPtr caller passes the same buffer
---

# Four functions, measured by running them

**PAL rev 0 (`R8PP01`, "eu0").** Each of these was measured with
[a self-healing detour](function-tracing.md) — the original kept running — over
runs of 90–120 seconds of the [attract demo](attract-demo.md). Where a count is
given, another hook in the *same build* was counting at the same time; a traced
function reading zero says nothing unless something else in the same run was
firing.

## `GetBasicPlayer` — `0x8030AFC0`

Listed in the PAL symbol list under `// nw4r::snd.cpp`, and in **no header**.

✅ **It returns its first argument plus `0xD8`.** Nothing else.

| sample | argument 0 | result | difference |
|---|---|---|---|
| first call | `901D6170` | `901D6248` | `0xD8` |
| a later call | `901D5634` | `901D570C` | `0xD8` |
| last call | `901D6170` | `901D6248` | `0xD8` |

Two distinct objects, the same offset, across **24,406 calls in 110 seconds**.
The static reading agrees: the first instruction at `0x8030AFC0` is `386300D8` =
`addi r3,r3,0xD8`.

✅ It is called **once per rendered frame** — 24,406 calls against 24,435
gameplay frames.

✅ The objects it is handed live in **MEM2** (`0x901D…`), not MEM1.

🔶 The reading: a C++ base-subobject accessor returning the `nw4r::snd` basic
sound player embedded at `+0xD8` inside a larger sound object. That fits the
name, the `nw4r::snd.cpp` grouping and the one-instruction body — but it is
inference. The arithmetic is what was measured.

⚠️ Its second recorded "argument" is **not** an argument: it read `0x4D3`, later
`0x2032`, drifting. A function that only touches r3 leaves r4 holding whatever
the caller had.

## `func_800cd554` — `0x800CD554`

Listed under a literal `// somewhere`; in no header.

✅ **It is an alternate entry point to `effSmallStarEntry` (`0x800C1D60`).** Its
first word is `4BFF480C` = `b 0x800C1D60` — a tail branch, not a prologue. Read
straight out of `main.dol` and confirmed as the word the hook restored.

⛔ **Not called during the attract demo** — zero entries in 110 seconds, with two
controls in the same build counting 24,406 and 28,635.

🔶 That is the attract demo's two maps, not the game. An effect nobody triggers
is not an effect that does not exist.

## `func_800b426c` — `0x800B426C`

Listed under `// somewhere`; in no header. Sits between `effHappyFlower`
(`0x800B3014`) and `effMapBlockDelEntry` (`0x800B5938`), so 🔶 an effect entry
point.

Prologue `9421FFA0` = `stwu r1,-0x60(r1)`, so it has a 0x60-byte frame and is
not a leaf.

⛔ **Not called during the attract demo** — zero entries in 110 seconds, same
build and same controls as above.

## `effMain` — `0x800618B0`

Documented in `spm-headers`' `effdrv.h`. Two operational facts that are not:

- ⛔ **Do not replace it.** Stubbing it wedges the game in `SEQ_MAPCHANGE`,
  which then never completes — 90 seconds without reaching gameplay. Something
  in the map-change sequence waits on the effect driver advancing. It was picked
  as a hook target precisely because it looked cosmetic.
- ✅ **It can be traced.** With the original still running, the game completed
  **4 map changes** across 110 seconds with the detour installed. That is the
  clearest demonstration that "replace" and "watch" are different capabilities.
- ✅ Called **28,635 times in 110 seconds** against 24,435 gameplay frames — so
  it runs during map changes too, not only during gameplay.

## `mapDataPtr` — `0x800294E0`

Documented in `spm-headers`' `map_data.h`. What is recorded here is what the
*callers* do, which is not in any header.

✅ **Every caller passes the same buffer.** All 19 calls in a 120-second run, and
all 15 in a separate 75-second run, were handed `0x80512260` — one address, not
a string literal per map. The bytes there change: the trace read `aa4_01`,
`ls4_12` and `title` from it over one run, and the returned `MapData *` changed
with them (`803FFF14` for `aa4_01`, `80402DE4` for `ls4_12`).

✅ `0x80512260` is in **.bss** (`main.dol` loads `80509C80..805B773C` as bss) and
sits `0x100` below `seqWork` (`0x80512360`). It has no name in the PAL symbol
list.

⚠️ This is the worked example for "a captured pointer is not a captured value".
A trace that stores the pointer shows the buffer's *current* contents for the
first call and the most recent call alike, because both recorded the same
address. The strings above were copied into the report block at call time.

✅ It is called a handful of times per map change — 19 calls across 5 map changes
in 120 seconds. Not a hot function, contrary to the assumption that picked it.

*(Sources: bleck decision log D94, D96.)*
