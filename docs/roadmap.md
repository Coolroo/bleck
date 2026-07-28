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
| **Scripting language** | ✅ **Working end to end** — compiles, links, and runs in-game at 60 iterations/sec, surviving map changes (D37, D43) |
| **Native code mods** | ✅ **Working** — `code.sources` compiles C into the same module and it runs in-game (D46, D47) |
| **Event mods** | ✅ **Working** — `code.maps` runs a script on arrival at a named map (D51) |
| Map ids / chapter names | ✅ Dumped from the game and committed; `bleck maps` (D51) |
| **Reaching any map unattended** | ✅ `evt_seq_mapchange` from a map hook — no controller needed (D52) |
| **Setup files: which copy the game reads** | ✅ **Settled** — the one embedded in the map archive (D53) |
| Windows 11 | ✅ **Fully verified** — tests, linters, `extract`, `verify`, `mod build`, boot (D33, D35, D36) |
| `map.dat` internals | ⛔ Deliberately deferred — see below |

---

## Nothing is blocking

The scripting track is proven end to end (D43). Work can proceed on any of the
items below in whatever order is most useful.

⚠️ One caveat worth carrying: **only `eu0` has been booted.** Other versions
compile but nothing has run on them.

---

## In rough order of value

**Legend:** 🟢 ready · 🟡 needs a decision · 🔵 needs a human, not an agent

### Needs no emulator at all

1. 🟢 **A `setup` reader/writer — the clearest next feature.** Turns `bleck`
   from "runs code" into "changes the game". Enemy and item placement is the
   most obviously moddable thing on the disc after textures, and no `bleck` code
   touches it yet.

   Both former blockers are gone: the container is fully specified in
   [`disc-layout.md`](./disc-layout.md) (a fixed 100-entry array, stride by
   version), and D53 settled which of the two copies to write.

   ⚠️ **The real work is the entry *fields*.** Only position and enemy ID are
   known, out of 112 bytes. `he1_01` is a good subject: 3 used entries out of
   100, and reachable unattended (D52).

2. 🟢 **Switch to the decomp symbol table** (D39). ~9,566 named symbols against
   the lst's 976, with sizes and types — enough to reject a `user_func` target
   that is actually *data* at compile time, instead of shipping a REL that jumps
   into a table.
   ⚠️ `spm-decomp` states **no licence** (D54), so it cannot be vendored. Read a
   clone the user supplies, exactly as symbol lists already work.

3. 🟢 **Emit `SETI` for ambiguous literals** (D39). Small; `var a = -30000000`
   is a compile error and need not be.

### Testable unattended, now that D52 landed

4. 🟢 **`peek`/`poke`, then doors, NPCs and items.** The remaining event
   surfaces — maps are done (`code.maps`, D51).
   ⚠️ **Read D51 first.** Patching a pointer the game owns deadlocked the map
   loader while passing every mechanical check; the design that works watches
   state instead. Expect the same trap here.

5. 🟢 **More opcodes**: `switch`, `IF_FLAG`, detached `spawn`, `SET_PRI`/
   `SET_SPD`. The language reaches 39 of the VM's 120. Unwritten, not blocked.

### Bigger swings

6. 🟢 **Multiple code mods.** ⚠️ **Unclaimed across the entire scene** (D39):
   `chainrel` is a stub with its loader body in `#if 0`, and both major
   distributions tell users to run one REL mod at a time. Highest
   differentiation, highest risk, and no user-visible payoff until it works.

7. 🟢 **Verify beyond `eu0`.** Everything so far has run on one build. Other
   versions compile; nothing has booted. `spm-porter` ships `pal0→us0` match
   CSVs.

### Needs a human

8. 🔵 **Confirm the `mod_loaded` banner.** Parked on `feat/mod-banner` because
   nothing here can see the screen and the title screen is unreachable
   unattended (D47, D48). `work/out/banner-probe.wbfs` is already built — boot
   it and check the text lands bottom-right, unclipped.

9. 🟡 **Settle the `LICENSE`.** Now the **only** thing between this and being
   shareable. `README.md` credits every upstream project and states that no game
   data is included, but `bleck` itself is all-rights-reserved by default while
   `docs-site` tells people to clone it. MIT would match `spm-headers`, whose
   material we resolve against.

### Done this cycle

| | |
|---|---|
| ✅ Bake the Gecko loader into the DOL | D44 — verified with Dolphin's cheat config removed. 🔶 Console untested |
| ✅ Native hooks in `bleck mod build` | D46, D47. ⚠️ C++ still unavailable — `g++-powerpc-linux-gnu` not installed |
| ✅ Event mods (`code.maps`) | D51 |
| ✅ Reach any map unattended | D52 |
| ✅ Settle D13 | D53 |
| ✅ Credit upstream projects | D54 |

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

### 2. 🟢 Install `g++-powerpc-linux-gnu`

```
sudo apt install -y g++-powerpc-linux-gnu
```

D26 proved the C toolchain. Upstream's framework is C++17, so anything beyond a
trivial hook needs the C++ compiler. Cheap and unblocking.

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

### ✅ ~~Settle the setup-file duplication (D13)~~ — *done (D53)*

The game reads the copy **embedded in the map archive**. The standalone
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
- ~~**Run the test suite on Windows.**~~ ✅ Done (D33, D35, D36) — 164 tests, the
  linters, `extract`, `verify`, `mod build` and `launch` all pass there against
  real game data, and a disc built on Windows boots with modified textures.
- **`bleck info` for `/a` container files** — the paired `name` / `name-` format
  is still unidentified.
- **`map/go1_03.bin`** — PAL-only map absent from US builds. Curiosity, but it
  may be cut content.

---

## Suggested next session

1. Make the licensing call (step 1) — it gates the rest.
2. `sudo apt install -y g++-powerpc-linux-gnu` (step 2).
3. Build the smallest observable hook and boot it (step 3).

Step 3 is the one that matters. Until a REL we built demonstrably *runs*, the
code track rests on the same kind of untested assumption the asset track carried
before D25 — and that assumption is riskier here, because the ABI mismatch is a
real and specific hazard rather than a general worry.
