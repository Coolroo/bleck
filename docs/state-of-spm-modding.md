# State of Super Paper Mario Modding (as of 2026-07-26)

Research snapshot compiled to orient the `spm-modkit` project. All repo metadata
(push dates, stars, percentages) was verified on 2026-07-26 and will drift.

---

## TL;DR

SPM modding is a **small but genuinely working ecosystem**, overwhelmingly
centered on one author: **SeekyCt**, whose repos supply the decompilation, the
symbol/header library, the RE documentation, the code-injection kit, and the evt
script tooling.

The critical thing to understand up front: **the practiced modding path is not
"edit a decomp and rebuild the game."** It is:

```
write freestanding PowerPC C/C++
  → compile with devkitPPC
  → link against a per-version symbol list (.lst)
  → convert ELF → Nintendo REL module
  → drop on disc as /mod/mod.rel  (Riivolution, or WIT ISO repack)
  → a Gecko code loads and runs it at boot, after the game's own REL
```

That pipeline demonstrably works — multiple substantive mods ship through it.

---

## The core stack

| Repo | Role | Last push | Health |
|---|---|---|---|
| [`SeekyCt/spm-decomp`](https://github.com/SeekyCt/spm-decomp) | WIP 1:1 decompilation | 2026-07-21 | bursty, ~2.34% matched |
| [`SeekyCt/spm-headers`](https://github.com/SeekyCt/spm-headers) | Symbols + structs + linker lsts | 2026-03-14 | **most current** |
| [`SeekyCt/spm-docs`](https://github.com/SeekyCt/spm-docs) | RE docs, ~47 pseudo-C headers | 2024-08-17 | dormant |
| [`SeekyCt/spm-rel-loader`](https://github.com/SeekyCt/spm-rel-loader) | Gecko loader + mod framework + elf2rel | 2022-06-13 | **stale but foundational** |
| [`SeekyCt/chainrel`](https://github.com/SeekyCt/chainrel) | Chain-loads `./mod/chain.rel` | 2026-02-09 | active |
| [`SeekyCt/evt-disassembler`](https://github.com/SeekyCt/evt-disassembler) | evt bytecode → text / C macros | 2026-04-19 | active |
| [`SeekyCt/evt-assembler`](https://github.com/SeekyCt/evt-assembler) | text evt → binary | 2021-06-04 | **ARCHIVED** |
| [`SeekyCt/pyelf2rel`](https://github.com/SeekyCt/pyelf2rel) | Generic GC/Wii ELF→REL (PyPI) | — | active alternative |
| [`skawo/Super-Paper-Mario-Level-Editor-Randomizer`](https://github.com/skawo/Super-Paper-Mario-Level-Editor-Randomizer) | Setup files, enemy data, ISO repack | 2025-01-30 | the asset-side tool |

### Decompilation — read the caveat carefully

`spm-decomp` is only **~2.34% decompiled / ~1.50% fully linked**, and that is
*by design*:

> "This will never be a decompilation of the full game, just specific parts that
> are useful or interesting... The SDK, NW4R and MSL libraries are out of scope."

**Do not read the low percentage as "modding is blocked."** The decomp is a
*documentation and symbol source*, not a build target. Its README is explicit:

> "In its current state, the repo isn't really ready for direct editing, but
> functions can be copied into [REL mods] and edited there, and the
> documentation is still useful."

It is also only "in theory shiftable... but this hasn't been thoroughly tested."
So a rebuild-from-source workflow does not exist today.

### Code injection

`spm-rel-loader` (a fork of PistonMiner/Zephiles' TTYD rel loader) provides:

- `loader/` — Gecko code that loads and runs a custom REL (source in `loader.s`)
- `rel/` — framework for writing code on top of existing code
- `elf2rel/` — ELF → REL converter

> "The file `/mod/mod.rel` is loaded from the disc (add with Riivolution or by
> ISO patching with Wiimms ISO Tools) and executed during boot, after the game's
> rel, by the cheat code given in the loader folder."

Note the documented SPM toolchain uses PistonMiner's **C++** elf2rel (via an
`ELF2REL` env var), not `pyelf2rel` — the latter is a same-author alternative.

### Build contract for a mod

- Add spm-headers' `include` and `mod` folders to the include path
- Use an `.lst` from `linker/` for your target version
- **Keep** standard library headers (do *not* use `-nostdinc`); linking libc is
  unnecessary, so `-nostdlib` is fine
- Toolchain: **devkitPPC** (`DEVKITPPC` + `ELF2REL` env vars)
- Decomp consumers instead use `include`/`include_cpp`/`decomp` with a `DECOMP` define
- **Licensing is split: MIT core, but `mod/` is GPLv3** — matters if you vendor headers

---

## Versions: 8 retail builds, wildly unequal support

Selected via `make rgX` (loader) and `SPM_{JP0,JP1,US0,US1,US2,EU0,EU1,KR0}`
preprocessor defines (headers).

| Build | Symbol list size | Notes |
|---|---|---|
| **eu0** | 33,661 B | **reference build** — the zero-arg default |
| eu1 | *(none)* | PAL revs share addresses with eu0 |
| us0 | 26,572 B | |
| us2 | 26,056 B | |
| jp0 | 20,541 B | |
| us1 | 17,309 B | |
| jp1 | 11,891 B | |
| kr0 | 11,636 B | |

> spm-docs: "All research is done on PAL revision 0 unless stated otherwise."

**NTSC-U work is explicitly discouraged upstream:**

> "it's advised to not put work into [NTSC-U] until some kind of automated
> porting setup has been created."

⚠️ **This matters for you specifically** — `roms/` holds *Super Paper Mario (USA)*
and *(USA) (Rev 1)*, i.e. **us0 and us1**. us1 has the *second-smallest* symbol
list of all 8 builds (17 KB vs eu0's 34 KB). If you plan to develop against the
reference build's documentation, expect friction. Consider sourcing a PAL rev 0
image for development even if you target US for release.

Both ROMs are also **`.wbfs`, not raw ISO** — the toolkit's input handling needs
to either convert (WIT does this) or read WBFS directly.

---

## Scripts: the `evt` bytecode format

SPM's cutscene/logic system is a bytecode called **evt**, structurally related to
TTYD's (shared lineage — evt-disassembler credits `ttyd-asm`, though SPM uses its
own official instruction names).

**Disassembly (active):** operates on a MEM1 RAM dump —
`--ramfile`/`--address`/`--map`/`--recursive`, plus `--ttyd` to swap opcode
tables and variable bases.

**The `--cpp` flag is the important one.** It emits C/C++ macro source
(`EVT_BEGIN`, `USER_FUNC`, `IF_STR_EQUAL`, `RUN_CHILD_EVT`, `LW`, `PTR`, `FLOAT`,
`MULF`, `END_IF`, `RETURN`, `EVT_END`) whose implementations live in
spm-headers' `evt_cmd.h` — present in **both** `mod/` and `decomp/` variants.
So disassembled scripts can be edited and recompiled straight into a REL mod.

**Assembly (dead):** `evt-assembler` is **archived**, untouched since 2021-06-04.
There is no maintained text→binary round trip. The live workflow is
disassemble → edit as C macros → compile into a REL.

Note: evt scripts are not only in RAM — they also exist statically in the DOL/REL
and are handled in source form by spm-decomp.

---

## Packaging & distribution

Two documented workflows, both upstream-blessed:

**Riivolution** (real Wii or Dolphin) — enable mods on the SPM page.

**Full ISO repack with Wiimms ISO Tools (WIT):**
> "Extract your ISO with either Dolphin's built-in extractor or Wiimms ISO
> Tools... create a folder called `mod` in the base folder of the DATA
> partition... Rebuild your ISO with Wiimms ISO Tools (**make sure to use
> `--align-files`**)."

⚠️ **Riivolution/WIT only *deliver* the file — the Gecko code is still required
to execute it.** A third route exists: a save-file exploit loader
(`spm-save-exploit`).

Community tooling **wraps rather than replaces** WIT — L5050's
[Flipside Mod Manager](https://github.com/L5050/Flipside-Mod-Manager) (also at
`star-haven/flipside-mod-manager`) is a CLI installer requiring WIT *plus* the
Wiimms SZS toolset (`wstrt`). That `wstrt` dependency is a strong hint that
**SZS archives are involved in SPM's asset layout**.

---

## Community & shipped mods

**[Star Haven](https://starhaven.dev/mods)** is the cross-title Paper Mario hub —
categories `N64 - PM64`, `GCN - TTYD`, **`Wii - SPM`**, `3DS - SS`, `Switch - TOK`
— with a ~13.5k-member Discord, `docs.starhaven.dev`, organized events (Paper
Mario Modding Jam, Star Haven Battle Jam), and [`github.com/star-haven`](https://github.com/star-haven).
Dolphin is the primary listed platform for SPM.

The SPM section is the small sibling of PM64/TTYD (~5 mods), but they are real
and iteratively versioned — proving code and data patching is established
practice, not theory:

- **Super Paper Mario: Hard Mode** v2.1.1 (L5050, 2023) — reworks XP/HP/damage/bosses;
  [`L5050/SPM-Hard-Mode`](https://github.com/L5050/SPM-Hard-Mode) is ~105 commits of
  C/C++ with a Makefile — compiled REL injection, not asset swapping
- **Rubies and Magic** DLC v1.0 (2024) — rebalances boss AI
- **Flipside Pit Randomizer** (Tartt/shiken-yme, Aug 2024) — since renamed
  *Lunatic Pit*, iterated v1.0 → v2.1; randomizes Pit of 100 Trials
- **Blocks of Wisdom** v2.0 (Oct 2024) — spawns up to 5 customizable blocks in
  nearly any room, implying working access to room/map object data

⚠️ Star Haven's version strings **drift** from upstream GitHub (it lists the
randomizer at v0.1.2 while GitHub is at v2.1). Treat it as a discovery index,
not a version-of-record.

---

## Tooling gaps — where a new toolkit adds value

Ranked by leverage:

1. **Automated cross-region symbol porting.** The single highest-leverage gap.
   spm-decomp explicitly *waits on one*; spm-headers symbols are "manually
   added." With 8 builds and a 3× spread in symbol coverage, this is real pain —
   and it is exactly the pain *you* will hit first, targeting US builds.
2. **Symbol data unification.** spm-headers: *"In the future, that yml will
   become part of this repo and the lsts will be auto generated based on it"* —
   future tense, not done. The decomp's `symbols.yml` is the richer source.
3. **A maintained evt round trip.** The assembler is archived; only the
   disassembler is alive. Either revive text→binary or commit fully to the
   C-macro path (see open questions — this may be an *obsolete* gap, not a real one).
4. **Loader maintenance.** `spm-rel-loader` is foundational and has had **no
   commits since 2022-06-13**. All 2026 activity is in chainrel and spm-headers.
5. **Texture/model tooling.** No dedicated SPM-specific tool surfaced. **But see
   the caveat below — this is likely an integration gap, not a format-research gap.**
6. **Source-rebuild workflow.** Blocked on the decomp being shiftable. Low
   priority; the REL path works.

### What is NOT a gap (common misconceptions, each explicitly refuted in research)

- ❌ *"2.34% decompiled means the decomp is unusable as a modding base"* — wrong;
  modding goes through REL injection, not decomp rebuilds.
- ❌ *"No asset/level editor exists"* — wrong; skawo's editor handles setup files,
  enemy data, randomizer presets, ISO extract/repack, and loading from a Dolphin
  extracted filesystem. It is linked from spm-docs as the canonical setup-file editor.
- ❌ *"SPM modders just reuse TTYD tooling"* — wrong; SPM-specific tools exist,
  though they share TTYD lineage and credit it.

---

## Caveats on this research

**Single-author concentration.** Roughly 70% of technical findings trace to
SeekyCt's repos. That is genuinely how the ecosystem is structured, but source
diversity is low and a **bus-factor risk** applies to anything built on it.

**"Actively maintained" needs calibration.** spm-decomp's 2026-07-21 push is a
one-line change after a ~5-month gap; ~23 commits in 13 months — bursty, not
continuous. spm-docs (2024-08), spm-rel-loader (2022-06), and evt-assembler
(2021, archived) are dormant to varying degrees.

**Argument from absence.** The "no texture/model tooling" gap rests on nothing
surfacing across surveyed repos — not on a positive finding that none exists.
SPM very likely reuses **standard Nintendo Wii asset formats** (BRRES/TPL/SZS),
in which case Wiimms SZS Toolset and BrawlCrate/BrawlBox already open them and
the gap is *integration*, not format research. **Verify this before investing.**

**Attribution/licensing.** The SPM stack is downstream of TTYD work —
spm-rel-loader forks PistonMiner/ttyd-tools and credits PistonMiner and Zephiles;
evt-disassembler credits ttyd-asm; `mod/evt_cmd.h` credits ttyd-tools' evt_cmd.h.
Relevant to licensing (MIT except `mod/`, which is GPLv3).

---

## Open questions to resolve before building

1. **What are SPM's actual texture/model/archive formats on disc** — BRRES/TPL/SZS
   or bespoke? Does the standard Wii toolchain already open them? The `wstrt`
   dependency hints at SZS. *This is the cheapest high-value check: just extract
   your WBFS and look at the file tree.*
2. **What does the "setup file" format skawo's editor manipulates actually
   contain** — room object placement, enemy spawns, camera, triggers? Its
   capabilities define the boundary of what a new toolkit must add.
3. **Is the archived evt-assembler superseded or just abandoned?** Do modders now
   write evt exclusively as C macros against `evt_cmd.h`? Determines whether the
   round-trip gap is real or obsolete.
4. **How much manual work is cross-region symbol porting in practice**, and has
   anyone prototyped the "automated porting setup"? Highest-leverage gap, but its
   difficulty is unquantified.
5. **Is there tooling outside the SeekyCt/Star Haven orbit** — Japanese-language
   communities, GameBanana, older Riivolution-era projects? This survey's sourcing
   was English GitHub/Star Haven-centric.

---

## Environment notes

- Dev box is **aarch64 Linux** (Raspberry Pi); **Windows is also available**.
  Relevant because skawo's editor and parts of the Wii tooling ecosystem are
  Windows/.NET-oriented. devkitPPC, WIT, and the Python tools are cross-platform.
- No Wii tooling installed yet — `wit`, `wszst`, `dolphin-tool` all absent.
- `roms/` holds US rev 0 and US rev 1 as **`.wbfs`** inside 7z archives.

### Suggested first steps

1. Extract a WBFS and dump the disc file tree — answers open question #1 immediately
   and cheaply.
2. Stand up the reference pipeline end to end (devkitPPC + spm-headers +
   spm-rel-loader + a no-op REL) on **eu0** before touching US builds.
3. Only then decide whether `spm-modkit` targets the symbol-porting gap (highest
   leverage) or asset-format integration (most visible payoff).
