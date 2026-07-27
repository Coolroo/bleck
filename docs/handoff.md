# Handoff — picking this up fresh

Last updated 2026-07-27. The scripting language landed (D37) and now **runs**
(D43), after three failed entry points and an unattended memory-readback rig
that finally settled it. Also: an ecosystem survey (D39) and the setup file
format (D42).

This is the conversational context that is **not** already captured elsewhere.
For anything else:

- [`decision-log.md`](./decision-log.md) — why every choice was made (D1–D51)
- [`state-of-spm-modding.md`](./state-of-spm-modding.md) — the ecosystem.
  **Substantially revised 2026-07-27**; read the revision section
- [`scripting.md`](./scripting.md) — the scripting language, and its limits
- [`hook-points.md`](./hook-points.md) — **when custom code can safely run.**
  Two debugging cycles went into this; read it before writing a hook
- [`roadmap.md`](./roadmap.md) — what to build next and what blocks it
- [`disc-layout.md`](./disc-layout.md) — observed facts about the disc
- [`../docs-site/`](../docs-site/) — user-facing docs

---

## Start here

**The scripting track works, and mods can now react to the world.** ✅ A script
compiled by `bleck` runs inside the game, and ✅ can be attached to a named map
so it starts on arrival (D51) — both verified by reading the running game's
memory, not by looking at the screen.

```
[t+45s] seq=GAME   gw[31]=4660 gw[30]=126     *** on_arrive RAN at aa4_01 ***
[t+93s] seq=GAME   gw[31]=4660 gw[30]=3004    *** 60/sec, still alive ***
[t+99s] seq=GAME   gw[31]=4660 gw[30]=3156    *** froze: next map is not hooked ***
```

That last line is the point. The counter *stopping* is what proves the hook is
map-specific rather than firing on any gameplay — evidence from a stopped
counter, not from nothing happening.

There is no longer a single blocking question. Pick from
[next steps](#next-steps) below.

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

⚠️ **Gameplay is reached ~45 seconds after boot with no controller input.** The
game runs `LOGO -> MAPCHANGE -> GAME`, loading `aa4_01` then `ls4_12` — its
attract demo — and never enters `SEQ_TITLE` (D47). So a full boot-and-verify
cycle is unattended and takes about two minutes.

✅ **The rig is now part of the repo**, after being rewritten from scratch three
times in scratch directories:

```
uv run python scripts/ingame.py my-mod --words 10 --watch-gw 30
```

`scripts/ingame.py` builds, boots, reads and always shuts Dolphin down; the mod
side is `docs/diagnostics/probe.h`. **Reach for it before debugging anything
in-game** — three rounds of asking a human to watch a screen produced two wrong
conclusions, and the rig has since settled five questions without one.

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
⛔ Patching `MapData.initScript` deadlocks the map loader; read D51 before
trying it.

326 tests, pylint 10.00/10.

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
| ✅ **A script runs on arrival at a named map** | map-specific, verified by a frozen counter elsewhere (D51) |
| ⛔ **`MapData.initScript` cannot be patched** | installs fine, then deadlocks the map load (D51) |
| ✅ **`.env` is loaded automatically** | tool paths survive between shells; real env still wins |
| ⛔ `SEQ_TITLE` is never entered | zero frames unattended; there is no menu to hook (D47) |
| ⛔ Input cannot be injected | DirectInput plus a locked session (D48) |
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

Anchor to **eu0**. Coverage varies sharply: eu0 documents ~976 symbols, `kr0`
only 456.

⚠️ **There is a much better source** (D39): `spm-decomp/config/EU0/symbols.txt`
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

**Committed mods look empty and that is correct.** `mods/title-invert` and
`mods/tex-koopa` have manifests but no overlays. Re-vendor:

```powershell
bleck mod vendor title-invert lyt/title.bin.uk/arc/timg/mario.tpl
bleck mod vendor tex-koopa    lyt/title.bin.uk/arc/timg/koopa.tpl
```

Then invert pixel data from `0x40` to the end of each — script in
[`../docs-site/guides/first-mod.mdx`](../docs-site/guides/first-mod.mdx).

**Script mods are different**: `mods/speedrun` and `mods/coin-tick` commit their
`scripts/*.evt` source, and the compiled `mod.rel` is regenerated by
`bleck mod build`. Nothing to re-vendor.

---

## Open decisions, carried forward

1. **Licensing.** `bleck` is still **unlicensed**, which technically means
   all-rights-reserved while `docs-site` tells users to clone it. This needs
   settling before any release.

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

3. **Rust rewrite** — deferred. The case rests on distribution and compressor
   speed. Revisit after the code track lands; a PyO3 port of just the compressor
   captures most of the benefit at a fraction of the risk.

4. **Hot reload** — designed for, not built. D37 records the reasoning and the
   verified facts (Riivolution re-reads host files on every disc read; SPM links
   `DVDMgrOpen`/`Read`/`Close`). Estimated 1–3 days. ⛔ Reloading a rebuilt REL
   is ruled out: there is no `OSUnlink`.

---

## Next steps after the open question closes

In rough order of value:

0. ✅ ~~Bake the Gecko loader into the DOL.~~ **Done** (D44).
1. **Emit `SETI` instead of refusing ambiguous literals** (D39). `SETI` (0x33)
   takes its argument raw, bypassing the zone decoder — confirmed from
   decompiled source. `var a = -30000000` is currently a compile error and need
   not be. Small, and removes a papercut the language shipped with.
2. **`peek`/`poke` for `SET_RAM`/`GET_RAM`.** The language reaches 39 of the
   VM's 120 opcodes. Raw memory access is the biggest remaining gap — it is what
   would let a script write an `EvtScriptCode *` into an **NPC, door or item**.
   ⚠️ **Maps are already done and did *not* need it** (D51): `code.maps` watches
   `seqWork.p0` instead, because patching the pointer the game owns deadlocked
   it. Expect the same trap for doors and NPCs — read D51 first.
3. **Switch to the decomp's symbol table** (D39).
   `spm-decomp/config/EU0/symbols.txt` has ~9,566 human-named symbols against
   the lst's 976 — **11×** — and carries sizes and types, so `user_func` targets
   can be validated rather than just resolved. One regex parses it.
4. **`switch`, `IF_FLAG`, detached `spawn`, `SET_PRI`/`SET_SPD`.** Unwritten,
   not blocked.
   ⚠️ `RUN_EVT`/`RUN_CHILD_EVT` are *emitted* nowhere now — the map-hook design
   that used them was ruled out (D51) — so `spawn` starts from scratch.
5. **Native hooks in `bleck mod build`** — a `code.sources` block for C/C++
   alongside `code.script`. Design in [`code-mods.md`](./code-mods.md);
   D38 proves the technique works.
6. **Multiple code mods — an unclaimed problem** (D39). Nobody in this scene
   has solved it: `chainrel` is a three-commit stub with its loader body wrapped
   in `#if 0`, and both major mod distributions tell users to enable one REL mod
   at a time. This is the clearest differentiator available to `bleck`.
   ⚠️ The known gotcha, from `relloader3/util.cpp`: allocate a second REL from
   the *tail* of `HEAP_MAIN` (negative alignment) so `relF.rel` does not shift.
7. **Settle D13 now that the setup format is decoded** (D42). Which of the two
   byte-identical setup copies does the game read — standalone `setup/*.dat`, or
   the copy embedded in some map archives? Change one, boot, observe; change the
   other, compare. An afternoon, and it removes a real footgun that `bleck`
   currently papers over with a build-time warning.
8. **A `setup` reader/writer.** The format is fully specified in
   [`disc-layout.md`](./disc-layout.md) and is trivial — a fixed 100-entry array
   with a version-dependent stride. Enemy placement is the most obviously
   moddable thing on the disc after textures, and no `bleck` code touches it yet.
   ⚠️ Individual entry *fields* are still undocumented beyond position and enemy
   ID; that is the remaining work, not the container.

---

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
- **Setup files exist in two byte-identical copies** and we still do not know
  which the game reads (D13). Now that booting works, this is directly testable —
  and ✅ **the format is fully decoded** (D42), so the experiment can *generate*
  a valid file rather than hand-patch bytes. Structure and the version→stride
  table are in [`disc-layout.md`](./disc-layout.md).
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
