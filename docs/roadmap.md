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
| **Scripting language** | ✅ **Working end to end** — compiles, links, and runs in-game at 60 iterations/sec, surviving map changes (D37, D43). `switch`/`case` lowers onto evt's own `SWITCH`…`END_SWITCH` (D84); 🔶 no switch has been run in-game |
| **Native code mods** | ✅ **Working** — `code.sources` compiles C into the same module and it runs in-game (D46, D47) |
| **C++ code mods** | ✅ Builds — `.cpp`/`.cc`/`.cxx` alongside C, `-fno-exceptions -fno-rtti -std=gnu++17`, static constructors walked from `_prolog` and the `.ctors` table checked at link (D85). 🔶 **Nothing C++ has run in-game** |
| **Riivolution output** | ✅ `--output riivolution` writes an XML plus only the changed files — 5.3 MB and 3.2 s against minutes for an image (D86). The loader travels inside the patched `main.dol`, so nothing has to be configured in the emulator. 🔶 **Dolphin only; never run on a Wii** |
| **Event mods** | ✅ **Working** — `code.maps` runs a script on arrival at a named map (D51) |
| **Patching the game's own scripts** | ✅ `code.patches` replaces one instruction of a vanilla `evt` script with a call into `mod.rel` (D89, D90). Same-size, but **any** size from two words up, and `item:<id>` as well as `map:<name>` (D92). 🔶 An item hook has never been seen *entering* |
| **Patching the game's own code** | ✅ C helpers write a PowerPC branch and flush it correctly; measured against a no-flush control that did nothing (D94). ✅ `code.hooks` declares one, with a guard word derived from `main.dol`; positive and negative runs (D95). ✅ **All three modes** — `replace`, `before` and `after` — via a generated PowerPC **assembly** wrapper per intercepting hook (D97); `before` and `after` both return the *original's* value. ⛔ Still **no trampoline**: interception reuses D96's self-healing detour, so it pays two cache flushes per call. ✅ A mod can also keep the original by hand-restoring it around the call: arguments **and** return values, `mapDataPtr` and `effMain` traced live (D96) |
| **Tracing a game function** | ✅ The self-healing detour records arguments **and** return values while the original still runs — `mapDataPtr`, `effMain` and `GetBasicPlayer` measured live (D96). Hand-written tracing is still a pattern over `code.hooks`, deliberately **not** a manifest field; `mode: "before"`/`"after"` (D97) covers the declarative case over the same mechanism. ⚠️ Floats are invisible to the trace record either way |
| **Doors** | ⛔ **Unreachable, with a reason.** `DoorDesc` has no lookup by name; descriptors are registered per map by `evt_door_set_door_descs`. That call is absent from all five map init scripts walked (D93, positive control 8 hits), and a branch installed over the function itself was entered **zero** times across 90 s in Flipside while a control hook fired 62,480 times (D94). `door:` is refused by the manifest. 🔶 Two maps is not the game; `door_init_evt` sits in the REL range, so door setup plausibly lives in each map's own module |
| **US (`us0`) support** | 🔴 **Blocked on a US disc image.** `work/extracted/` holds `eu0` only, so nothing US-targeted can be extracted, built or booted here. `base`/`code.target` already carry the version, and the symbol lists exist — what is missing is a disc |
| Map ids / chapter names | ✅ Dumped from the game and committed; `bleck maps` (D51) |
| **Boot straight into any map** | ✅ `--map` / `code.boot` (D64) |
| **Button combinations** | ✅ `bleck.yml` + `code.combos`, played by hand (D77). ⚠️ D48 never ruled this out — it is about *injecting* input (D66) |
| **Several code mods on one disc** | ✅ Merged at compile time; both run (D78). The loader's one-REL limit is untouched |
| **Enemy placement editing** | ✅ Declared in `mod.json`, verified in game (D80) |
| **A JSON API** | ✅ `bleck mod export/import`, `setup show/apply`, versioned, schema-published |
| **A single-file binary** | ✅ `pyinstaller bleck.spec`; CI builds and smoke-tests three platforms, green on all (D83). 🔶 The tag-triggered release job has never run |
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
and `peek`/`poke` for `SET_RAM`/`GET_RAM`. `switch` landed in D84, though 🔶
nothing has run one in-game. The language lowers to 50 of the VM's 120 opcodes;
this is the one place that number is written down, so update it here.

⚠️ Raw memory access is what would let a script write an `EvtScriptCode *` into
a **door, NPC or item** — but expect D51's trap: patching a pointer the game
owns deadlocked the map loader, and maps ended up watching `seqWork.p0` instead.

### 🔶 Seeing a patched item hook actually run

`item:<id>` is built and its patch is measured as applied (D92) — but an item
use script only runs when the player uses that item, which needs menu
navigation, and controller input cannot be injected unattended (D48). What would
settle it: a save state with the item in the inventory plus `scripts/keys.py`
(Windows, attended). Until then the hook's *execution* stays 🔶.

### ⛔ `door:` and `npcdrv:` patch selectors

Deferred with a reason, not merely unimplemented. `DoorDesc` carries
`initScript`/`interactScript`/`moveScript` but has **no lookup by name**: the
descriptor array is registered per map by `evt_door_set_door_descs`, and
`evtDoorGetActiveDoorDesc` returns only the door in use, which is null at
`mod_prolog`. A door patch would have to *intercept* that registration — a
different shape from `map:` and `item:`, and unproven (D91). 🔶 The same likely
applies to `npcdrv.h`'s `templateinitScript`.

⛔ **Interception is now built and it does not help.** Instruction patching works
(D94): a branch written over `evt_door_set_door_descs` at `mod_prolog` was in
place, verified by readback, and entered **zero** times while Flipside loaded and
ran for 90 s — with a control hook on `npcDispMain` firing 62,480 times in the
same window. D93 had already ruled out reaching it from map init scripts. So the
function is not on the path for `mac_01` or `aa4_01` at all.

🔶 **Where to look next:** `door_init_evt` (`0x8041a2b0`) sits in the REL address
range, so door setup plausibly lives in each map's own module. Hooking that, or
finding the caller of `evt_door_set_door_descs` in a map that does use it, is the
next cheap experiment. Two maps is not the game.

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
