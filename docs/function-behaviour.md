# Function behaviour — what the game's code actually does

**Living document.** Facts about individual game functions, established by
*running* them and watching, not by reading a header.

The decomp is ~2.34% matched, so for most of the game there is no source to
read. `spm-headers` names about 927 symbols in `spm.eu0.lst` and describes far
fewer; 25 of those names appear in no header at all. This file is where the gap
gets filled in, one measurement at a time.

Companion to [`disc-layout.md`](disc-layout.md), which records what is true
about the *disc*. This one records what is true about the *code*.

## How anything gets into this file

By trace. `code.hooks` puts a branch over a function's first instruction (D95),
and the **self-healing detour** (D96) restores that instruction, calls the
original, and re-installs the branch — so a mod can record a function's
arguments and its return value without disabling it.

    uv run python scripts/ingame.py fn-trace-somewhere --words 62 --seconds 110

`mods/fn-trace-probe` and `mods/fn-trace-somewhere` are the worked examples;
[`code-mods.md`](code-mods.md#tracing-a-function-instead-of-replacing-it) has
the pattern.

### ⚠️ Rules for adding an entry

1. **A control that fired.** A traced function reading zero says nothing unless
   something else in the *same build* was counting. The first attempt at D96's
   third run had three hooks and three zeroes, and had to be discarded.
2. **Mark confidence.** ✅ observed directly · 🔶 inferred · ⛔ ruled out.
3. **Say what was traced and for how long.** "During the attract demo, 110 s"
   bounds a negative in a way "never called" does not.
4. **Do not record an argument the function does not have.** A handler declared
   with eight `u32`s records eight words regardless; past the real arity those
   are leftover register contents. Same for a `void` function's "return value".
5. **Floats are invisible.** Arguments in f1–f8 and float returns in f1 are not
   captured at all. Never write down a float argument as `0`.

---

## `GetBasicPlayer` — `0x8030AFC0` (eu0)

Listed in `spm.eu0.lst` under `// nw4r::snd.cpp`; in **no header**.

✅ **It returns its first argument plus `0xD8`.** Nothing else.

| Sample | argument 0 | result | difference |
|---|---|---|---|
| first call | `901D6170` | `901D6248` | `0xD8` |
| a later call | `901D5634` | `901D570C` | `0xD8` |
| last call | `901D6170` | `901D6248` | `0xD8` |

Two distinct objects, the same offset, over **24,406 calls in 110 s** of the
attract demo (D96). The static reading agrees: the first instruction at
`0x8030AFC0` is `386300D8` = `addi r3,r3,0xD8`, which `bleck` derived as the
hook's guard word at build time.

✅ It is called **once per rendered frame** — 24,406 calls against 24,435
SEQ_GAME frames.

✅ The objects it is handed live in **MEM2** (`0x901D…`), not MEM1.

🔶 The reading: a C++ base-subobject accessor, returning the `nw4r::snd` basic
sound player embedded at `+0xD8` inside a larger sound object. Fits the name,
the `nw4r::snd.cpp` grouping and the one-instruction body — but it is inference.
The arithmetic is what was measured.

⚠️ Its second recorded argument is **not** an argument: it read `0x4D3`, later
`0x2032`, drifting. A function that only touches r3 leaves r4 holding whatever
the caller had.

---

## `func_800cd554` — `0x800CD554` (eu0)

Listed under a literal `// somewhere`; in no header.

✅ **It is an alternate entry point to `effSmallStarEntry` (`0x800C1D60`).** Its
first word is `4BFF480C` = `b 0x800C1D60` — a tail branch, not a prologue. Read
straight out of `main.dol`, and confirmed as the guard word `bleck` derived when
hooking it.

⛔ **Not called during the attract demo** — zero entries in 110 s, with two
controls in the same build counting 24,406 and 28,635 (D96).

🔶 That is the attract demo's two maps (`aa4_01`, `ls4_12`), not the game. An
effect nobody triggers is not an effect that does not exist.

⚠️ Worth noting for the toolkit rather than for the game: a function starting
with a branch is exactly what a *trampoline* cannot relocate (D37). The
self-healing detour never moves the instruction, so this one traced normally.

---

## `func_800b426c` — `0x800B426C` (eu0)

Listed under `// somewhere`; in no header. Sits between `effHappyFlower`
(`0x800B3014`) and `effMapBlockDelEntry` (`0x800B5938`), so 🔶 an effect entry
point.

Prologue `9421FFA0` = `stwu r1,-0x60(r1)`, so it has a 0x60-byte frame — not a
leaf.

⛔ **Not called during the attract demo** — zero entries in 110 s, same build
and same controls as above (D96).

---

## `mapDataPtr` — `0x800294E0` (eu0)

Documented in `spm/map_data.h`; recorded here for what the *callers* do, which
is not in any header.

✅ **Every caller passes the same buffer.** All 19 calls in a 120-second run,
and all 15 in a separate 75-second run, were handed `0x80512260` — one address,
not a string literal per map. The bytes there change: the trace read `aa4_01`,
`ls4_12` and `title` from it over one run, and the returned `MapData *` changed
with them (`803FFF14` for `aa4_01`, `80402DE4` for `ls4_12`).

✅ `0x80512260` is **in .bss** (`main.dol` loads `80509C80..805B773C` as bss) and
sits `0x100` below `seqWork` (`0x80512360`). It has no name in `spm.eu0.lst`.

⚠️ **This is why a captured pointer is not a captured value.** The report shows
the *current* contents of that buffer for both the first and the most recent
call, because both recorded the same address. The bytes have to be copied at
call time to say anything about a specific call.

✅ It is called a handful of times per map change — 19 calls across 5 map
changes in 120 s. Not a hot function.

---

## `effMain` — `0x800618B0` (eu0)

Documented in `spm/effdrv.h`. Two operational facts that are not:

- ⛔ **Do not replace it.** Stubbing it wedges the game in `SEQ_MAPCHANGE`, which
  never completes (D94). Something in the map-change sequence waits on the
  effect driver advancing.
- ✅ **It can be traced.** With the original still running, the game completed 4
  map changes across 110 s with the detour installed (D96). `replace` and
  `trace` are not the same capability, and this is the function that shows it.
- ✅ Called **28,635 times in 110 s** against 24,435 SEQ_GAME frames — so it also
  runs during map changes, not only during gameplay.

---

## See also

- [`decision-log.md`](decision-log.md) — D94 (instruction patching), D95
  (`code.hooks`), D96 (the trace)
- [`hook-points.md`](hook-points.md) — when custom code can safely run
- [`code-mods.md`](code-mods.md) — the trace pattern and its hazards
- [`disc-layout.md`](disc-layout.md) — facts about the disc rather than the code
