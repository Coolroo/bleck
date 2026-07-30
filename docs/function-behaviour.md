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

    uv run python scripts/ingame.py fn-trace-probe --words 28 --seconds 120

`example-mods/fn-trace-probe` is the worked example. The three-target run below
used a separate probe, removed in D148; its measurements stand.
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

✅ **They are called from map init scripts.** One 90 s bytecode-walk run
(a probe since removed in D148; the measurement stands):

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

One 75 s run (a probe since removed in D148; the measurement stands):

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
runs measured (D107) with a probe since removed (D148).

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

---

## `setupReadItemInfo` — `0x80029730` (eu0)

Hands back a setup file's item count, version and array. **No length check of
any kind**, so for the 184 v6 files that end exactly at `0x2BC4` all three reads
are past the end of the file:

```
80029784  lwz  r7, 11204(r3)   ; *(file + 0x2BC4) -> itemCount
80029788  addi r0, r3, 11212   ;   file + 0x2BCC  -> items
80029790  lwz  r3, 11208(r3)   ; *(file + 0x2BC8) -> itemVersion
```

v5 uses `0x2A34` / `0x2A38` / `0x2A3C` for the same three.

⚠️ **The caller caps a map at 512 items** and nothing enforces it: it allocates
8192 bytes, then `memcpy`s `count * 16` where `count` came from the file
(`0x8017A9C8`). It also **asserts** `itemVersion == 20051201` (`setup_data.c:355`)
whenever the count is non-zero, so a wrong version hangs rather than being
ignored. A count of 0 skips the assert, the copy and the spawn entirely.

*(D128, D129.)*

## `swdrv` coin flags — `swdrv_assign_tbl` `0x80326178` (eu0)

**Neither this address nor `swdrv_wp` (`0x805ADF40`) is in the published symbol
list**, though `spm-headers` declares both structures.

A coin is persistent, so each owns a save flag from a fixed per-map budget: 32
entries of `{const char *mapName, s32 num}`, summing to 853. Overflowing it
**hangs the game** rather than dropping the coin:

```
swdrv.c:505   (wp->gameCoinId - 1) < assign_tbl[i].num
              コインのフラグが溢れました   "the coin flags have overflowed"
```

⚠️ **The budget counts coins the setup file cannot see** — coins in blocks are
map objects. `he1_01` has a budget of 4, ships no setup items, and still refused
one coin: `gameCoinId` was 5 at the assert.

⚠️ A map **absent** from the table is not stuck: the allocator returns `-1`, and
the collected-check at `0x8003875C` reads `-1` as "not collected", so the coin
spawns. 204 of the 227 maps with a setup file are in that position.

*(D130, D133.)*

## `EvtDoorWork` — `evt_door_wp` `0x805AE020` (eu0)

`spm-headers` has this as `u16 flags` plus `u8 unknown_0x2[0x57c - 0x2]`. Four
offsets are now known, each read out of the function that uses it:

| offset | what | found in |
|---:|---|---|
| `+0x000` | flags; **bit 11 = the active-door pointer is valid** | `evtDoorGetActiveDoorDesc` |
| `+0x2D8` | active `DoorDesc *` | same |
| `+0x36C` | `MapDoorDesc` array | `evt_door_set_map_door_descs` |
| `+0x370` | its count | same |
| `+0x374` | per-zone event slots, 2 words each: `+ index*8 + which*4` | `evt_door_set_event` |

✅ **`evt_door_set_event(door, which, script)` attaches a script to a loading
zone**, which has no script field of its own. Verified by read-back — both slots
`0` before, the supplied script in slot 0 after — and the game uses it on **13**
maps.

⛔ A door's `interactScript` is **an animation step**, not the door's behaviour:
four instructions, `MULF LW(0), <float>` then an `evt_mapobj_*` transform. It
carries no branch, and running it directly changes no map.

*(D138, D140, D143.)*

---

## ✅ Enemy stats: `npcTribes`, and what a boss is made of (D151)

Two tables, both static in DOL data, both in `spm.eu0.lst`:

| | address | stride | entries |
|---|---|---|---|
| `npcEnemyTemplates` | `0x80449888` | `0x68` | 435 — behaviour |
| `npcTribes` | `0x8043BF30` | `0x68` | 535 — **stats** |

A template's `+0x14` is its **tribe id**, and `+0x2C` its flags. ✅ Both were
confirmed against the committed `npccatalog.json` for templates 255, 196 and
404 — the catalog was dumped from a running game by a different route, so this
is cross-validation rather than a self-consistent read.

`NPCTribe` is declared in `spm-headers` (MIT) and is where the numbers live:

| field | offset | type |
|---|---|---|
| `catchCardDefense` | +0x0C | s16 |
| **`maxHp`** | **+0x18** | **u8** |
| `killXp` | +0x38 | s16 |
| `coinDropChance` | +0x46 | u16 |
| `attackStrength` | +0x64 | u8 |

⛔ **`maxHp` is a `u8`, so 255 is a hard ceiling.** Not a design choice — the
field cannot hold more.

### Measured values

| tribe | | maxHp | attackStrength | killXp |
|---|---|---|---|---|
| 0 | Goomba | **1** | 1 | 100 |
| 292 | Dimentio (stg8) | 80 | 4 | 8000 |
| 305 | Count Bleck | 150 | 8 | 8000 |
| 309 | **Super Dimentio** | **200** | 6 | 9990 |

✅ Goomba at 1 HP is the positive control: a wrong offset would not land on a
plausible value for the one enemy whose stats everybody knows.

⚠️ `attackStrength` **does not set damage** — the header says it is used only by
the tattle and turn-based combat. Real damage comes from the move script (below).

### Super Dimentio's move script — where the fight actually lives

Template 255 `moveScript` is `0x8045C8C8`, decoded from the DOL:

```
     evt_npc_set_move_mode(npc, 1)
+4   evt_npc_set_part_attack_power(npc, -1, 2)   <- his damage
     evt_npc_flag8_onoff(npc, 1, 0x20000000)
     func_801072a4(npc)
     evt_npc_wait_for(npc, 500)                  <- opening delay
     DO
         <run child script 0x8045D328>           <- the attack itself
+25      evt_npc_wait_for(npc, 1000)             <- cooldown between attacks
     WHILE
```

✅ **`move`, `onhit` and `death` are UNIQUE to template 255.** ⛔ `init`
(`0x8043B8F8`) is **shared by 376 of 435 templates** — patching it would change
almost every enemy in the game. Checked by comparing pointers across the whole
table, not assumed.

### Two levers that need no instruction patch

`+8` (attack power) and `+28` (cooldown) are plain **argument words**, not
instructions. Rewriting them needs no `code.patches`: no handler prototype to
match, no VM return semantics, and no jump-table concern because nothing moves.
`mods/boss-harder` does exactly this, guarding on the two header words first.

✅ Verified in one unattended boot: `200 -> 255` HP, `2 -> 4` attack power,
`1000 -> 350` cooldown, all three guards passed, and the attract demo still ran
`aa4_01` then `ls4_12`.

⚠️ **The edits are verifiable without reaching the boss**, because they happen at
`mod_prolog` against static data. The *fight* still needs a human; the *edit*
does not.

---

## ✅ The hero's HP, and pinning it (D152)

`MarioPouchWork` (`mario_pouch.h`, MIT) carries `hp` at **+0x00C** and `maxHp`
at **+0x010**. `pouchGetPtr` (`0x8014C088`) returns the struct;
`pouchGetHp` / `pouchSetHp` / `pouchAddHp` / `pouchSetMaxHp` are all in
`spm.eu0.lst`. ⛔ There is **no `pouchGetMaxHp`** — max has to come from the
struct.

✅ **Measured `maxHp` = 10**, which is exactly what Mario starts a new file
with. That is the positive control on the offset: a wrong one would not land on
the one value everybody can check.

### Restoring HP per frame works, and was proved rather than assumed

`mods/invincible` restores HP to max every GAME frame from a `seq_data` hook.
Chosen over hooking the damage function because it **fails safe**: a missed
frame means a hit landed, never that the game hung.

⚠️ **"HP stayed at max" is what a mod that does nothing also reports.** So the
mod damages the player on purpose — `pouchAddHp(-5)` every 300 frames past
frame 600 — and checks the damage was undone. One 150-second boot:

| | |
|---|---|
| self-test hits | **107** |
| restores | **107** — every one |
| damage absorbed | **535** = 107 × 5 |
| lowest hp seen | **5** = 10 − 5 |
| hp at the end | **10** = max |

The arithmetic closing exactly is what makes this a measurement rather than an
impression: an inert mod gives 0 restores, and a mod that restored *without*
damage ever landing would show `lowest hp = 10`.

⛔ **Not death-proof.** Pits, crushes and scripted deaths do not go through
`hp`. 🔶 Only self-inflicted damage has been observed being absorbed; a real
enemy hit takes the same path in principle, but has not been watched.

---

## ✅ Super Dimentio's attack, fully decoded (D153)

His move loop runs a child script at **`0x8045D328`**. Decoded from the DOL and
named against `spm.eu0.lst`:

```
     <two unnamed user funcs: 0x801e8ed0(5), 0x801e92ac(3)>
+6   LBL 0
+8   evt_mario_get_pos(LW10, LW11, LW12)        <- where the player is
+13  evt_npc_get_position("me", LW0, LW1, LW2)
+19  evt_sub_random(300, LW3)                   <- scatter on X
+34  evt_sub_random(50,  LW4)                   <- scatter on Z
     ... arithmetic toward the player, then clamped to X +/-600, Z +/-120
+91  evt_npc_flag8_onoff("me", 1, 0x800)        <- "attacking" flag on
+96  evt_npc_arc_to("me", LW0, LW1, LW2, 2500, ...)   <- THE ATTACK: he arcs onto the player
+108 0x800fe4e8("me", 9..12, LW0, LW1, LW2)     x4, each followed by
+115 evt_eff(..., "kemuri_test", ...)           <- smoke bursts
+201 evt_npc_get_position("me", ...)
+207 evt_snd_sfxon_3d("SFX_BS_DMNL_LANDING1", ...)
+213 evt_cam_shake(5, ...)                      <- impact
+228 evt_npc_flag8_onoff("me", 0, 0x800)        <- flag off
+233 evt_npc_wait_for("me", 15)
```

✅ **The sound name confirms the reading independently**: `SFX_BS_DMNL_LANDING1`
— boss, Dimentio Large, *landing*. The `arc_to` is a leap-and-slam, not a
projectile.

### `"me"` is how a script names its own NPC

Every `evt_npc_*` call passes `0x805B4628`, which is the **string `"me"`**.
Count Bleck's script passes `0x805B4918`, a different address holding the *same*
string. So the first parameter of `evt_npc_get_position(const char *name, ...)`
is an instance name, and `"me"` is the self-reference convention — matching the
header signature exactly.

⚠️ This matters for writing a replacement: a new script can simply pass the
literal `"me"`.

### ✅ Every function it uses is already in bleck's catalog

| function | arity in catalog | arity decoded |
|---|---|---|
| `evt_mario_get_pos` | 3 | 3 |
| `evt_npc_get_position` | 4 | 4 |
| `evt_npc_arc_to` | 10 | 10 |
| `evt_sub_random` | 2 | 2 |
| `evt_cam_shake` | 6 | 6 |
| `evt_snd_sfxon_3d` | 4 | 4 |
| `evt_npc_flag8_onoff` | 3 | 3 |
| `evt_npc_wait_for` | 2 | 2 |

Eight for eight, with no disagreement — so a new attack can be **written in the
scripting language** rather than hand-assembled as bytecode.

✅ **Output parameters lower correctly.** Compiling
`evt_mario_get_pos(mx, my, mz)` with three `var`s emits `-30000000`,
`-29999999`, `-29999998` — i.e. `0xFE363C80/81/82`, the *same* local-work slot
encoding the game's own script uses at +8. Verified by compiling it, not assumed.

---

## ✅ `npcEntryFromTemplate` — spawning an NPC from code (D154)

```c
NPCEntry * npcEntryFromTemplate(NPCEnemyTemplate * enemyTemplate);   // 0x801BE198
```

✅ **The upstream declaration is correct**, checked against the code rather than
trusted — `evt_door.h`'s argc was wrong (D102), so a declaration is a hypothesis
until the disassembly agrees. It does:

```
801be1b8  mr    r29,r3        <- one argument, kept
801be1c0  lwz   r12,12(r3)    <- reads +0x0C OF THE ARGUMENT: a pointer, not an id
801be1c4  cmpwi r12,0
801be1c8  beq   ...           <- zero means "no gate"
801be1d0  bctrl               <- otherwise call it; if it returns 0, spawn fails
801be1e4  lwz   r3,20(r29)    <- +0x14, the tribe id
801be1e8  lis   r4,-32700
801be1f0  addi  r4,r4,-16592  <- r4 = 0x8043BF30
```

✅ **`npcTribes = 0x8043BF30` is confirmed a third way**: the function computes
that exact address to index the tribe. Previously it was read from the symbol
list and cross-checked against the catalog; now the code itself agrees.

### `+0x0C` is an optional spawn gate

A template may carry a predicate at `+0x0C`. If it is **zero** the spawn
proceeds unconditionally; otherwise it is called and a zero return makes
`npcEntryFromTemplate` return `NULL`.

⚠️ The committed catalog's `can_spawn` is 0 for every boss, which reads as
"cannot be spawned" and is **not** what this field means. Measured:

| template | +0x0C | |
|---|---|---|
| 103 | `0x00000000` | Super Dimentio Block Proj (his beam) |
| 197 | `0x00000000` | Bleck Small Portal |
| 198 | `0x00000000` | Bleck Large Portal |
| 255 | `0x00000000` | Super Dimentio |

🔶 So all four should spawn from code. Not yet tried.

### Pieces available for a summoned-orb attack

| | template | tribe | |
|---|---|---|---|
| the orb | **198** | 307 | `Bleck Large Portal` — the void Count Bleck opens |
| a smaller orb | 197 | 306 | `Bleck Small Portal` |
| a beam | **103** | 311 | `MOBJ_frame_beam`, *Super Dimentio's own* block projectile |

⛔ There is **no Chaos Heart entity** in the 435 templates or 535 tribes. The
portal is the closest thing the game already has to the void it represents.

---

## ✅ Map objects: the API, and where its work pointer lives (D165)

Scenery, blocks, doors and pillars are **map objects**, not NPCs, and they have
their own driver:

```c
s32          mobjEntry(const char *instanceName, const char *animPoseName);  // 0x8002B390
void         mobjSetPosition(const char *instanceName, f32 x, f32 y, f32 z);  // 0x8002B72C
MobjEntry *  mobjNameToPtr(const char *instanceName);                         // 0x8002C834
MobjEntry *  mobjNameToPtrNoAssert(const char *instanceName);                 // 0x8002C8E8
const char * mobjGetModelName(MobjEntry *mobj);                               // 0x8002EB38
void         mobjDelete(const char *instanceName);                            // 0x8002B664
```

🟢 **`mobjEntry` creates one from a model name** — the same kind of string as a
tribe's `animPoseName`. That is a second route to putting an arbitrary object in
the world, alongside the NPC model swap (D162).

### ✅ `mobjdrv_wp` = `0x805ADF10`, measured

Not in `spm.eu0.lst`. Read out of `mobjNameToPtrNoAssert`:

```
8002c90c  lwz r4,-32752(r13)   <- r13 is 0x805B5F00, so the work is at 0x805ADF10
8002c910  lwz r30,0(r4)        <- MobjWork.entryCountMax
8002c914  lwz r29,4(r4)        <- MobjWork.entries
8002c91c  lwz r0,0(r29)        <- MobjEntry.flag0
8002c920  clrlwi. r0,r0,31     <- bit 0 is "active"
8002c92c  addi r3,r29,8        <- MobjEntry.instanceName
```

✅ The offsets it uses match `mobjdrv.h` exactly — `instanceName` at +0x008,
`flag0` bit 0 active — which is a check on the read rather than a coincidence.
`MobjEntry` is `0x2a8`; `MobjWork` is `0x18`.

### 🔶 Where a Pure Heart actually is

⛔ **Not an NPC, not a global model, not an effect that renders.** It is geometry
inside `mac_12`'s (Flipside's) `map.dat`, which is undecoded. The REL bundles
carry `heart_01`, `A2_heart_01`, `A3_heart_iwa` and `pure_heart` immediately
beside `mac_12_init_evt`, with `A2_`/`A3_` being SPM's 2D and 3D layer pair.

⛔ Looking those five names up at `mac_12` with `mobjNameToPtrNoAssert` found
**none of them** — 5 tried, 0 found. 🔶 The likeliest reason is game state: a
fresh save has no Pure Hearts on Flipside's pillars, because they are placed
there as they are collected.

🟢 Next: enumerate `MobjWork.entries` and dump every live instance name and
model. That replaces guessing names with reading them, and gives `mobjEntry` a
model string that is known to exist.
