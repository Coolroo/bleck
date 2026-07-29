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

## The door descriptor setters — `evt_door_set_door_descs` and friends

⚠️ **Established by walking bytecode, not by tracing** (D101), which is a
different instrument from everything above — the entries here are `USER_FUNC`
call sites found in map init scripts, so what is measured is *who calls them and
with what*, not what the functions do internally.

`evt_door_set_door_descs` is `0x800E2610` (eu0), declared in `evt_door.h`.

✅ **They are called from map init scripts.** One 90 s `mods/door-scan` run:

| | |
|---|---|
| `evt_door_set_door_descs` | 1 call |
| `evt_door_set_map_door_descs` | 3 calls |
| `evt_door_set_dokan_descs` | 3 calls |
| control (`evt_hitobj_attr_onoff`) | 8 hits |
| walks truncated at the 4096-word limit | 0 |

✅ **The first argument is the descriptor array's address, in the bytecode.**
`DoorDesc *` = `0x80D2FBB0`; `MapDoorDesc *` = `0x80D2F940`, from `he1_01`. The
check that makes this a finding rather than a number: `MapDoorDesc[0].destMapName`
read back as the string **`he1_02`** — a real map name. A wrong pointer does not
spell one.

✅ Layouts, from `evt_door.h`: `DoorDesc` is 0x58 bytes with `interactScript`
+0x40, `initScript` +0x50, `moveScript` +0x54. `MapDoorDesc` is 0x20 bytes with
`destMapName` +0x14 and `destDoorName` +0x18 — the **loading zone** descriptor.

### ✅ All three setters take argc 3 (D102)

`mods/door-argc`, one 75 s run:

| | header | map | arg0 | arg1 |
|---|---|---|---|---|
| `evt_door_set_door_descs` | **`0x0003005C`** | `he1_01` | `0x80D2FBB0` | **1** |
| `evt_door_set_map_door_descs` | **`0x0003005C`** | `he1_01` | `0x80D2F940` | **3** |
| `evt_door_set_dokan_descs` | **`0x0003005C`** | `mac_01` | — | — |
| control `evt_hitobj_attr_onoff` | **`0x0005005C`** | — | — | 8 hits |

The `USER_FUNC` header, the function pointer, then `(descs, count)`. ⚠️ The
control's *header word* is the check that matters, not its hit count: D88
recorded that call at argc 5, so `0x0005005C` was known in advance from an
unrelated run and reading it back proves headers are being decoded from the
right offset.

✅ So `he1_01` registers **1** door and **3** loading zones, and `mac_01`
registers dokan (pipes) — which is why D94's two maps genuinely have no
`DoorDesc` call. Its zero was honest, and about map coverage.

✅ `DoorDesc[0]`'s three script pointers are all non-null and were re-read by a
different probe in a different run (D103, D104), which is what confirms the
offsets — a wrong offset landing on a non-null word would look the same:

| field | offset | pointer |
|---|---|---|
| `interactScript` | +0x40 | `0x80D2FB78` |
| `initScript` | +0x50 | `0x80D2F9E0` |
| `moveScript` | +0x54 | `0x80D2FB70` |

✅ `MapDoorDesc[0]` spells `destMapName` **`he1_02`** and `destDoorName`
**`doa1_l`**, so its +0x14/+0x18 offsets are right too. ✅ All of it read at
`mod_prolog`, so the descriptor arrays are resident before gameplay — which is
what makes a build-time-declared patch possible at all.

⚠️ **A door interact script opens with `MULF`.** `he1_01` door 0's
`interactScript` starts `0x0002003C` — opcode `0x3C`, a float multiply, argc 2.
Not a `USER_FUNC`, not a `DEBUG_PUT_MSG`, and not what anyone would guess, which
is why `code.patches`' `expect` has no useful default for a door (D103). 🔶 What
`initScript` and `moveScript` open with is not recorded.

### ⛔ `evt_door.h`'s argument count is wrong

```c
// evt_door_set_door_descs(DoorDesc * descs, s32 count)
EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)     // -> argc 2
```

The comment says two arguments; the macro says one. **The game says three words
— the comment.** D93 trusted the macro, searched at argc 2 only, and recorded
zero calls; D94 followed. ⛔ Both are superseded.

⚠️ **`spm-headers` is a reference, not ground truth.** It is hand-maintained
against a 2.34%-matched decomp, and this is the first case recorded here where
one of its declarations is simply incorrect. Where a header's claim is
load-bearing — an argc, an offset, a size — reading it is a hypothesis 🔶, not a
finding. Measure it.

🔶 Five maps is not the game, and the `count` argument was read as a literal — a
script that computed it would not be handled.

⛔ **Hooking the function is not the route in.** D94 branched over it and counted
zero entries in 90 s with a control at 62,480 — but that run covered `mac_01`,
`aa4_01` and `ls4_12`, none of which contain the call. Reading the argument out
of the bytecode needs no hook at all (D89, D101), and `code.patches`'
`door:<map>:<index>` selector is built on that walk (D103, D104).

---

## NPC behaviour scripts — `npcGetWorkPtr` `0x801c9adc` (eu0)

⚠️ **Research, not a feature.** `npcdrv:` is not a `code.patches` selector and
nothing here is declarable from a manifest. What follows is what three
`mods/npc-probe` runs measured (D107).

Declared in `spm/npcdrv.h`. Established by reading the structure it returns
during gameplay, not by tracing the function.

✅ **Measured, booting into `he1_01`** (`scripts/ingame.py --map he1_01`):

| | |
|---|---|
| `npcGetWorkPtr()` | `0x805283E0`, usable every gameplay frame |
| `work->num` | **80**, constant |
| `work->entries` | `0x807BB960` |
| live slots (control: head word non-zero) | **3** |
| slots carrying script pointers | **3** — all of them |
| `templateinitScript` | `0x8043B8F8` |
| `templatemoveScript` | `0x804938E8` |
| `templateonHitScript` | `0x80494E28` |
| `templatedeathScript` | `0x80439F10` |
| first word of the init script | **`0x0002005C`** |

⚠️ **`NPCWork.num` is the array's capacity, not a live count.** It read exactly
80 for the whole of every run and never moved; `npcGetMaxEntries` is a separate
symbol. A slot inside that range can be entirely unused, so reading one and
finding nulls says nothing about whether NPCs exist.

✅ **The scripts are real evt bytecode.** The init script's first word decodes as
`USER_FUNC` with argc 2 — that is the evidence. Four non-null pointers are four
numbers; a word that decodes as a known opcode with a sane argument count is
bytecode.

✅ **The bytecode lives in DOL static data** (`0x8043…`–`0x8049…`, inside the
data span D95 recorded reaching `0x805B7720`), not on the heap. So the *script*
is at a fixed address even though the *pointer* is on a live entry.

⛔ **`work->setupFile`** (`NPCWork` +0x18) read **0** on every frame in every map
tried. Either the offset is wrong or it is populated on a path these runs did
not take. Unexplained, and not chased.

### ⛔ The attract demo's maps contain no NPCs at all

Two earlier runs read zero and both were honest measurements of the wrong place:

- **Run 1** read `entries[0]` and found four nulls — slot 0 was simply unused,
  because `num` is a capacity.
- **Run 2** scanned all 80 slots and still found nothing, because it ran on
  `aa4_01` and `ls4_12`.

✅ What broke the cycle was a **control that could tell the two apart**: count
slots whose head word is non-zero — live at all — independently of whether the
script offsets are right. With `--map he1_01` it read 3, and the script counts
followed. Without it, run 3's numbers would have been one more plausible zero.

### ⛔ Superseded: the templates were found, and `npcdrv:` was built

⚠️ **Everything from here to the end of this section is D107's reading and is
wrong in its conclusion.** D110 found the static table, D111 measured its stride
(and got the field offsets wrong), D112 corrected them and built the selector:

| | |
|---|---|
| `npcEnemyTemplates` | `0x80449888`, stride **`0x68`**, entry *n* = template *n* |
| `initScript` / `moveScript` / `onHitScript` / `deathScript` | +0x34 / +0x38 / +0x3C / **+0x48** |
| sharing | **280** templates share template 2's death script; **40** its onhit |

✅ Confirmed in game (D115): a patch on `npcdrv:2` (Goomba) fired when the
player hit a **Squiglet**, template 250. The kept text below is why the wrong
inference looked sound.

### 🔶 Why this is not a `door:`-shaped selector yet

| | where the pointer lives | readable at `mod_prolog`? |
|---|---|---|
| `door:` | an argument in the map's **init script** bytecode | ✅ yes |
| NPC scripts | fields on a **live `NPCEntry`**, copied in at spawn | ⛔ no |

🔶 So a build-time selector needs the **template**, not the entry, and where
templates live is not known. `npcEntryFromTemplate` (`0x801be198`) and
`npcEntryFromSetupEnemy` (`0x801bf7a0`) are the two spawn paths; the second
takes a record from the setup file `bleck` already parses and edits (D80), which
is the promising thread.

🔶 Alternatives, unranked: intercept a spawn function with `code.hooks`
`mode: "after"` (D97) and rewrite the entry's pointers per spawn; or find the
static template table and patch it like a door. The first is certainly possible
today; the second would be a *declaration* rather than a hook, which is what
[`vision.md`](vision.md) asks for.

🔶 `npcNameToPtr` (`0x801b6f2c`) means NPCs **can** be looked up by name, unlike
doors — a nicer selector shape if it can be reached at a useful time.

---

## ⚠️ Three times now: the right measurement, the wrong maps

D94 (doors), D101 (doors again) and D107 (NPCs) each recorded a zero that was a
fact about **map coverage**, not about the game. The attract demo reaches only
`aa4_01` and `ls4_12`, and neither registers a `DoorDesc` or holds an NPC.

`scripts/ingame.py --map <name>` boots straight into any of the 383 maps (D64),
so this costs nothing to avoid. **Before recording that something is absent,
check the run was in a map that has it** — and pair the reading with a control
that would have looked different if it were present.

---

## See also

- [`decision-log.md`](decision-log.md) — D94 (instruction patching), D95
  (`code.hooks`), D96 (the trace), D101 (the door setters, and why D93/D94 were
  wrong about them), D102 (their argc, and the wrong header), D103/D104 (the
  `door:` selector), D107 (NPC behaviour scripts, and the third wrong-maps zero)
- [`hook-points.md`](hook-points.md) — when custom code can safely run
- [`code-mods.md`](code-mods.md) — the trace pattern and its hazards
- [`disc-layout.md`](disc-layout.md) — facts about the disc rather than the code
