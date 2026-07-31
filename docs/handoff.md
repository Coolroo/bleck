# Handoff — picking this up fresh

Last updated 2026-07-29. A mod can now change the game's **own** content: one
instruction of a vanilla `evt` script (D89–D92) or a game C function by name
(D94–D96), both declared in `mod.json` and both refused rather than written when
the target is not what the build expected. Code mods build C++ and run it
in-game (D85, D105), and `--output riivolution` produces a patch for real
hardware instead of a 4.3 GB image (D86).

**Since then:** placements are declarable in CSV tables keyed by kind
(`enemies`, `coins`) as well as inline (D124–D126, D131); **any enemy template
can be placed in any map** and behaves normally (D127, `example-mods/mr-l`); coins
cannot be added to a map that places none, and the reason is now known rather
than guessed (D128–D130). `bleck` is **MIT** (D132).

This is the conversational context that is **not** already captured elsewhere.
For anything else:

- [`decision-log.md`](./decision-log.md) — why every choice was made (D1–D132)
- [`state-of-spm-modding.md`](./state-of-spm-modding.md) — the ecosystem.
  **Substantially revised 2026-07-27**; read the revision section
- [`scripting.md`](./scripting.md) — the scripting language, and its limits
- [`hook-points.md`](./hook-points.md) — **when custom code can safely run.**
  Two debugging cycles went into this; read it before writing a hook
- [`roadmap.md`](./roadmap.md) — what to build next and what blocks it
- [`disc-layout.md`](./disc-layout.md) — observed facts about the disc
- [`../docs-site/`](../docs-site/) — user-facing docs

---

# Where this is right now

Everything here is committed and pushed. `main` is at **1170 tests**, full
linter clean, `mkdocs build --strict` clean, and both CI workflows green.

## The headline: the Chaos Heart exists and `bleck` can spawn it

Weeks of searching concluded it did not. That was wrong, and the way it was
wrong is the useful part.

✅ **Hearts are `effdrv` effects** — a fourth entity kind, alongside NPCs, map
objects and items. Nothing enumerated them, which is why 1,687 assets, 169 MOBJ
names, 397 archives, 383 map.dat files, 435 templates and 535 tribes all came up
empty (D171).

✅ **The spawner is `0x80094E44`**, unnamed, sitting in a gap between
`effSpmHitEntry` and `effSpmSpindashEntry`. Signature
`(s32 variant, f32 x, f32 y, f32 z)`, read off the prologue. **Variant 16 is the
Chaos Heart**; 0..7 are the coloured Pure Hearts (D172).

✅ **Position is `userWork +0x10 / +0x14 / +0x18`** (D173). Verified on screen:
`example-mods/chaos-heart` drifts the heart DVD-logo style with five Pure Hearts
orbiting at 72°.

⚠️ **`chaos` is a runtime-composed name.** The `== 16` branch builds asset names
from the fragment `"chaos"`; the string `chaos_heart` appears nowhere on the
disc. **No search for the assembled name could ever have found it** — the way in
was a live `mainFunc` pointer.

⚠️ **D155 was over-generalised.** "Spawning from a sequence hook hangs" is true
of `npcEntryFromTemplate` only. Effects spawn from one cleanly.

## New tools, all offline

| Script | What it answers |
|---|---|
| `dump_effects.py` | **all 174 effects** the game can spawn, by name and entry address |
| `evtdis.py` | **disassembles the game's own evt scripts**; `--template N` lists a template's script pointers |
| `dump_builtins.py` | regenerates `docs-site/scripting/`; `--check` is what CI runs |

`evtdis.py` closed a real gap: `bleck` compiled *to* evt and had never read it
back, so every question about a vanilla script was answered from raw hex.

## Assets: Dimentio can show two of three, and one is a fragment

`bleck` now exports three manifests into one folder, and `dimentio/` (Rust,
eframe) reads them:

```bash
bleck texture export --out work/export   # 21,780 images, PNG
bleck model   export --out work/export   # 864 OBJ + models.json
bleck effect  export --out work/export   # 139 effects + effects.json
```

| | state |
|---|---|
| **Textures** | ✅ browsable, searchable, filterable by GameCube format |
| **Models** | ✅ geometry, UVs and textures — confirmed by a person in Blender |
| **Animations** | ✅ **playable**, as glTF morph targets (D217) |
| **Effects** | 🔶 structure, part durations and transform rows; **no part→image link** |

⛔ **Animation is per-vertex morphing, not skeletal** (D217). Two sessions went
into hunting a track→joint mapping that does not exist: `animPoseMain` adds
per-vertex offsets to a copy of the position array, so a key is
`[u8 vertex stride, s8 dx, s8 dy, s8 dz]`. That maps straight onto glTF morph
targets and needs no joints at all.

⚠️ **The model reading is the thing to be careful about.** The vertex format was
read off the game's own draw code (D207) and is solid; the *face and index*
reading resolves cleanly but reaches only **13.6% of a file's vertices**
(D211). Every command prints the coverage and the manifest carries
`"fragment": true`. Do not treat an exported OBJ as a character.

⛔ **Two hypotheses for the gap are already ruled out**: a per-group position
base (D214, refuted by shuffling the bases) and the size-prefixed record chain
past `0x15F5C` holding the other shapes (D212, refuted — it holds the animation
clips instead, all 80 of them). `--min-coverage 95` gives the **132 models
known to render correctly**.

⚠️ **r13 is `0x805B5F00`** (D218), so every small-data global is now
addressable by name. `xref` cannot see them — the same blind spot as D206 —
which is what hid the effect code for two sessions.

⚠️ **Nobody has looked at Dimentio's window.** This machine cannot capture its
own interactive desktop, which is exactly why the viewport is a software
rasteriser with 36 pixel-level tests behind it (D213) — but drag direction and
layout are unverified by eye.

## Entities have an onSpawn hook (D176)

`NPCEnemyTemplate+0x30` is `onSpawnScript` — documented in `spm-headers` all
along, and this repo's notes had recorded `+0x34/38/3C/48` and **missed it**.

Count Bleck's platforms come from it: `onSpawnScript 0x8046AA58` → `USER_FUNC
0x801EF744` (allocates a 780-byte work struct) → creation loop `0x801EF600`,
which `sprintf`s `LBB_%d`, uses model `MOBJ_frame_block`, and reads a position
table at `0x8045ED78` (**stride 0x34**). Fourteen platforms, x -600..600 by 300,
at y 80/160/240/320. Nothing on the disc contains the string `LBB_0`.

## Source tags (D178)

Hooks and map attachments can be declared where they live instead of in
`mod.json`:

```c
BLECK_HOOK(mapDataPtr, before)
void watchMapData(void *work) { ... }
```

```
#[map("he1_04")]
script onLineland { ... }
```

`BLECK_HOOK` is a real macro from `bleck/mods/code/include/bleck.h`, always on a
mod's include path, expanding to nothing — so the **C compiler** validates it and
a typo is a build error rather than a silently-inert tag. ⛔ A tag and a
`mod.json` entry claiming the same *game* function is a hard error naming both
sites; neither overrides the other.

`Mod.code` is the seam — call it, never `mod.manifest.code`, or tag-declared
hooks are invisible. Same shape as `Mod.tables_of`.

## Structure and rules, as of today

- `manifest/codespec.py` (695 lines) → `manifest/code/` — `specs`, `parse`,
  `patches`, `hooks`, `tags`. `codespec.py` remains a re-export shim because
  `api/v1/mods.py` imports from it. **1147 tests passed before and after**, so
  the split was provably behaviour-neutral before the feature landed.
- ⛔ **`mods/` is git-ignored** except its README (D175). D147 already said it
  ships empty and twelve probe mods were tracked there anyway; the rule is now
  enforced by git rather than by memory. Copy — do not move — a keeper into
  `example-mods/`.
- ⛔ **tree-sitter rejected** for the parser (D177): a native custom-grammar
  dependency in a project with two runtime dependencies that ships a frozen
  binary to three platforms, and it optimises for error tolerance where a
  compiler wants precise rejection. Revisit only if the GUI editor needs
  highlighting, and prefer pure-Python Lark if the grammar gets hard.
- **`docs-site/scripting/`** is a full reference; `builtins.md` and `storage.md`
  are **generated** and CI fails if they are stale.

---

## Start here

### ⚠️ Every mod this doc names lives in `example-mods/`, not `mods/`

`bleck` reads `mods/` by default (`BLECK_MODS_DIR`), and that directory is
**git-ignored entirely** except its `README.md` — it is scratch space for *your*
mods, and nothing in it is tracked (D175). Write probes there freely; copy one to
`example-mods/` when it earns a place. The ~24 worked examples and probes this
document cites are in `example-mods/`, so pass `--mods-dir`, which every command
accepts:

```bash
uv run bleck mod check mr-l --mods-dir example-mods
uv run python scripts/ingame.py coin-tick --words 12   # the rig reads BLECK_MODS_DIR
```

Without it a bare `bleck mod check mr-l` reports **"no mod named 'mr-l'"**, which
reads as a broken repo rather than a wrong path (D147). Build a *new* probe under
`mods/`; that is what it is for. ⛔ 32 older probes were deleted in D148 once
their findings were recorded here — a decision-log entry naming one is history,
not a directory you can still `cd` into.

### Four things a mod can do

**In rough order of how recently they stopped being
impossible.** Every one was verified by reading the running game's memory, and
every one has a *negative* run on record where the guard refused and the game
was left untouched.

| | Declared as | Proven by |
|---|---|---|
| Run its own script or C, on a loop, on arrival at a map, or on a button combo | `code.script`, `code.maps`, `code.combos` | D43, D46, D51, D77 |
| Make a **vanilla** script call into it — a map's init script, an item's use script | `code.patches` | D89, D90, D92 |
| Replace a **game C function** by name, or run **before** / **after** it with the original intact | `code.hooks` | D94, D95, D97 |
| **Trace** a game function without breaking it — arguments, return value, original still runs | a pattern, not a manifest key | D96 |
| Change what a map **places** — enemies in any of 100 slots, coins where the map has budget | `setup`, `tables` | D122–D131 |

⚠️ **One of those has a hole worth knowing.** An item patch has been *applied*
and never *entered* — using an item needs menu navigation and input cannot be
injected (D92).

⛔ **The paragraph that used to sit here said `code.hooks` has only
`mode: "replace"` and refuses `before`/`after` for want of a trampoline (D95).
D97 superseded it**: all three modes work, generated as a PowerPC assembly
wrapper over D96's self-healing detour. There is still **no trampoline** — and
still no way to change what the caller receives, since `before` and `after` both
return the *original's* value.

⛔ **Nothing has ever run on a real Wii.** Riivolution output exists (D86) and
Dolphin runs it, but hardware is untested, and so is Dolphin's cache model
against a real 750 (D94, D96).

There is no longer a single blocking question. Pick from
[next steps](#next-steps) below, or from
[`roadmap.md`](./roadmap.md).

### You can test without a human

This is the most reusable thing to come out of the last session.
`dolphin-memory-engine` (`pip install dolphin-memory-engine`) attaches to the
running Dolphin **process** and reads the emulated address space from outside —
no Dolphin config, no fork, stock builds. Three addresses give full visibility:

| Address | What |
|---|---|
| `0x80512360` | `seqWork` — current sequence at +0x00, stage at +0x04 |
| `0x8050C990` | `evtGetWork()`'s return. `gw[]` at +0x04, so `gw[n]` at +4+4n |
| `0x80005000` | Free scratch for a probe block (unused TRK interrupt table) |

### A hang that is really an assert will tell you why (D130)

**Reach for this before bisecting anything that freezes.** `__assert2` is in the
symbol list at `0x8019c54c`, and its call sites pass `(file, line, func, expr)`.
Hook it with `mode: "before"`, copy the four arguments into a probe block, and
the game names its own cause:

```json
"hooks": [ { "function": "__assert2", "call": "on_assert", "mode": "before" } ]
```

`example-mods/coin-nobudget` is the worked example. That technique turned "the map
freezes" into `swdrv.c:505`,
`(wp->gameCoinId - 1) < assign_tbl[i].num` in a single run, after four runs of
bisecting had only narrowed it to one byte. A frozen game and a deliberate
refusal are indistinguishable from outside, and most of this repo's freezes were
probably the latter.

⚠️ **Assert messages are Shift-JIS**, like the message files. Decoding as ASCII
throws away the sentence that explains everything —
`コインのフラグが溢れました`, "the coin flags have overflowed".

⚠️ Record a frame counter alongside it. If the hook never fires, that means
nothing unless you can show the game reached the code at all.

### Reading the DOL when the symbol list is thin

`eu0` names two setup symbols, so nothing in the item path could be looked up.
What worked (D128): find a string — an assert `__FILE__`, a `printf` format —
and cross-reference it. The game builds addresses as **base register plus
offset**, not one `lis`/`addi` pair, so a naive two-instruction search finds
nothing; a scanner that tracks register values across `lis`/`addis`/`addi` finds
all of them. `powerpc-eabi-objdump` from devkitPPC disassembles a slice of the
DOL by virtual address.

⚠️ **Gameplay is reached ~45 seconds after boot with no controller input.** The
game runs `LOGO -> MAPCHANGE -> GAME`, loading `aa4_01` then `ls4_12` — its
attract demo — and never enters `SEQ_TITLE` (D47). So a full boot-and-verify
cycle is unattended and takes about two minutes.

✅ **And you are no longer limited to those two maps** (D52). A script attached
to `aa4_01` can call `evt_seq_mapchange("he1_01", 0)` and the game goes there —
so any of the 383 maps is reachable without a controller. `example-mods/goto-map` is a
worked example.

✅ **And you no longer have to write that script** (D64). `--map he1_01` on
`bleck mod build`, or `"code": {"boot": "he1_01"}` in a manifest, generates it.
`ingame.py --map he1_01` passes it through, and the rig now prints `map=<name>`
so a boot map that worked and one that quietly did nothing look different.

✅ **The rig is now part of the repo**, after being rewritten from scratch three
times in scratch directories:

```
uv run python scripts/ingame.py my-mod --words 10 --watch-gw 30
```

`scripts/ingame.py` builds, boots, reads and always shuts Dolphin down; the mod
side is `docs/diagnostics/probe.h`. **Reach for it before debugging anything
in-game** — three rounds of asking a human to watch a screen produced two wrong
conclusions, and the rig has since settled nine questions without one.

Three things it does that are easy to miss:

| Flag | Why it exists |
|---|---|
| `--find <hex>` | Searches MEM1 and MEM2 for a byte pattern. Answers "which of these did the game load?" without knowing *how* it loads them — this is what settled D13 |
| *(automatic)* | Every run writes a full transcript to `work/build/ingame.log`. **Read that, never pipe the console through `tail`** — truncating output has already cost a whole repeat run |
| *(automatic)* | Reports a frozen game and a Dolphin that exited on its own, because silence used to mean both "nothing changed" and "it crashed" |

⚠️ **Report the *effect*, not the setup.** D51's map hook passed every
mechanical check — valid pointer, right offset, original preserved — and still
froze the game. Only a probe value showing the script had never run exposed it.

⛔ **Input injection does not work** (D48). Dolphin reads a DirectInput
keyboard, which ignores the message queue, and driver-level injection still
needs an unlocked session with Dolphin focused. Anything behind a button press
needs a human, or Dolphin's TAS movie playback, which is untried.

---

## Where the project actually is

**The asset pipeline is finished and proven** (D25, D36). A disc built by
`bleck` boots in Dolphin and renders modified textures, confirmed visually with
a two-mod dependency chain, on both Linux and Windows. Bit-exact LZ77 is not
required.

**Custom code runs in-game** (D38). A REL built by this toolchain loads via the
Gecko loader and executes correctly, verified by an unmistakable on-screen
effect. The roadmap carried "no custom code has ever run" for a long time; that
is no longer true.

✅ **And compiled scripts run** (D43). The last link closed: `_prolog` installs
`seq_data` hooks, gameplay starts the script, and every other sequence re-arms
it so a map change does not silently kill it.

**A scripting language exists** (D37). `bleck` compiles a small language to
`evt`, the game's own bytecode VM — 120 opcodes, cooperative scheduling, ~444
native builtins. No interpreter is shipped. See [`scripting.md`](./scripting.md).

✅ **Event mods work** (D51). `code.maps` runs a script on arrival at a named
map — the difference between a mod that loops and a mod that *reacts*. It
needs no C, and `bleck maps` lists every map with the chapter it belongs to.
⛔ **Repointing** `MapData.initScript` at a wrapper deadlocks the map loader;
read D51 before trying it. ✅ **Mutating the bytecode that pointer already
refers to is a different mechanism and it works** (D89) — that is what
`code.patches` does.

✅ **Code mods build C++** (D85), with static constructors walked from `_prolog`
and the `.ctors` table checked at link time — and ✅ **C++ runs in-game** (D105):
a global's constructor fired, a virtual call through a relocated vtable
returned, and sequence hooks installed from C++ kept running for 13,119 frames.

⛔ **A script that fell off its end used to hang the game** (D105, D106). Only
`END_SCRIPT` (0x01, ends the instruction *list*) was emitted, never `END_EVT`
(0x02, ends the running *entry*), so the entry stayed alive and the game stopped
a few frames later with every value the script wrote still correct. ✅ Fixed —
both are now emitted unconditionally, for **every** script, not just `main`.

pylint 10.00/10. The test count moves every session; run `uv run pytest` rather
than trusting a number written here.

### What is verified, and what is not

| | |
|---|---|
| ✅ LZ77, U8, format detection, extract/build, overlays, chains, conflicts | byte-exact on 383/383 archives |
| ✅ Asset mods boot and render | D25 (Linux), D36 (Windows) |
| ✅ A `bleck`-built REL loads and executes | D38 — the diagnostic's Signal A |
| ✅ Scripts compile to correct bytecode | hand-verified against the opcode table |
| ✅ Scripts link, resolving game functions by name | `elf2rel` + `spm.eu0.lst` |
| ✅ Our REL is byte-identical once staged | hash-checked overlay vs `work/build/` |
| ✅ `setup/*.dat` format fully decoded | all 227 files parsed, no exceptions (D42) |
| ✅ **A script runs in-game** | 60 iterations/sec, survives a map change (D43) |
| ✅ **No Dolphin cheat setup needed** | loader embedded in the disc, verified with the INI removed (D44) |
| ✅ **Native C runs in-game** | `code.sources` module executes, measured per frame (D46, D47) |
| ✅ **Every disc names itself on screen** | `mod_loaded: <name>` on the title screen, confirmed by eye (D49) |
| ✅ **A script runs on arrival at a named map** | map-specific, verified by a frozen counter elsewhere (D51) |
| ⛔ **`MapData.initScript` cannot be *repointed*** | a wrapper installs fine, then deadlocks the map load (D51) |
| ✅ **A vanilla script can call into `mod.rel`** | one instruction of `he1_01`'s init script replaced in place, map ran 90 s (D89, D90) |
| ✅ **Any instruction of two words or more is patchable** | replacement carries the original's argc and arguments through (D92) |
| ✅ **Item use scripts are reachable** | `itemEventDataTable` walked, `item:0x41` resolved and written (D92) |
| 🔶 **A patched *item* hook has never been entered** | using an item needs menu input, which cannot be injected (D48, D92) |
| ✅ **A game C function can be replaced by name** | `code.hooks`, guard derived from `main.dol`, 63,644 entries (D95) |
| ✅ **The instruction-cache flush is necessary, not ceremonial** | a no-flush control read back the new word and ran the old body (D94) |
| ✅ **`before` and `after` run with the original intact** | generated asm wrapper; `beforeSaw=0` vs `afterSaw=0x901D6248` told the modes apart (D97) |
| ⛔ **Still no trampoline** | interception restores/re-installs instead — two cache flushes per call (D97) |
| ⛔ **More than eight integer arguments cannot be intercepted** | they live in the caller's frame; not checked and cannot be (D97) |
| ✅ **A function can be traced with the original still running** | restore, call, re-arm — `effMain` through four map changes (D96) |
| ✅ **Door scripts are reachable, and `door:` ships** | `door:<map>:<index>[:interact\|init\|move]` resolved and APPLIED in-game; word 0 `0x0002003C` → `0x0002005C`, word 2 untouched (D103, D104). ⛔ D91 ("needs interception, not a lookup") and D93/D94 ("unreachable") are all superseded — the setters take **argc 3**, not the argc 2 `evt_door.h` declares (D102). 🔶 The hook has never been *entered* |
| ⚠️ **`spm-headers` can be simply wrong** | `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)` contradicts the comment above it and the game; it cost two decision entries (D102). A load-bearing argc, offset or size from a header is a hypothesis 🔶 until measured |
| ✅ **C++ code mods build** | `.ctors` survives `-r --gc-sections` and elf2rel; markers checked at link (D85) |
| ✅ **A C++ code mod runs in-game** | a global's ctor fired (`0x0C70FA11`, `.bss` would read 0), a virtual call through a relocated vtable returned `0x1234`, 1 constructor counted, 13,119 SEQ_GAME frames (D105) |
| ✅ **A `switch` takes the right arm in-game** | `case 3` wrote `0x33`, the `else` arm `0xDD`; each arm writes a different value and 3 is not the first case, so first-arm-always could not pass (D105) |
| ⛔ **A script that simply ended hung the game** | `END_EVT` was emitted only for an explicit `return`, so the entry outlived the script (D105, D106). Fixed; both terminators now always emitted |
| ✅ **Riivolution output boots in Dolphin** | loader travels in the patched `main.dol`; negative isolates one XML element (D86) |
| ⛔ **Nothing has run on real hardware** | every runtime claim here is Dolphin's (D86, D94, D96) |
| ✅ **`.env` is loaded automatically** | tool paths survive between shells; real env still wins |
| ⛔ `SEQ_TITLE` is never entered | zero frames unattended; there is no menu to hook (D47) |
| ⛔ Input cannot be injected | DirectInput plus a locked session (D48) |
| ✅ **The game reads the *standalone* `files/setup/*.dat`** | ⚠️ D53 concluded the opposite; D62 settled it by giving each copy a different enemy and seeing which spawned |
| ✅ **Any map is reachable unattended** | `evt_seq_mapchange` from a map hook (D52) |
| ✅ **A disc can start itself in any map** | `--map` / `code.boot`, confirmed in game (D64) |
| ✅ **A button combination runs a script** | `bleck.yml` + `code.combos`, played by hand (D77) |
| ✅ **A mod can read the controller** | `wpadGetWork`; D48 was about *injecting*, not reading (D66) |
| ✅ **The four face-button masks** | a=0x0800 b=0x0400 1=0x0200 2=0x0100, one press each (D68) |
| ⚠️ **The rig's map field was wrong until D76** | it read `seqWork.p0`; four entries were retracted |
| ⛔ **`SEQ_LOGO` cannot be cut short** | black screen after the controller warning (D65) |
| ⛔ **Emulation speed cannot be restored mid-run** | `--fast` uncaps the whole session (D64) |
| 🔶 Only `eu0` has been booted | other versions compile, untested |

---

## Setup you will need

### Environment variables — copy `.env.example` to `.env`

`bleck` loads the nearest `.env` automatically, from anywhere inside the
checkout, so there is nothing to source and no need to export anything per
shell. Only `BLECK_*` names are read from it, and the real environment still
wins — a one-off `BLECK_DOLPHIN=... uv run bleck ...` overrides the file.
It is gitignored; `.env.example` documents every setting.

```ini
# .env
BLECK_WIT=C:\Users\Wyatt\tools\wit\bin\wit.exe
BLECK_DOLPHIN=C:\Users\Wyatt\tools\dolphin\Dolphin.exe
BLECK_WSTRT=C:\Users\Wyatt\tools\szs\szs-v2.42a-r8989-cygwin64\bin\wstrt.exe
```

Backslashes are taken literally, so Windows paths need no escaping.

⚠️ **This exists because `$env:` does not persist between shells.** Two sessions
were lost to that, and both `wit` and `Dolphin` had to be found by searching the
filesystem afterwards. `setx` also works and survives reboots, but it is
per-machine rather than per-checkout, and it will not tell the next person which
variables matter — `.env.example` will.

### Symbol lists — required for code mods, not shipped

Compiling a script needs `spm.eu0.lst` from
[spm-headers](https://github.com/SeekyCt/spm-headers) (`linker/`). `bleck` does
not vendor it, deliberately — see "Licensing" below.

✅ It now lives at `work/symbols/spm.eu0.lst`, which is where
`BLECK_SYMBOLS_DIR` defaults to, so no environment variable is needed for it.

Anchor to **eu0**. Coverage varies sharply: `spm.eu0.lst` carries 1,111 entries,
`kr0` only 456. ⚠️ `code.hooks` resolves its `function` against this same list,
so it is now load-bearing for more than scripts.

⚠️ **There is a much better source** (D39), though it **cannot be vendored** —
`spm-decomp` states no licence (D54), so read a user-supplied clone:
`spm-decomp/config/EU0/symbols.txt`
carries ~9,566 human-named symbols — **11x** the lst — with sizes and types, and
parses with one regex. Switching to it is on the next-steps list.

### Dolphin — the two silent traps, now avoidable

✅ **`bleck` embeds the loader into the disc** (D44), so neither trap below
applies any more. Verified with `R8PP01.ini` moved aside entirely. It needs
`wstrt` (Wiimms SZS Toolset, a separate download from `wit`) and a codelist at
`work/gecko/loader.eu0.txt`; without them the build warns and continues.

The old path, for reference — both fail *invisibly* if misconfigured:

1. `User/GameSettings/R8PP01.ini` must contain the Gecko loader under **both**
   `[Gecko]` **and** `[Gecko_Enabled]`. Listed once, it never runs.
2. `Config/Dolphin.ini` must have `EnableCheats = True` under `[Core]`. Dolphin
   reads codes regardless and simply does not apply them — indistinguishable
   from a broken mod. A fresh install has no `[Core]` section at all, since
   Dolphin only writes non-default settings.

The loader code itself is GPLv3 and lives in Dolphin's config, **not** in this
repo.

⚠️ **That INI is back in place on this machine and is enabled** (found during
D86). It means a mod can run on this host even when the DOL carries no loader,
so any run that seems to confirm an embedded loader is confounded until
`%APPDATA%\Dolphin Emulator\GameSettings\R8PP01.ini` is moved aside. Two D86
runs were re-done for exactly this reason.

### Riivolution output (D86)

`bleck mod build <mod> --output riivolution` writes a patch and only the changed
files — seconds and megabytes instead of minutes and gigabytes — and
`scripts/ingame.py --riivolution` boots it through the same rig. See
[`hardware.md`](./hardware.md).

### Toolchain

devkitPPC is installed at `C:\devkitPro\devkitPPC` — GCC 16.1.0, target
`powerpc-eabi`, `--with-cpu=750`, newlib. Both `powerpc-eabi-g++` **and**
`powerpc-eabi-gdb` are present, so C++ works here where it did not on the Pi,
and Dolphin has a GDB stub if source-level debugging is ever wanted.

---

## What is not in git, by design

| | Notes |
|---|---|
| `work/roms/` | Disc images. Gitignored. Supply your own. |
| `work/extracted/eu0` | The PAL rev 0 base. Regenerate with `bleck extract`. |
| `mods/*/overlay/` | Gitignored — extracted game assets, and generated `mod.rel`. |
| `work/build/`, `out/` | Staging and images. Regenerable. |
| Upstream clones | `spm-headers`, `spm-rel-loader` in scratch. Re-clone as needed. |

**Committed mods look empty and that is correct.** `example-mods/title-invert` and
`example-mods/tex-koopa` have manifests but no overlays. Re-vendor:

```powershell
bleck mod vendor title-invert lyt/title.bin.uk/arc/timg/mario.tpl
bleck mod vendor tex-koopa    lyt/title.bin.uk/arc/timg/koopa.tpl
```

Then invert pixel data from `0x40` to the end of each — script in
[`../docs-site/guides/first-mod.md`](../docs-site/guides/first-mod.md).

**Script mods are different**: `example-mods/speedrun` and `example-mods/coin-tick` commit their
`scripts/*.evt` source, and the compiled `mod.rel` is regenerated by
`bleck mod build`. Nothing to re-vendor.

---

## Open decisions, carried forward

1. **Licensing.** `bleck` is still **unlicensed**, which technically means
   all-rights-reserved while `docs-site` tells users to clone it. This needs
   settling before any release.

   ✅ **Upstream attribution is now done** (D54): `README.md` credits every
   project `bleck` builds on, verified against each repository. Two assumptions
   turned out wrong — `spm-headers` has no `LICENSE` file but *is* MIT for
   `include`/`decomp`/`linker` (and GPLv3 for `mod/`), while `spm-decomp` from
   the same author states no licence at all.

   ⚠️ **It no longer blocks the code track.** D37 changed that: scripts name
   game functions and `elf2rel` binds them at build time, so `bleck` vendors no
   upstream material and hardcodes no addresses. The roadmap's claim that
   licensing "blocks everything else here" is superseded.

   Also corrected in D37: **`spm-rel-loader` re-bundles the MIT headers under
   its repo-wide GPLv3 `LICENSE`.** Take headers and lsts from `spm-headers`
   (MIT), never from `spm-rel-loader`.

2. **One code mod per disc.** The Gecko loader opens exactly one `/mod/mod.rel`.
   `bleck` fails loudly, naming both mods, rather than silently dropping one.

   ⚠️ **Corrected by D39: `chainrel` is not the answer.** It is a three-commit
   stub whose loader body is wrapped in `#if 0`, and nobody in this scene has
   solved multi-mod loading. Our behaviour matches the state of the art. See
   the "unclaimed problem" item under next steps.

2. **Rust rewrite** — deferred. The case rests on distribution and compressor
   speed. Revisit after the code track lands; a PyO3 port of just the compressor
   captures most of the benefit at a fraction of the risk.

3. **Hot reload** — designed for, not built. D37 records the reasoning and the
   verified facts (Riivolution re-reads host files on every disc read; SPM links
   `DVDMgrOpen`/`Read`/`Close`). Estimated 1–3 days. ⛔ Reloading a rebuilt REL
   is ruled out: there is no `OSUnlink`.

---

## What is not done

Ordered by value. Anything closed has been removed — the decision log is the
record of what was finished and why.

### The boss work

1. **The attack is built from effects, and effects do not hit the boss hang**
   (D183). `chaos-heart` orbits five `robo_beam`s around the Chaos Heart; 22,350
   frames, no freeze, where the boss *NPC* froze at a fixed ~2,177 (D157). 🔶 The
   remaining question is whether the NPC-path hang is what stands between this
   and a real Count Bleck fight — the effect path sidesteps it rather than
   explaining it.

### Assets — textures done, models not started

2. ✅ **Texture edits are declared, not baked** (D187, D193). `tables/textures.csv`
   names a disc path and a colour operation; the build reads the texture from
   the user's own disc and rewrites it in the CMPR endpoint domain, so a rebuild
   costs no quality. `bleck mod pack tex-koopa` ships two files and no game
   bytes. ⛔ **Tier 2 — replacing artwork — needs a real DXT1 encoder** and is
   not started; everything today is exact *because* it never re-compresses.
3. 🔶 **`effdata.dat`: 2 of 16 sections read** (D190, D191). 139 effects, 704
   parts, 4,048 transform rows — and `chaos` holds an exact 72-degree rotation,
   matching the five-fold ring measured in game. ⛔ **The part-to-texture link
   is still missing**, and the obvious candidate is refuted. Nine sections
   remain, none with any strings.
4. ⛔ **The model container is unidentified.** `a/p_wii_mario` announces a Jan
   2007 Maya export and skinned shape names and decodes to nothing; `map.dat`
   names its sections (`mesh`, `animation_table`, `vcd_table`). A string table
   is not a mesh. This blocks Dimentio's 3D stages
   ([`plan-dimentio.md`](./plan-dimentio.md)).

### The language

5. **`peek`/`poke` for `SET_RAM`/`GET_RAM`.** The biggest remaining gap.
   ⚠️ Maps did **not** need it (D51) and doors do **not** (D103) — read D51
   before assuming NPCs will.
6. **Emit `SETI` instead of refusing ambiguous literals** (D39). `var a =
   -30000000` is a compile error and need not be.
7. **`IF_FLAG`, detached `spawn`, `SET_PRI`/`SET_SPD`.** Unwritten, not blocked.
   ⚠️ `RUN_EVT` is emitted nowhere, so `spawn` starts from scratch — and
   D184 measured the consequence: a spawned script's **parent waits for
   it**, so `spawn` cannot currently isolate a call that never returns.
8. **Switch to the decomp's symbol table** (D39): ~9,566 named symbols against
   `spm.eu0.lst`'s 1,111, with sizes and types, so hook targets could be
   *validated* rather than merely resolved. ⚠️ It states no licence (D54), so it
   stays a local convenience and nothing derived from it ships.

### Toward the base app

9. **More editing surfaces through the API.** The map archive is the prize and
   is **not decoded** — research before it is an editing problem.
10. **A GUI over the API.** Any language; the contract is JSON and the schema is
   published.
11. 🔶 **Speed, if profiling names it.** LZ77 is ~12 s/MB (D16). The recorded
    answer is a PyO3 port of *just the compressor* — not a rewrite.

### Needs a human, once

12. **A save state.** Driving into a map leaves Mario invisible: no save, no
    profile (D63). `--state` exists on `bleck launch` and `ingame.py`; making
    one needs someone to play far enough and press F1.
13. 🔶 **`plus`/`minus`/`home`/d-pad masks** — one `button-probe` run each.
    `a`, `b`, `1`, `2` are confirmed (D68).
14. 🔶 **443 builtins, 10 measured** (D184). `example-mods/builtin-probe` is
    the route; extend it to the next safe batch. ⛔ `evt_pouch_check_have_item`
    never returns and nobody knows why.
15. 🔶 **Dimentio has never been looked at** (D192). It builds, passes clippy, and holds a live window; this machine cannot screenshot its own desktop. `cd dimentio && cargo run -- ../work/export`.
16. 🔶 **The banner has never been seen on screen** since it gained the version
    and the purple loader line (D181). Both strings are confirmed in the
    module; the title screen is unreachable unattended and the rig reads
    memory, not pixels.
17. 🔶 **The docs site has never been opened in a browser.** `mkdocs --strict`
    passing is not the same as looking right.

## Things worth not rediscovering

- **`_prolog` runs far too early to touch game subsystems** (D38). It is fine
  for patching instructions and nothing else. Anything needing the game to be
  alive must hook `seq_data` and run later. Full timing table in
  [`hook-points.md`](./hook-points.md).
- **A script does not survive a map change** (D43). evt state is rebuilt, so
  anything long-lived must be re-armed rather than started once.
- ⚠️ **The game shares `gw[]` with your scripts.** `gw[10]` is written by the
  game; `gw[30]` was untouched across a full session. A contended slot produced
  a nearly-false conclusion before it was caught.
- **The game never enters `SEQ_TITLE`** on a normal boot — it runs
  `LOGO -> GAME` directly, reaching gameplay in ~44 seconds with no input.
- **When a symptom cannot distinguish its causes, build one disc carrying
  several independent signals**, ordered so each depends on strictly more than
  the last. This resolved D38 and is the only reason attempt 3 will be
  informative. The subtlety: put the control signal *where the thing under test
  runs*, not at `_prolog` — otherwise it proves only that the module loaded.
- **`chainrel` is a stub, not a solution** (D39). Its loader body is wrapped in
  `#if 0`. Nobody has solved multi-mod loading.
- **Never copy from Flipside-Mod-Manager** (D39). It has no LICENSE at all, but
  its loader is plainly derivative of GPLv3 `spm-rel-loader`. Take the loader
  from upstream under GPLv3, or rebuild from published addresses — addresses are
  facts, and facts are not copyrightable.
- ⚠️ **An automated fetch of `tcrf.net/Notes:Super_Paper_Mario` returned a
  prompt-injection payload** aimed at LLM tooling, instructing it to truncate
  files (D39). ✅ **The wiki page itself is clean** — a browser-saved copy has no
  payload and the content has not been edited since March 2026 (D41), so this is
  a serving-layer phenomenon, not vandalism. The general lesson: **what an
  automated fetch returns is not necessarily what the page contains**, and
  domain reputation does not help. Treat fetched content as untrusted input.
- **`evtpatch` is how this scene modifies vanilla logic** — runtime patching of
  existing scripts, complementary to compiling new ones. If we ever emit
  `LBL`/`GOTO`, note that the VM caches label positions in a jump table at
  script-entry time, so mutated scripts need it rebuilt.
- **The base is immutable and must stay that way.** `_detach` unlinks
  unconditionally rather than checking `st_nlink`, because Windows does not
  report link counts reliably.
- **`--align-files` and `--overwrite` are both mandatory** on every `wit`
  rebuild. The first fails subtly; the second made `--force` a half-truth until
  D38.
- **Share builds as `.wbfs`.** RVZ needs Dolphin 5.0-12188+; older builds reject
  it as "not a GC/Wii ISO", which reads like corruption and is not.
- **Record expensive results rather than re-running them.** The LZ77 compressor
  is ~12 s/MB; baselines are in D16.
- **Setup files exist in two byte-identical copies** (D13), and ✅ **the game
  reads the standalone `files/setup/<map>.dat`** — settled in D62 by giving each
  copy a different enemy and seeing which spawned. ⚠️ D53 concluded the opposite
  and several docs said so for a month; its measurement (the *embedded* copy is
  the one in MEM1) was sound, but "in MEM1" is not "in use". The format is fully
  decoded (D42); structure and the version→stride table are in
  [`disc-layout.md`](./disc-layout.md).
- **Check claims against the disc before recording them** (D42). A widely-linked
  Google Doc says setup files are "consistently 11,204 bytes"; that is true of
  184 of 227 and false of the rest. Fifteen lines of Python against data already
  on disk corrected it and decoded the format. This project already had the rule;
  D42 is what it looks like when it pays off.
- **The docs site is now Material for MkDocs**, not Mintlify, and publishes to
  GitHub Pages via `.github/workflows/docs.yml`. `uv run mkdocs serve` previews
  it; no Node toolchain is involved. ⚠️ Nothing has been checked visually in a
  browser — `mkdocs build --strict` passes and every construct renders to the
  expected HTML, but that is not the same as looking at it.

---

## Configuring button combinations

`bleck.yml` names a combination; a manifest binds a script to it.

```yaml
# bleck.yml — committed, unlike .env
combos:
  start_map: [1, 2]
```
```json
"code": { "boot": "he1_01", "combos": { "start_map": "warp_home" } }
```

Boot maps and combinations work together (D77), which four decision-log entries
had claimed otherwise.

## ⚠️ Read this before trusting the rig

**Six runs and four decision-log entries went into a bug that did not exist**
(D70, D73, D74 — all retracted by D76). Every one was internally consistent,
had a control, and bisected cleanly, because the instrument was wrong in the
same direction every time.

The cause: the rig read the current map from `seqWork.p0`, which only means
anything *while* a map change is running. Between changes it holds stale data,
so **a run that changed maps looked identical to one that did not**.

Fixed — it now reads `seq_mapchange_wp->mapName` (`0x805AE0A8`, `+0x20`), which
survives the transition.

### The rules that came out of it

1. ⚠️ **Before trusting a negative result, show the instrument can produce a
   positive one.** No run ever asked "can this rig see a map change I already
   know happened?" The attract demo moves `aa4_01 -> ls4_12` unaided; that was
   always available as a positive control.
2. ⚠️ **A control does not help when it is measured with the same broken ruler.**
3. ⚠️ **Prefer the two-line test to the new tool.** D71 built a whole new script
   to read a bound address, correctly, to answer a question that did not matter.
   Adding one `gw` write would have been more discriminating and took minutes.
4. ⚠️ **"Works by eye, invisible to the rig" is a finding about the rig.** That
   discrepancy was visible from D64 and went unremarked for a day.

### What the rig gained

| Flag / behaviour | Why |
|---|---|
| refuses to start if another Dolphin is open | an idle instance makes every read fail and looks like a broken mod |
| reports *why* a read failed | silence used to mean four different things |
| `map=` from `seq_mapchange_wp` | see above |
| `--press a b 1+2` | presses buttons; `+` holds them together |
| `--press-at`, `--press-gap` | press after a boot map lands, and space presses so each is observable |

⚠️ `scripts/keys.py` synthesises input and **must stay out of the `bleck`
package** — `tests/test_boundaries.py` enforces it. It is reasonable for a
harness driving an emulator on its own operator's machine, and not something a
modding toolkit should ship to strangers.

⚠️ Attended only: Windows refuses `SetForegroundWindow` to a background process
and `AttachThreadInput` does not get around it. The script waits for a click
rather than zeroing `SPI_SETFOREGROUNDLOCKTIMEOUT`, which would disable focus
protection system-wide and outlive the process.

---

## Code mods — the three warnings worth carrying

Design detail lives in [`code-mods.md`](./code-mods.md) and
[`plan-merging.md`](./plan-merging.md). These are the parts that have bitten:

- ⚠️ **The cache flush is necessary, not decorative.** A store lands in the data
  cache and the instruction fetcher cannot see it. Two identical patches
  differing only in `dcbst`/`sync`/`icbi`/`isync` read back the same word and
  behaved differently — the unflushed one did nothing while looking applied.
- ⛔ **A branch written on its own destroys the original body.** Keeping the
  original means restoring the instruction around the call (D96), which
  `mode: "before"`/`"after"` generates for you (D97). ⛔ **A trampoline is still
  not built**, and upstream's `hookFunction` is not a drop-in — it blindly
  copies instruction[0] (D37).
- ⚠️ **Intercept wrappers are generated PowerPC assembly**, not C
  (`emit/runtime_intercept.py`). A hook is resolved from a symbol *name* and
  nothing carries a signature; a C wrapper would have to guess one, and an
  integer guess silently drops float arguments, which the EABI passes in
  `f1-f8` separately from `r3-r10`. **A handler's prototype must match the
  target exactly and nothing can check it.**
- ⚠️ **Merging happens at compile time** (D78), because the Gecko loader opens
  exactly one `/mod/mod.rel`. Runtime chaining is unsolved and not on this path.

## The JSON API — how a GUI will talk to this

**`bleck/api/` is the contract other programs integrate against.** The CLI
prints for people; this is for tools. A GUI cannot shell out to
`bleck mod build` on every keystroke.

```bash
bleck setup show <map> --json      # what a map places, names resolved
bleck setup edits <mod> --json     # what a mod declares about placement
bleck setup apply <mod> --json -   # write it back; - is stdin
bleck mod export <name>            # a whole mod: identity, deps, code, setup
bleck mod import <name> --json -
bleck mod schema                   # JSON Schema for the above
```

An entire edit loop without touching `mod.json`:

```bash
bleck mod export hard-lineland | your-tool | bleck mod import hard-lineland --json -
```

### The four decisions inside it

⚠️ **It is a wire format, deliberately separate from `bleck/mods/manifest/`.**
The manifest is what a mod *declares* — tuned for being hand-edited and
reviewed. The API is what a program *exchanges* — tuned for being unambiguous.
Keeping them apart means the file format can change without breaking
integrations. The conversions are round-trip tested against every real mod in
the tree, because an editor that cannot re-open what it wrote is a converter.

⚠️ **Reading and editing are different shapes.** `show` returns every slot;
`edits` returns only what a mod changes. Sending a read back as edits would
rewrite a hundred slots to change one, and lose the difference between "left
alone" and "deliberately set to what it already was".

⚠️ **Versioned twice.** `api_version` rides inside each top-level document, so
one written to disk or pasted into a bug report still says what it is — a
schema is not always to hand. `bleck.api.v1` versions the *code*, so a v2 can
be added beside v1. `bleck.api` re-exports the current version; pin to
`bleck.api.v1` to break loudly instead. Nested models carry no version; they are
never exchanged alone.

⚠️ **`apply`/`import` replace, they do not merge.** Merging needs a rule for
"the document omits a field — clear it or keep it?", and either answer surprises
half of callers. An editor holds the whole document anyway.

**Overlay files are not in the API.** A mod's overlay is extracted game assets —
binary, large, already on disk. An editor lists them from the filesystem.

### Why pydantic

`bleck mod schema`. The schema and the parser are the same declaration, so they
cannot drift. That is the thing a hand-rolled JSON layer never gets right.

⚠️ pylint cannot see through pydantic's descriptors and reports every field as a
`FieldInfo` with no members. `pylint-pydantic` is loaded in `pyproject.toml`
rather than scattering `# pylint: disable=no-member` as the API grows.

---

## Distribution: a binary, and CI that checks it

`pyinstaller bleck.spec` produces **one ~15 MB executable, no Python needed**.
`.github/workflows/build.yml` builds it for Linux, Windows and macOS on every
change and runs the same `pytest` and `lint.py` a contributor runs.

### ⚠️ The two packaging traps, both already hit

1. **The four JSON catalogs are found with `Path(__file__).with_name()`**, so
   they must be bundled at paths mirroring the package. Get it wrong and the
   binary starts happily and then reports an *empty* catalog — which reads as a
   corrupt install rather than a build bug.
2. **`__main__.py` must use an absolute import.** PyInstaller runs it as a
   top-level script, where `from .cli import ...` fails with "attempted relative
   import with no known parent package" — a message that says nothing about
   packaging.

CLI command modules are collected explicitly in the spec: nothing references
them by name, and PyInstaller follows imports rather than intentions.

### `scripts/smoke_binary.py` is the step that matters

**A PyInstaller build that *builds* proves almost nothing.** Every failure above
produces a working-looking binary. The smoke test runs six checks against the
artifact, each covering a different way packaging breaks rather than a different
feature, and needs no extracted disc — so it runs on a machine that has never
seen the game.

✅ **The build workflow runs and is green on all three platforms** (D83) — which
also caught that the smoke test could never have failed where it was originally
run. 🔶 **The tag-triggered *release* job has still never run**, and
`upload-artifact` drops the exec bit (D81). `macos-latest` is arm64, so that
artifact is Apple Silicon only.

---

## Runtime dependencies, and why each exists

`bleck` had none by design for a long time. It now has two, each argued:

| | For | Reversible? |
|---|---|---|
| `pyyaml` | `bleck.yml` — hand-editable config wants comments, and YAML is not a format worth hand-rolling | Yes, at the cost of a worse format |
| `pydantic` | The JSON API: validation, both directions, and a published schema from one declaration | Not really — it is the API's shape |

⚠️ The install docs claimed "no runtime dependencies" for a while after this
stopped being true. If a third is ever added, check that page.

---

## Known gaps

- 🔴 **US (`us0`) support is blocked on a US disc image.** `work/extracted/`
  holds `eu0` only.
- ⛔ **Hardware.** Riivolution output is built for a Wii and has only ever run
  in Dolphin (D86), as has every cache-flush result (D94, D96).
- 🔶 **54 builtins remain unlinkable** (D61): 21 live in the game's own REL at
  REL-relative addresses, 33 have no known address anywhere.
- 🔶 **`npcdrv:` is research, not a feature** (D107). NPC behaviour scripts are
  real evt bytecode readable from a live `NPCEntry`, but nothing carries them at
  `mod_prolog`, so no selector exists. ⚠️ Superseded in part by D176:
  `onSpawnScript` **is** a plain template field at `+0x30`, so the spawn path is
  reachable even though the live-entry path is not.
- 🟢 **Licensing is deferred.** It blocks sharing and nothing else, and must be
  settled before the first release.

## Reaching the game's own scripts

`code.patches` replaces one instruction of a vanilla `evt` script with a call
into the mod, **same size only** — the replacement carries the same argument
count, so no label moves and `jumptable[]` stays valid. Selectors:
`map:<name>`, `item:<id|name>`,
`door:<map>:<index>[:interact|init|move]`. `code.replace` swaps a whole script
by pointer instead.

Full reference: [`code-mods.md`](./code-mods.md) and
[the manifest reference](../docs-site/reference/manifest.md).

- 🔶 **A patched *item* hook has never been entered.** Using an item needs menu
  input, which cannot be injected (D48, D92).
- ⚠️ **`spm-headers` is not ground truth.** `evt_door.h`'s macro declares the
  wrong argc; its own comment was right (D102).
- ⛔ **`npcdrv:` selectors do not exist.** Script pointers are fields on a live
  `NPCEntry` copied in at spawn, so nothing carries them at `mod_prolog` (D107).
  ✅ But `onSpawnScript` is a plain template field at `+0x30` (D176), so spawn
  behaviour *is* reachable — that is how Count Bleck builds his platforms.

## ⚠️ Methodology, earned the hard way

**Five instrument errors in two days**, and every one was caught by
**cross-run agreement** — a value measured by a different probe, in a different
run, by a different route. Internal consistency caught none of them.

1. **A correct measurement of the wrong place.** D93 searched one function at
   one argc; D94 hooked a function in maps that do not call it; D107 read
   `entries[0]`, an unused slot. ⚠️ **The attract demo reaches only `aa4_01` and
   `ls4_12`, and neither has NPCs or the doors that mattered.** Use
   `--map <name>`.
2. **A probe gated on something that never happens.** `SEQ_TITLE` never occurs
   in an unattended boot, so an entire instrument sat behind a dead branch and
   reported a null pointer as though it had been read.
3. **An early return leaving zeros**, indistinguishable from reading zeros.
   Report the pointer as a sentinel.
4. **A field overwritten by another** (`STATUS(3)` collided with
   `GAME_FRAMES`).
5. **A hand-reformatted dump shifted one word** — every offset wrong, every one
   self-consistent, and the stride derived from the same dump cancelled the
   error out.

**The rule these converge on: a probe must report the precondition it depends
on, not just the value it went looking for.** And prefer searching for
*already-measured values* over guessing a struct layout — that is what made
D110 cheap and D111 wrong.

⚠️ Two more, not instrument errors but the same family: `spm-headers` is
**not ground truth** (`evt_door.h`'s argc is simply wrong, D102), and a
pydantic field's docstring is **published** into `bleck mod schema`.

## Standing traps

- ⚠️ **Editing code by string replace or regex fails silently.** Use the `Edit`
  tool, which errors instead. This has corrupted `codespec.py` twice and
  `tests/test_tags.py` once.
- ⚠️ **Capture output to a file; never filter raw stdout.** `tail` has hidden
  the one line naming a failure more than once. Redirect to
  `$CLAUDE_JOB_DIR/tmp/`, then read slices — re-reading is free, re-running is
  not.
- Generated C must be **pure ASCII**; an emoji in a comment fails the build.
- Console output must be ASCII too — Windows is cp1252 and an emoji raises
  `UnicodeEncodeError`.
- `runtime_c.py` keeps approaching pylint's 1000-line limit.
- Script comments are `--`, the default arm is `else`, and `gw` is
  `GW(0)..GW(31)`.
- An idle Dolphin window breaks `ingame.py`; the memory reader may attach to it.
  `example-mods/nop` exists so a stock-behaviour disc can boot on this host,
  which runs the REL loader as a Gecko cheat.
