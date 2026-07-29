# Roadmap

The destination is in [`vision.md`](./vision.md) — a full editor, GUI
included. This is the order of getting there.

What to build next, why in this order, and what is blocking what.

Reasoning behind past choices lives in [`decision-log.md`](./decision-log.md);
this file is forward-looking only.

**Legend:** 🔴 blocked · 🟡 needs a decision · 🟢 ready to start

---

## Where things actually stand

| Area | State |
|---|---|
| LZ77, U8, format detection | ✅ Verified, byte-exact repacking on 383/383 archives |
| Disc extract / build (ISO, RVZ, WBFS) | ✅ Working |
| Mod overlays, dependency chains, conflicts | ✅ Working, validated on the real game |
| **Asset pipeline end to end** | ✅ **A built disc boots and renders mods** — on Linux (D25) and Windows (D36) |
| PowerPC toolchain | ✅ Proven — builds a valid REL (D26) |
| **Custom code runs in-game** | ✅ **Confirmed** (D38) — a `bleck`-built REL loads and executes |
| **Scripting language** | ✅ **Working end to end** — compiles, links, and runs in-game at 60 iterations/sec, surviving map changes (D37, D43). `switch`/`case` lowers onto evt's own `SWITCH`…`END_SWITCH` (D84), ✅ and takes the right arm in-game — `case 3` and the `else` arm each wrote their own value, so a first-arm-always lowering could not have passed (D105). ⛔ **A script that fell off its end used to hang the game**: only `END_SCRIPT` was emitted, never `END_EVT`, so the entry stayed alive (D106). Fixed, and `tests/test_script.py::TestTermination` asserts the property the VM imposes rather than what the compiler emits |
| **Native code mods** | ✅ **Working** — `code.sources` compiles C into the same module and it runs in-game (D46, D47) |
| **C++ code mods** | ✅ Builds — `.cpp`/`.cc`/`.cxx` alongside C, `-fno-exceptions -fno-rtti -std=gnu++17`, static constructors walked from `_prolog` and the `.ctors` table checked at link (D85). ✅ **Runs in-game** (D105): a global's constructor fired, a virtual call through a relocated vtable returned, and sequence hooks installed from C++ kept running for 13,119 frames. ⚠️ Four runs blamed C++ for D106's freeze before a pure-C control cleared it |
| **Riivolution output** | ✅ `--output riivolution` writes an XML plus only the changed files — 5.3 MB and 3.2 s against minutes for an image (D86). The loader travels inside the patched `main.dol`, so nothing has to be configured in the emulator. 🔶 **Dolphin only; never run on a Wii** |
| **Event mods** | ✅ **Working** — `code.maps` runs a script on arrival at a named map (D51) |
| **Patching the game's own scripts** | ✅ `code.patches` replaces one instruction of a vanilla `evt` script with a call into `mod.rel` (D89, D90). Same-size, but **any** size from two words up, and `item:<id>` as well as `map:<name>` (D92). ✅ `door:<map>:<index>[:interact\|init\|move]` too (D103, D104) — `DEFERRED_PATCH_KINDS` is now empty. 🔶 Neither an item nor a door hook has been seen *entering* |
| **Patching the game's own code** | ✅ C helpers write a PowerPC branch and flush it correctly; measured against a no-flush control that did nothing (D94). ✅ `code.hooks` declares one, with a guard word derived from `main.dol`; positive and negative runs (D95). ✅ **All three modes** — `replace`, `before` and `after` — via a generated PowerPC **assembly** wrapper per intercepting hook (D97); `before` and `after` both return the *original's* value. ⛔ Still **no trampoline**: interception reuses D96's self-healing detour, so it pays two cache flushes per call. ✅ A mod can also keep the original by hand-restoring it around the call: arguments **and** return values, `mapDataPtr` and `effMain` traced live (D96) |
| **Tracing a game function** | ✅ The self-healing detour records arguments **and** return values while the original still runs — `mapDataPtr`, `effMain` and `GetBasicPlayer` measured live (D96). Hand-written tracing is still a pattern over `code.hooks`, deliberately **not** a manifest field; `mode: "before"`/`"after"` (D97) covers the declarative case over the same mechanism. ⚠️ Floats are invisible to the trace record either way |
| **Doors** | ✅ **Built** — `door:<map>:<index>[:interact\|init\|move]` is a `code.patches` selector (D103, D104). Resolved at load: `mapDataPtr(map)` → `MapData.initScript` → walk for `evt_door_set_door_descs` → `descs[index]` → the chosen script field. No interception, no trampoline, no `code.hooks`. ✅ `interact` measured APPLIED in-game, word 0 `0x0002003C` → `0x0002005C`, word 1 the mod's function pointer, word 2 untouched (D103). ⚠️ A door interact script opens with **`MULF`**, so `expect` must be measured per door — the guard is what makes a wrong guess REFUSED rather than destructive. ⛔ The index is not bounds-checked at build time and cannot be; the runtime compares against the setter's own `count` and reports NO_SCRIPT. ⛔ D91's "reaching a door needs interception, not a lookup" and D93/D94's "doors unreachable" are all **superseded** (D101, D102). 🔶 The hook has never been *entered* — a door script runs when the player uses the door, which needs a controller. 🔶 What `init` and `move` open with is unrecorded |
| **US (`us0`) support** | 🔴 **Blocked on a US disc image.** `work/extracted/` holds `eu0` only, so nothing US-targeted can be extracted, built or booted here. `base`/`code.target` already carry the version, and the symbol lists exist — what is missing is a disc |
| Map ids / chapter names | ✅ Dumped from the game and committed; `bleck maps` (D51) |
| **Boot straight into any map** | ✅ `--map` / `code.boot` (D64) |
| **Button combinations** | ✅ `bleck.yml` + `code.combos`, played by hand (D77). ⚠️ D48 never ruled this out — it is about *injecting* input (D66) |
| **Several code mods on one disc** | ✅ Merged at compile time; both run (D78). The loader's one-REL limit is untouched |
| **Enemy placement editing** | ✅ Declared in `mod.json`, verified in game (D80) |
| **A JSON API** | ✅ `bleck mod export/import`, `setup show/apply`, versioned, schema-published |
| **A single-file binary** | ✅ `pyinstaller bleck.spec`; CI builds and smoke-tests three platforms, green on all (D83). ✅ Green again on the **pinned** interpreter (D99), which is what proves `setup-uv` fetches `.python-version`'s 3.13 on Linux and macOS and not just where it was developed. 🔶 The tag-triggered release job **has still never run** — it is gated on `refs/tags/v*`, so a push to `main` does not exercise it however green that build is |
| **Published docs** | ✅ MkDocs → GitHub Pages, live at `coolroo.github.io/bleck` |
| Map geometry / archive contents | ⛔ **Not decoded.** The prize, and a research problem before an editing one |
| **Reaching any map unattended** | ✅ `evt_seq_mapchange` from a map hook — no controller needed (D52) |
| **Setup files: which copy the game reads** | ✅ **Settled** — the **standalone** `files/setup/*.dat`. ⚠️ D53 concluded the opposite and was wrong; D62 measured it |
| Windows 11 | ✅ **Fully verified** — tests, linters, `extract`, `verify`, `mod build`, boot (D33, D35, D36) |
| `map.dat` internals | ⛔ Deliberately deferred — see below |

---

## What is blocking what

Nothing on the list below is blocked by another item on it — work can proceed in
whatever order is most useful. Two things are blocked by something outside the
repository:

- 🔴 **US (`us0`) support needs a US disc image.** Only `eu0` is extracted here.
- 🔵 **Seeing a patched item hook run needs a human** — a save state plus
  attended input (D48, D92).

⚠️ One caveat worth carrying: **only `eu0` has been booted**, and every runtime
claim in this repository is Dolphin's behaviour. **Nothing has ever run on a
real Wii**, including the Riivolution output built for it.

---

## In rough order of value

**Everything is measured against "does this get us to the base app"**
([`vision.md`](./vision.md)). Licensing, packaging polish and breadth of
game-version support are explicitly deferred — nothing is shared until there is
an application worth sharing.

**Legend:** 🟢 ready · 🟡 needs a decision · 🔵 needs a human, not an agent ·
🔴 blocked on something outside the repository

### 🟢 Publish what this repository knows and the ecosystem does not

⚠️ **Not a docs task.** `docs/` is a maintainer's record and `docs-site/` tells
people how to use `bleck`; neither is written to be *found* by someone
researching Super Paper Mario. A third audience exists — the modding and decomp
community — and there is now a real amount here that is not on any forum,
wiki or repository:

- ✅ `evt_door.h`'s `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)` is
  **wrong**; the game uses argc 3, matching the comment above it (D102). This
  cost two entries here and would cost anyone else the same.
- ✅ A script that reaches its end needs `END_EVT`, not just `END_SCRIPT`, or
  its entry stays alive and the game hangs a few frames later with every value
  it wrote still correct (D106).
- ✅ The game reads the **standalone** `files/setup/*.dat`, not the copy
  embedded in the map archive (D62) — and this repository itself got that
  backwards for a long time.
- ✅ A PowerPC code patch needs `dcbst`/`sync`/`icbi`/`isync`, measured against
  a no-flush control that silently did nothing (D94).
- ✅ `GetBasicPlayer` returns `arg0 + 0xD8`, and it is in no header (D96).
- ✅ `itemEventDataTable` holds 33 entries, all *effect* items — an item with no
  scripted use, like Shroom Shake, is simply absent (D107 follow-up).
- ✅ The self-healing detour: a function can be watched, arguments **and**
  return value, without a trampoline (D96).
- ✅ A door's interact script opens with `MULF`, so there is no useful default
  for a patch guard (D103).

Most of this was measured because a header or an assumption was wrong, which is
exactly the shape of thing that is expensive to rediscover and cheap to write
down.

🔶 Shape undecided: a `docs/findings/` tree, a wiki page, or upstream PRs
against `spm-headers` for the ones that are outright corrections. The argc bug
is a genuine upstream fix and should probably go back as one regardless.


### 🟢 More editing surfaces through the API

Placement editing is done end to end because its format is *fully decoded*. The
same treatment for anything else needs the format understood first — which makes
this a research question wearing an engineering hat.

⛔ **The map archive is not decoded.** It is the prize, and until someone reads
it there is nothing to build an editor on. Do not plan GUI work around it yet.

### 🟢 A GUI over the JSON contract

`bleck mod export | edit | import` already round-trips every mod in the tree. A
frontend can be any language; the schema is published. This is the first thing
that turns `bleck` into an *app* rather than a toolchain.

### 🔵 A save state

Driving into a map leaves **Mario invisible** — no save, no profile (D63). Fine
for reading enemy placement, useless for anything touching player state.
`--state` is wired into both `bleck launch` and `ingame.py`; it needs a human to
play far enough once and press F1.

### 🟢 The rest of the scripting language

`SETI` for ambiguous literals, `IF_FLAG`, detached `spawn`, `SET_PRI`/`SET_SPD`,
and `peek`/`poke` for `SET_RAM`/`GET_RAM`. `switch` landed in D84 and ✅ takes
the right arm in-game (D105). The language lowers to 50 of the VM's 120 opcodes;
this is the one place that number is written down, so update it here.

⚠️ Raw memory access is what would let a script write an `EvtScriptCode *` into
an **NPC** — but expect D51's trap: patching a pointer the game owns deadlocked
the map loader, and maps ended up watching `seqWork.p0` instead. ⛔ Doors and
items no longer need it: `code.patches` reaches both by selector (D92, D103,
D104), and it mutates bytecode rather than repointing anything.

### 🔶 Seeing a patched item hook actually run

`item:<id>` is built and its patch is measured as applied (D92) — but an item
use script only runs when the player uses that item, which needs menu
navigation, and controller input cannot be injected unattended (D48). What would
settle it: a save state with the item in the inventory plus `scripts/keys.py`
(Windows, attended). Until then the hook's *execution* stays 🔶.

⚠️ **`door:` inherits exactly this gap** (D103): the patch is measured as applied
and read back out of memory, but a door interact script runs when the player
*uses* the door. The same save state plus attended input settles both.

### ✅ ~~`door:` — measure the argc, then build the selector~~ — *done (D102, D103, D104)*

⛔ **This entry used to be "the next cheap experiment in the repository".** It is
kept because three superseded conclusions ran through it and the wrong turns are
the useful part.

✅ **Built.** `door:<map>:<index>[:interact|init|move]` is a `code.patches`
selector. The script part is optional and defaults to `interact`. `door` is out
of `DEFERRED_PATCH_KINDS`, which is now **empty**.

| what settled it | |
|---|---|
| argc of all three setters | ✅ **3** — `0x0003005C` (D102) |
| `he1_01` | ✅ 1 door, 3 loading zones |
| `DoorDesc[0]` script pointers | ✅ `interact 0x80D2FB78`, `init 0x80D2F9E0`, `move 0x80D2FB70` |
| `door:he1_01:0` in-game | ✅ **APPLIED**; word 0 `0x0002003C` → `0x0002005C`, word 1 → the mod's function, word 2 untouched (D103) |
| `door:he1_01:9` (past the end) | ✅ **NO_SCRIPT** — the two rows differing is what proves resolution happened |

⛔ **Three superseded conclusions, kept for why they were wrong:**

- **D91: "reaching a door needs interception, not a lookup."** Wrong. It is a
  lookup — `mapDataPtr(map)` → `MapData.initScript` → walk for
  `evt_door_set_door_descs` → `descs[index]`.
- **D93 searched for one function at one argument count.** It matched
  `header == 0x0002005C && script[at+1] == 0x800E2610`, so
  `evt_door_set_map_door_descs` and `evt_door_set_dokan_descs` were never in the
  search at any argc. The argc-2 constraint came from `evt_door.h`'s
  `EVT_DECLARE_USER_FUNC(evt_door_set_door_descs, 1)`, which **contradicts the
  comment directly above it** reading `(DoorDesc *descs, s32 count)`. ✅ The game
  uses argc 3 — the comment. The macro is wrong and D93 trusted it.
- **D94 hooked the function in maps that do not contain the call** — its run
  covered `mac_01`, `aa4_01` and `ls4_12`, and the registration is in `he1_01`.

Both controls passed. They proved the instruments *worked*, not that they were
*pointed at the right thing*.

⚠️ **Standing caution, worth stating once:** `spm-headers` is a hand-maintained
reference against a 2.34%-matched decomp, and this is the first recorded case of
one of its declarations being simply **incorrect**. Where a header's claim is
load-bearing — an argc, an offset, a size — it is a hypothesis 🔶 until measured.

What is still open on doors:

- 🔶 **The hook has never been *entered*.** A door interact script runs when the
  player uses the door, which needs a controller (D48) — the same standing gap
  as `item:`. What is measured is `status = APPLIED` plus the readback.
- ⚠️ **`expect` has no useful default.** A door interact script opens with
  `MULF`, a float multiply — not a `USER_FUNC`. Measure it per door.
- ⛔ **The index cannot be bounds-checked at build time.** How many doors a map
  registers is game data; the runtime compares against the setter's own `count`.
- 🔶 What `init` and `move` scripts open with is not recorded.
- 🔶 One door, in one map, and five maps is not the game.

⚠️ `MapDoorDesc` (0x20 bytes, `destMapName` +0x14, `destDoorName` +0x18) is the
**loading zone** descriptor and has *no* selector — `door:` reaches `DoorDesc`
(0x58), the door the player interacts with. Loading zones are the obvious next
one.

### 🟡 `npcdrv:` — research in progress, and *not* a `door:` in disguise

⛔ **Still not a selector**, and D107 is why it is not a mechanical follow-on
from `door:`. What that research settled, and what it did not:

✅ **Known** (`mods/npc-probe`, booted into `he1_01`):

- `npcGetWorkPtr()` (`0x801c9adc`) is usable every gameplay frame; it returned
  `0x805283E0`, entries at `0x807BB960`.
- ⚠️ `NPCWork.num` is **80 and constant** — the array's **capacity**, not a live
  count. `npcGetMaxEntries` is a separate symbol.
- `he1_01` has **3 live entries, all 3 carrying script pointers**
  (`templateinitScript` `0x8043B8F8`, `move` `0x804938E8`, `onHit`
  `0x80494E28`, `death` `0x80439F10`).
- ✅ Those pointers are **real evt bytecode** — the init script's first word is
  `0x0002005C`, `USER_FUNC` argc 2 — and the bodies live in **DOL static data**
  (`0x8043…`–`0x8049…`), so the bytecode is at a fixed address.

⛔ **The attract demo's maps contain no NPCs at all.** Two earlier runs read zero
for that reason alone. See the standing caution below.

🔶 **Why the `door:` shape does not carry over.** A door descriptor array's
address is an argument in the map's **init script**, readable at `mod_prolog`
before anything runs. An NPC's script pointers are fields on a **live
`NPCEntry`**, copied in at spawn — nothing carries them at `mod_prolog`. So a
build-time selector needs the **template**, and where templates live is unknown.

The open thread: `npcEntryFromSetupEnemy` (`0x801bf7a0`) takes a record from the
**setup file `bleck` already parses and edits** (D80). `npcEntryFromTemplate`
(`0x801be198`) is the other spawn path. 🔶 The alternative is intercepting a
spawn with `code.hooks` `mode: "after"` (D97) and rewriting the entry per spawn —
certainly possible today, but a hook rather than a declaration, which is the
wrong direction for [`vision.md`](./vision.md).

⚠️ `npcNameToPtr` (`0x801b6f2c`) means NPCs **can** be looked up by name, unlike
doors — a better selector shape than an index, if it can be reached at a useful
time. ⛔ `work->setupFile` (+0x18) read 0 in every map tried and is unexplained.

Measurements in
[`function-behaviour.md`](./function-behaviour.md); reasoning in D107.

### ⚠️ Standing caution: a correct measurement of the wrong maps

**Three separate times now, a real measurement has read as a capability being
absent** because the run never visited a map that had it — D94 (doors), D101
(doors again), D107 (NPCs). Each zero was honest and each was about **map
coverage**, not about the game.

The attract demo reaches only `aa4_01` and `ls4_12`. Neither registers a
`DoorDesc`; neither contains a single NPC. `scripts/ingame.py --map <name>`
boots straight into any of the 383 maps (D64), so this costs nothing to avoid.

**Before recording that something is absent, check the run was in a map that has
it**, and pair the reading with a control that would look different if it were
present. This is a testing-methodology fact people here keep re-learning.

### 🔴 US (`us0`) support — blocked on a disc

`base` and `code.target` already carry the version, symbol lists exist for every
region, and a mismatched base is already an error rather than a silent
misapplication. What is missing is a **US disc image**: `work/extracted/` holds
`eu0` and nothing else, so nothing US-targeted can be extracted, built, or
booted here. Until one exists this is not work that can be started, let alone
verified. Anchor everything address-dependent to `eu0` meanwhile.

### 🔵 Hardware — never tested

Every Riivolution result on record is Dolphin's implementation of Riivolution
(D86), and every cache-flush result is Dolphin's cache model (D94, D96). The XML
is written against the documented format and Dolphin's parser agrees with it;
that is not the same as an SD card in a Wii. One person with a Wii, a Riivolution
install and an SD card settles it.

### 🔶 Remaining button masks

`plus`, `minus`, `home` and the d-pad. One `button-probe` run each; `a`, `b`,
`1`, `2` are confirmed (D68).

### 🟡 A trampoline — no longer a blocker, only an optimisation

⛔ **This entry used to read "the single largest thing standing between
`code.hooks` and being usable for anything other than a probe". D97 retracts
that ranking**, and it is kept here rather than deleted because the mis-ranking
is the useful part: the mechanism was never the gap. Down-ranked from 🟢 near
the top of this list to here.

✅ `code.hooks` now accepts all three modes (D97). `before` and `after` are
generated as a PowerPC **assembly** wrapper per intercepting hook, over D96's
self-healing detour — restore the first instruction, call the original,
re-install the branch. No instruction is relocated, so upstream `hookFunction`'s
blind instruction[0] copy (D37) is not on this path at all.

⛔ **A real trampoline is still not built.** What it would still add, and the
only reasons left to want one:

- The detour pays **two cache flushes per call**; a trampoline pays none. D96
  measured that at 7–10 time-base ticks — ~1.1% on `effMain`, and unbounded
  relative overhead on a leaf like `GetBasicPlayer`, whose own body measured 0.
  🔶 Those are Dolphin's cycle counts, not a 750's, and no workload has yet been
  slowed by it: 26,996 SEQ_GAME frames ran with two hooks installed (D97).
- No wrapper at all. A trampoline of `<relocated instruction>; b <original + 4>`
  is reached with a plain branch.

If it is ever built, the refusal matters more than the coverage — a trampoline
that silently mis-relocates is worse than none. Decode the displaced instruction
well enough to know whether it is position-dependent and refuse the rest;
`bleck/backends/dol.py` already reads the words to decide from.

### 🟡 Speed, only if profiling names it

The LZ77 compressor is ~12 s/MB (D16) — the one place language choice shows as a
user-visible problem. The recorded answer is a PyO3 port of *just the
compressor*, not a rewrite. Eighty decision entries of hard-won behaviour do not
live in the language, and a rewrite re-discovers every bug.

### 🟡 Licensing — deferred, not forgotten

Blocks sharing and nothing else. Must be settled before any release, since
`docs-site` tells people to clone a repo that is all-rights-reserved by default.

---

## Historical: the original code-injection plan

⚠️ **Steps 3, 4 and 5 below are done, and step 6 is no longer blocked.** Kept
because the reasoning — especially the ABI gamble in step 3 and the fallback
that was never needed — is the useful part. Read it as a record, not a plan.

⚠️ **Largely superseded.** Kept because the reasoning is still useful and
because item 1's premise turned out to be wrong.

The design is written up in [`code-mods.md`](./code-mods.md); the toolchain is
proven. What remained:

> ⚠️ **Superseded in part by D37.** The scripting track shipped without
> resolving item 1: scripts name game functions and `elf2rel` binds them at
> build time, so `bleck` vendors no upstream material at all. Licensing is still
> worth settling, but it **no longer blocks this track**. See
> [`scripting.md`](./scripting.md).

### 1. 🟡 Decide the licensing question — *no longer blocks the scripting path*

`spm-rel-loader` is **GPLv3**, including the Gecko loader code we need.
`spm-headers` is MIT except its `mod/` folder, which is also GPLv3. `bleck` is
currently **unlicensed**.

Three options:

- **Don't vendor.** `bleck` fetches or requires the user to supply
  `spm-rel-loader`. Keeps the toolkit license-clean; costs a setup step.
- **Vendor and adopt GPLv3**, for the code-mod portion or the whole project.
- **Vendor only the MIT parts** (`spm-headers`' `include`/`linker`) and fetch the
  GPL loader separately.

⚠️ Nothing upstream has been copied into this repo yet — the clones live in
scratchpad precisely so this stays open. **This decision should come first**,
because unwinding a licensing mistake later is far worse than making it now.

### 2. ✅ ~~Install `g++-powerpc-linux-gnu`~~ — *done (D85)*

D26 proved the C toolchain and this step was about the C++ one. `code.sources`
now compiles `.cpp`/`.cc`/`.cxx` beside C, with the driver derived from whichever
`gcc` was located rather than hardcoded, so the Linux package name below is only
one of the ways to satisfy it — devkitPPC's `powerpc-eabi-g++` is what is used on
the Windows host.

```
sudo apt install -y g++-powerpc-linux-gnu
```

### 3. ✅ ~~Get one hook actually running~~ — *done (D38, D43, D46)*

⚠️ **The ABI gamble did not fail**, and the Windows fallback was never
needed. What did bite was *timing*, not ABI: three hook points were tried
before one worked (D38, D40, D43). See [`hook-points.md`](./hook-points.md).

**This is the D25 of the code track.** Everything else assumes our REL both
loads and behaves; that assumption is currently untested and carries real risk:
Debian's compiler targets SysV where devkitPPC targets `powerpc-eabi`, so ABI
differences could produce code that builds cleanly and misbehaves at runtime.

Smallest useful test: hook a function called early and often, and make an
unmistakable change — force a value, skip a check, alter a displayed string.
Verified by booting, exactly as the asset pipeline was.

Concretely, this needs:

- The Gecko code applied so `/mod/mod.rel` actually executes (see step 5)
- `mod.rel` placed on the disc — the overlay already handles this, no new code
- Something observable enough to confirm through emulation

⚠️ **If the ABI gamble fails**, fall back to building RELs on Windows with real
devkitPPC and packaging with `bleck`. The split is clean because the REL is just
a file the overlay places, so the design here does not change — only where the
compile runs.

### 4. ✅ ~~Wire compilation into `bleck mod build`~~ — *done*

A `code/` directory in a mod, a `code` block in `mod.json`, compiled output
generated into `overlay/files/mod/mod.rel`. Design already written; mechanical
once step 3 proves the output works.

### 5. ⛔ ~~Emit the Dolphin INI~~ — *superseded by D44*

The loader is now embedded in the DOL with `wstrt --add-sect`, so a built
disc needs no Dolphin configuration at all. Verified with the cheat config
removed entirely. The INI plan below is obsolete.

Riivolution and ISO rebuilds only place the *file*. Without the Gecko code,
`mod.rel` sits on the disc inert. Dolphin reads codes from
`User/GameSettings/R8PP01.ini`, so `bleck` can emit it beside the built image
and make testing turnkey:

```
work/build/my-mod.wbfs
work/build/my-mod.R8PP01.ini
```

The loader codes ship pre-assembled per region, so this is packaging, not
assembly.

### 6. 🟡 Multiple code mods — *no longer blocked; step 3 is done*

⚠️ **`chainrel` is not the answer** (D39): a three-commit stub with its
loader body wrapped in `#if 0`. Nobody in this scene has solved this, which
is what makes it the clearest unclaimed problem available.

The Gecko loader loads exactly one file, `/mod/mod.rel`, but our chains allow
many mods. Two wanting code would collide, and unlike an asset conflict the
second simply would not exist.

**Interim:** treat `files/mod/mod.rel` as implicitly exclusive — one code mod per
build, caught by existing conflict machinery. Then adopt
[`chainrel`](https://github.com/SeekyCt/chainrel) once a single code mod works.
Shipping a broken multi-mod story is worse than declining to support it.

---

## Now unblocked by D25

Booting works, so questions that needed a running game are answerable:

### ✅ ~~Settle the setup-file duplication (D13)~~ — *done (D62)*

⛔ **The paragraph below is the superseded D53 answer**, kept because the
wrong turn is the useful part. The game reads the **standalone**
`files/setup/<map>.dat`; D53's measurement was right and its inference was
not.

> The game reads the copy **embedded in the map archive**. The standalone
`files/setup/*.dat` is loaded into MEM2 but never used, so editing it alone is a
silent no-op — `bleck` now says so at build time. Proven with a control run:
swapping which copy carried which marker left both buffer addresses unchanged.

The original reasoning is kept below.

Setup files exist as **two byte-identical copies** — standalone in `setup/` and
embedded in some map archives — and we do not know which the game reads. `bleck`
warns at build time, but the warning is a confession of ignorance.

Now testable directly: change one copy, boot, observe. Change the other,
compare. An afternoon at most, and it removes a real footgun.

### 🟢 Identify `rel.bin` vs `relF.bin` (D11)

99.8% identical strings, one section apart. `relD.bin` is a **debug build**
(PAL-only, `Debug:Stage Skip ON`, 13 extra source filenames). The remaining
question is what distinguishes the other two. `relD` is also worth mining for RE
value — it names source files the retail builds omit.

---

## Deliberately deferred

### `map.dat` internals

The obvious next asset target, and correctly postponed: **without a viewer,
editing map data means changing bytes and hoping.** The feedback loop is
"rebuild a 400 MB disc, boot, squint" — untenable for reverse engineering a
format.

Reasonable order when it comes up: parse the structure headers, build a minimal
2D visualiser, *then* edit. The visualiser is the expensive part, which is
exactly why code injection comes first — it has a tight feedback loop today.

### Cross-region symbol porting

Research (D1) identified this as the **highest-leverage gap in the whole SPM
ecosystem** — upstream explicitly waits on it, and symbol coverage ranges 3× from
eu0 to kr0. It is also a large project, and only matters once we are producing
code worth porting. After the code track lands.

---

## Small, whenever

- **LZ77 lazy matching.** Our encoder is +0.25% vs Nintendo; lazy matching would
  likely close most of that. Zero urgency — D25 proved bit-exactness is not
  required.
- ~~**Run the test suite on Windows.**~~ ✅ Done (D33, D35, D36) — the suite, the
  linters, `extract`, `verify`, `mod build` and `launch` all pass there against
  real game data, and a disc built on Windows boots with modified textures.
- **`bleck info` for `/a` container files** — the paired `name` / `name-` format
  is still unidentified.
- **`map/go1_03.bin`** — PAL-only map absent from US builds. Curiosity, but it
  may be cut content.

---

## Suggested next session

⚠️ The three steps that used to sit here — licensing, installing a C++ compiler,
booting the first hook — are done or deferred. The code track is no longer the
risky part of this project.

1. **A GUI over the JSON contract.** The largest remaining step toward the thing
   `vision.md` describes, and it is unblocked: the schema is published and every
   mod in the tree round-trips through it.
2. **A save state**, which needs a human once and then unblocks item hooks,
   player state, and anything past the attract demo.

⛔ **"A trampoline, so `mode: \"before\"`/`\"after\"` can stop being refusals" used
to be item 2 here.** D97 shipped both modes without one; the remaining case for
a trampoline is two cache flushes per call, and it is 🟡 far down the list above.

Licensing (step 1 of the historical plan) still has to be settled before any
release, and still blocks nothing else.
