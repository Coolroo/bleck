# Roadmap

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
| **Code injection** | ⬅ **the active track, not yet integrated** |
| Windows 11 | ✅ **Fully verified** — tests, linters, `extract`, `verify`, `mod build`, boot (D33, D35, D36) |
| `map.dat` internals | ⛔ Deliberately deferred — see below |

---

## Active track: code injection

This is where the interesting mods live. Everything below is asset-swapping;
this is running our own code inside the game.

The design is written up in [`code-mods.md`](./code-mods.md); the toolchain is
proven. What remains:

### 1. 🟡 Decide the licensing question — *blocks everything else here*

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

### 3. 🟢 Get one hook actually running — *the real milestone*

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

### 4. 🟢 Wire compilation into `bleck mod build`

A `code/` directory in a mod, a `code` block in `mod.json`, compiled output
generated into `overlay/files/mod/mod.rel`. Design already written; mechanical
once step 3 proves the output works.

### 5. 🟢 Emit the Dolphin INI

Riivolution and ISO rebuilds only place the *file*. Without the Gecko code,
`mod.rel` sits on the disc inert. Dolphin reads codes from
`User/GameSettings/R8PP01.ini`, so `bleck` can emit it beside the built image
and make testing turnkey:

```
build/my-mod.wbfs
build/my-mod.R8PP01.ini
```

The loader codes ship pre-assembled per region, so this is packaging, not
assembly.

### 6. 🔴 `chainrel` for multiple code mods — *blocked on step 3*

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

### 🟢 Settle the setup-file duplication (D13)

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
