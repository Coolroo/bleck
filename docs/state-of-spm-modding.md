# State of Super Paper Mario Modding (as of 2026-07-26)

Research snapshot compiled to orient the `spm-modkit` project. All repo metadata
(push dates, stars, percentages) was verified on 2026-07-26 and will drift.

> ⚠️ **Substantially revised 2026-07-27.** A second, much deeper survey ran a day
> later and corrected several conclusions below — most importantly that
> `chainrel` is a non-working stub, and that the ecosystem is considerably
> broader than "overwhelmingly one author". **Read
> [the 2026-07-27 revision](#the-2026-07-27-revision) at the end before trusting
> the ranked gap list or the community section.** Original text is left intact;
> corrections are marked there.

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

⚠️ **This matters for you specifically** — `work/roms/` holds *Super Paper Mario (USA)*
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
- `work/roms/` holds US rev 0 and US rev 1 as **`.wbfs`** inside 7z archives.

### Suggested first steps

1. Extract a WBFS and dump the disc file tree — answers open question #1 immediately
   and cheaply.
2. Stand up the reference pipeline end to end (devkitPPC + spm-headers +
   spm-rel-loader + a no-op REL) on **eu0** before touching US builds.
3. Only then decide whether `spm-modkit` targets the symbol-porting gap (highest
   leverage) or asset-format integration (most visible payoff).

---

# The 2026-07-27 revision

A second survey, prompted by a pointer to
[Flipside-Mod-Manager](https://github.com/L5050/Flipside-Mod-Manager), went
considerably deeper than the original snapshot. Recorded in D39; this section is
the reference form.

⚠️ **Security warning first.** ⚠️ **Attribution corrected in D41 — the wiki page
itself is clean and unedited since March 2026; the payload came from the serving
layer, not the page.** `https://tcrf.net/Notes:Super_Paper_Mario` — linked as a
resource from `spm-docs` — served **no game documentation at all** to an
automated fetch.
It served a prompt-injection payload addressed "to LLMs", falsely claiming the
user had requested it, instructing the reader to truncate files to zero bytes
and circularly swap file contents, with a disclaimer that TCRF "isn't
responsible for damage". Not complied with. **Treat that URL as hostile to
automated tooling.** Unknown whether page-specific vandalism or broader.

## Corrections to the original snapshot

| Original claim | Correction |
|---|---|
| "overwhelmingly centered on one author: SeekyCt" | ⚠️ **Overstated.** Seeky supplies the *foundations*, but **JohnP55** (`evtpatch`, `spm-porter`, `SPMNetMemoryAccess`), **L5050** (Flipside-Mod-Manager, several large mods), **shiken-yme**, **skawo**, **AchtungKatse** and others carry substantial independent work. ~8–10 active technical contributors. |
| `chainrel` listed as live 2026 activity and the answer to multi-mod | ⛔ **It is a three-commit stub.** The loader body is wrapped in `#if 0`; what exists is a boot-time picker UI drawing `"test string"` ten times. Even the dead code is single-successor (`mod.rel` → `chain.rel`), not N mods. |
| "`spm-rel-loader` … no commits since 2022-06-13" — flagged as a maintenance gap | ✅ True, but **it has been superseded**, not abandoned. `spm-loaders`/`relloader3` is the current loader. |
| Gap #2: "The decomp's `symbols.yml` is the richer source" | ⚠️ **There is no `symbols.yml`.** The real files are per-version plain text: `config/EU0/symbols.txt`. The "richer source" conclusion holds, and is stronger than stated — see below. |
| Gap #5: "No dedicated SPM texture/model tool surfaced" | ⚠️ **Superseded.** `SPME` does U8/TPL/LZSS and `map.bin ↔ FBX`; `Flint` is a message editor; `SpmViewer` and `spm-level-dumper` exist. See "Asset tooling" below. |
| Gap #3: "a maintained evt round trip" | ✅ Confirmed a real gap. `evt-assembler` is archived (2021), ~200 lines, no expressions, macros or labels. `bleck`'s compiler is already well past it. |

## The unclaimed problem: multiple code mods

⛔ **Nobody has solved it.** This is the clearest differentiator available.

- Flipside-Mod-Manager README: *"assume that you can only have one rel mod
  installed at a time"*. It hard-codes the assumption — `mod.rel` is excluded
  from backup, and uninstall does `remove_all(files/mod)`.
- `spm-lunatic-pit` README: *"Please do not enable any more than one SPM mod at
  one time, as they are not cross-compatible."*
- `relloader3` loads exactly one file, `break`ing on first match.
- Several mods carry a copy-pasted `include/chainloader.h` declaring
  `void tryChainload()` with **no implementation anywhere in the tree**.
- The scene's shared `hookFunction()` writes a branch over instruction 0 and
  builds a trampoline, so **two mods hooking the same function silently clobber
  each other** — the actual hard part, and unaddressed.

⚠️ **The gotcha whoever solves it will hit**, from `relloader3/util.cpp`:

```cpp
// Use negative alignment to allocate from tail so that relF.rel won't shift
return MEMAllocFromExpHeapEx(handle, size, -alignment);
```

There is also a `HEAP_MEM1_UNUSED` heap; before `memInit` you must carve from
`OSGetMEM1ArenaHi()` instead.

## The Gecko code can travel inside the disc

The most directly useful practical finding. Flipside-Mod-Manager does:

```
wstrt patch extracted/sys/main.dol --add-sect ./gct/EU0.gct
```

Wiimms SZS Toolset's [`--add-sect`](https://szs.wiimm.de/info/add-section.html)
creates a **new TEXT section at `0x80001800` holding an internal copy of
`codehandleronly` plus the codes, and patches the DOL entry to branch into it.**

Consequences: no `R8PP01.ini`, no `EnableCheats`, no Riivolution, no USB-loader
cheat engine — on emulator *or* hardware. The claim in `code-mods.md` that "the
Gecko code is still required" is true but has this escape hatch. 🔶 Not yet
tried here; `wstrt` is a separate tool from `wit`.

## Loaders: `spm-loaders` supersedes `spm-rel-loader`

`relloader3` defines an actual platform ABI:

- **Fixed reserved RAM `0x80004200`–`0x800060bb`** — the unused TRK interrupt
  table, at the same address in every region and revision.
- **Payload header, magic `SPMP`**: `{headerMagic, headerVersion, payloadMagic,
  payloadVersion, context, loadAddress, entrypoint, hookAddress,
  implementationType, implementationVersion}`. `implementationType` is
  0 gecko / 1 DOL patch / 2 Riivolution / 3 save exploit — **so a mod can ask at
  runtime how it was loaded.**
- **Region filenames** `./mod/eu0.rel`, `us2.rel`, … with `mod.rel` as legacy
  fallback. Also loads from NAND.
- **Documented size budgets:** saveloader `0xf4c`; **Dolphin's Gecko codehandler
  caps codes at `0xcb0`, described as "the current bottleneck"**; relloader3
  itself `0x1ebc`.

## `evt` at runtime: `evtpatch`

[JohnP55/evtpatch](https://github.com/JohnP55/evtpatch) is how this scene
actually modifies vanilla game logic, and it is complementary to compiling new
scripts rather than competing with it.

- API: `hookEvt`, `hookEvtByOffset`, `hookEvtReplace`, `hookEvtReplaceBlock`,
  `patchEvtInstruction`.
- **It adds two opcodes to the VM** — `Call` and `ReturnFromCall`, giving `evt`
  a call stack it lacks natively — by patching `evtmgrCmd`'s dispatcher and
  **bypassing `make_jump_table`'s opcode bound check at `+0xe0`**.
- ⚠️ It rebuilds jump tables after mutation, because `make_jump_table` caches
  `lbl` positions at script-entry time. **A constraint `bleck` will hit the
  moment it emits `LBL`/`GOTO`, which it currently does not.**
- Scripts are reachable by name from a REL — `mapDataPtr("he3_01")->initScript`,
  `getItemUseEvt(87)` — so hooking an existing map or item needs no file
  surgery at all.

> ⚠️ **Correction, 2026-07-28.** That last point turned out to be the important
> one, and `bleck` now uses it: `code.patches` replaces one instruction of a
> vanilla map or item script in place with a `USER_FUNC` into `mod.rel` (D89,
> D90, D92). ⛔ It does **not** do the rest of what `evtpatch` does — no
> dispatcher changes, no new opcodes, no insertion or deletion. The jump-table
> constraint above is precisely why: same-size replacement is the one mutation
> that moves no label. ⚠️ `bleck` walks `itemEventDataTable` directly rather
> than calling `getItemUseEvt`, which returns a fallback for an unknown id and
> would silently patch a shared script (D92).

## Symbols: the decomp is 11× richer than the lst

| Source | Symbols (eu0) | Sizes/types? |
|---|---|---|
| `spm-headers/linker/spm.eu0.lst` — what `bleck` uses | **1,111** ⚠️ *(this table said 976; the file has 1,111 `addr:name` entries)* | no |
| `spm-decomp/config/EU0/symbols.txt` | **43,944 total, ~9,566 human-named** | **yes** |

One regex parses it:
`^(\S+)\s*=\s*(\.?\w+):0x([0-9A-F]+);\s*//\s*(.*)$`, attributes
`type:{function,object,label}`, `size:0x…`, `scope:…`. Filter
`^(@|fn_|lbl_|jumptable_)` for the meaningful set.

Also: **`L5050/spm-headers` is ahead of upstream** — eu0 `34,330 B` vs
`33,661 B`, with commits adding map, `itemMain` and `mario_pouch` symbols.

⚠️ **`spm-decomp/src/evtmgr_cmd.c` (3352 lines) is fully decompiled** and is the
ground truth for every opcode handler. It is what settled `SET`/`SETI`/`SETF`
(D39). ⚠️ But `evtGetValue`/`evtSetValue`/`evtGetFloat`/`evtSetFloat` are **not**
decompiled — zone-dispatch semantics are documented only by ttydasm's
reimplementation.

## `evt` semantics: the canonical references

1. **[`ttyd-opc-summary.txt`](https://github.com/PistonMiner/ttyd-tools/blob/master/ttyd-tools/docs/ttyd-opc-summary.txt)**
   — 257 lines, `Hex | Dec | Original Mnemonic | ttydasm Mnemonic | Summary` for
   every opcode. **The best evt reference in either community.**
2. `spm-decomp/src/evtmgr_cmd.c` — matching C for the handlers.
3. `ttydasm.cpp`'s `categorizeExpr`/`exprToString` — the expression-zone
   decoder, with SPM's bases already `#ifdef GAME_SPM`'d in.

⚠️ **SPM vs TTYD differ in exactly one place:** SPM inserts `ClampInt` after the
float mem-ops, so **every opcode from `0x4A` up is shifted by one** between the
two games. Also `cAddrBase`/`cFloatBase` differ (SPM `-270000000`/`-240000000`;
TTYD `-250000000`/`-230000000`). Everything else is shared.

`evt-disassembler --cpp` emits the same `evt_cmd.h` macro form `bleck` targets —
a free round-trip oracle. ⚠️ It needs a **RAM dump**, not a file.

## Asset tooling — better than the original snapshot claimed

- **[SPME](https://github.com/InconspicuousCactus/SPME)** (C++) — `u8
  extract/compile`, `tpl dump`, `map to_fbx`, `map from_glb`, `lzss
  decompress/compress`, plus an OpenGL preview. **Ships an ImHex pattern file**
  for the map format. Known limits, from its own README: cannot generate
  `cameraroad.bin`, `setup/*.bin` or `bg/*.tpl` (new maps must be
  "frankensteined" from an existing one); textures >512×512 hang the game; no
  triangle-strip generation; **"LZSS compression is not implemented correctly"**.
- **[Flint](https://github.com/Luma48/Flint)** (PyQt5) — message/text editor with
  in-editor rendering preview; outputs Riivolution patches.
- **[skawo's editor](https://github.com/skawo/Super-Paper-Mario-Level-Editor-Randomizer)**
  — setup/enemy-spawn editor plus randomizer, as the original snapshot said.
- **[spm-level-dumper](https://github.com/BraidenPsiuk/spm-level-dumper)** — dumps
  300+ levels' geometry and collision to `.obj`.
- **PistonMiner's 010 Editor templates** — `MarioSt_CameraRoad.bt`,
  `MarioSt_AnimGroupBase.bt`, `MarioSt_WorldData.bt`. `CameraRoad.bt` is likely
  the head start SPME's TODO is missing.
- **noclip.website** renders SPM maps; its TypeScript source is an independent,
  readable implementation of the format.

The scene's own approach is notable: **runtime patching rather than file
editing.** `SPM-RPG-Battles` swaps TPL entries in RAM and `.incbin`s custom art
into the REL rather than rebuilding archives.

## Region porting

[JohnP55/spm-porter](https://github.com/JohnP55/spm-porter) — Python, with
pre-computed match CSVs (`pal0-us0.csv`, `pal0-jp0.csv`, …) generated by
**stebler's `portfinder` from mkw-sp**. ⚠️ *"Currently only supports porting
.text (code addresses)."*

This is the answer to the original snapshot's gap #1, and it partly exists.

## Community

| Venue | Link |
|---|---|
| **SPM Speedrunning Discord** — the primary hub, where RE and modding discussion happens | https://discord.gg/dbd733H |
| Star Haven — umbrella Paper Mario modding community (~5.1K) | https://discord.com/invite/WuKt67e |
| L5050's server — Flipside-Mod-Manager support | https://discord.gg/CeXnez2Bj7 |
| Paper Mario Technical Knowledge Base — ⚠️ SPM page explicitly under construction | https://papermariotkb.wiki.gg/ |

⚠️ **`docs.starhaven.dev` is Paper Mario 64 only** — no SPM content.
⛔ **No SPM mod has a written postmortem.** Knowledge transfer is Discord plus
reading each other's source. That is the ecosystem's largest documentation gap,
and an argument for keeping this project's decision log public.

## Licensing map

| Project | License |
|---|---|
| `spm-headers` `include/`, `decomp/`, `linker/` | **MIT** |
| `spm-headers/mod/` | GPLv3 |
| `spm-rel-loader`, `evtpatch`, `evt-disassembler`, `evt-assembler`, L5050's mods | **GPLv3** |
| **`Flipside-Mod-Manager`** | ⚠️ **none — all rights reserved** |

⚠️ **The trap:** FMM has no LICENSE file, but its `src/Rel Loader.asm` is plainly
derivative of SeekyCt's **GPLv3** `spm-rel-loader/loader/loader.s` — same
structure, same `relWork` flag-byte protocol, extended with more region tables.
The `gct/*.gct` blobs are its assembled output. **Do not copy from FMM.** Take
the loader from `spm-rel-loader` under GPLv3, or rebuild from published
addresses — addresses are facts, and facts are not copyrightable.

⚠️ Also: **`spm-rel-loader` re-bundles the MIT headers under its repo-wide GPLv3
LICENSE.** Always take headers and lsts from `spm-headers`.

## Odds and ends worth not rediscovering

- **Save-file code execution** (`spm-loaders/saveloader`): a crafted save
  overflows a stack buffer via a fake item description, firing when the player
  opens the items menu. Four stages, survives reboot. **Unmodified disc, no
  Gecko, no Riivolution, on retail hardware.**
- **Dolphin detection**, credited to TheLordScruffy:
  `IOS_Open("/sys", 1) == -106`, falling back to probing `/dev/dolphin`.
- **Mods persist state in unused `GSW` slots** (`gsw[1900]` etc.) rather than
  changing the save format — free persistence, no compatibility break. ⚠️ But
  `spm-loaders`' save exploit also claims save space; writing there collides.
- **Networking from inside the game**: `SPMNetMemoryAccess` runs an HTTP server
  on the Wii exposing read/write/msgbox, with a Python client. A better RE
  feedback loop than watching memory in Dolphin.
- **`spm-docs/misc/`** is an under-mined trove: `mapscriptlocs.txt` (every map's
  init-script address in both rel variants), `dolscriptlocs.csv` /
  `relscriptlocs.csv` (likely evt script locations), `filemap.txt`,
  `setupfiles.md`, `wiidungeon.md` (the Pit of 100 Trials is defined by an
  LZ-compressed XML file), `utilcodes.txt`.
- ⛔ **`SPM-RPG-Battles` has no usable README** despite being the largest mod
  codebase in the scene (custom badge system, menus, NPC RPG driver, save
  manager, sound and texture patching). **The single richest unmined source.**

## What did not change

Nothing found supersedes the D37 decision to compile to `evt` rather than ship a
VM. **No one else has a script compiler** — `evt-assembler` was the closest and
it is archived and far weaker. `bleck` compiles *new* scripts; the scene patches
*existing* ones at runtime. Those are complementary.

> ⚠️ **Correction, 2026-07-28.** "Complementary" understated it: `bleck` now
> does both. `code.patches` mutates existing scripts (D89–D92) and `code.hooks`
> replaces a game C function by name (D94, D95), each declared in `mod.json`
> with a guard that refuses rather than writes on a mismatch. ⛔ What is still
> not done is the dispatcher surgery `evtpatch` performs, and there is no
> trampoline — a hooked function's original body never runs.

> ⚠️ **Correction, 2026-07-28 (second).** The final clause above was
> unconditional and is now wrong: it is only true of `mode: "replace"`.
> `code.hooks` accepts `before` and `after` as well (D97), and under those the
> original body **does** run — reached by restoring the patched instruction
> around the call, generated as a PowerPC assembly wrapper per hook. ⛔ "There is
> no trampoline" stands as written; the detour pays two cache flushes per call
> where a trampoline would pay none. Both modes return the *original's* value, so
> a handler still cannot change what the caller receives, and ⛔ a function taking
> more than eight integer arguments cannot be intercepted at all.
