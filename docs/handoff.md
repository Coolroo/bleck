# Handoff — picking this up fresh

Last updated 2026-07-27, after the scripting language landed (D37) and two
failed attempts to make a script actually run (D38, D40).

This is the conversational context that is **not** already captured elsewhere.
For anything else:

- [`decision-log.md`](./decision-log.md) — why every choice was made (D1–D40)
- [`state-of-spm-modding.md`](./state-of-spm-modding.md) — the ecosystem.
  **Substantially revised 2026-07-27**; read the revision section
- [`scripting.md`](./scripting.md) — the scripting language, and its limits
- [`hook-points.md`](./hook-points.md) — **when custom code can safely run.**
  Two debugging cycles went into this; read it before writing a hook
- [`roadmap.md`](./roadmap.md) — what to build next and what blocks it
- [`disc-layout.md`](./disc-layout.md) — observed facts about the disc
- [`../docs-site/`](../docs-site/) — user-facing docs

---

## Start here: the one open question

**Why will a compiled script not run?**

Two attempts have failed. This is the only unverified link left in the whole
scripting track, and everything else is proven.

| Attempt | Hook | Result |
|---|---|---|
| 1 | `evtEntry` directly in `_prolog` | ⛔ nothing (D38) |
| 2 | `seq_data[SEQ_GAME].init` | ⛔ nothing (D40) |
| 3 | `seq_data[SEQ_GAME].main` | 🔶 **built and waiting — `out/diag2.wbfs`** |

### Do this first

The third attempt is already built. No rebuild needed:

```powershell
bleck launch --batch out\diag2.wbfs
```

Get into a level. It carries **three independent signals**, each depending on
strictly more than the last:

| Signal | Look for | Proves |
|---|---|---|
| **A** | Mario at 2x speed | the hook fired at all |
| **B** | **+100 coins**, once, immediately | the game is live and writable |
| **C** | +1 coin/sec afterwards | evt scheduling works |

Reading it:

- **A+B+C** — it works. Promote the `.main` hook into
  `bleck/script/emit.py`'s `_FOOTER`, rebuild `coin-tick`, mark D40 resolved,
  and update `scripting.md`'s Unproven section and the roadmap.
- **A+B, no C** — evt scheduling is wrong even in a fully live `SEQ_GAME`. Next
  suspect is `evtEntry(script, 0, 0)`: those priority/flags came from TTYD
  convention and were never checked against SPM. `EVT_FLAG_START_IMMEDIATE`
  exists in `evtmgr.h`.
- **A only** — the hook fires but the game is not live yet.
- **none** — the `seq_data` write is not taking effect at all.

The probe source is [`diagnostics/entry-point-probe.c`](./diagnostics/entry-point-probe.c),
kept in the repo because the first one was lost with a scratch directory.

### Why attempt 2 failed, probably

⚠️ **Every mod in the scene hooks `.main`. None hooks `.init`.** That was visible
in the D39 survey and got treated as a curiosity instead of a warning.
`evtmgrReInit` exists, which implies evt state is torn down and rebuilt across
sequence transitions — so an entry created at `.init` would plausibly be wiped
moments later. Untested; it is why attempt 3 hooks `.main`.

The narrow lesson, recorded in D40: **when prior art consistently does X and we
do X', the burden is on X'.**

Full timing reference in [`hook-points.md`](./hook-points.md).

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

⛔ **But no compiled *script* has ever been observed running** (D40). The module
executes; the thing it is supposed to start does not. That is the open
question above, and it is the only one.

**A scripting language exists** (D37). `bleck` compiles a small language to
`evt`, the game's own bytecode VM — 120 opcodes, cooperative scheduling, ~444
native builtins. No interpreter is shipped. See [`scripting.md`](./scripting.md).

253 tests, pylint 10.00/10.

### What is verified, and what is not

| | |
|---|---|
| ✅ LZ77, U8, format detection, extract/build, overlays, chains, conflicts | byte-exact on 383/383 archives |
| ✅ Asset mods boot and render | D25 (Linux), D36 (Windows) |
| ✅ A `bleck`-built REL loads and executes | D38 — the diagnostic's Signal A |
| ✅ Scripts compile to correct bytecode | hand-verified against the opcode table |
| ✅ Scripts link, resolving game functions by name | `elf2rel` + `spm.eu0.lst` |
| ✅ Our REL is byte-identical once staged | hash-checked overlay vs `build/` |
| ⛔ **A script actually runs in-game** | **never observed, two attempts failed** |

---

## Setup you will need

### Environment variables — set these permanently

`$env:` does not persist between shells. Two sessions were lost to this; both
`wit` and `Dolphin` had to be found by searching the filesystem.

```powershell
setx BLECK_WIT         "C:\Users\Wyatt\tools\wit\bin\wit.exe"
setx BLECK_DOLPHIN     "C:\Users\Wyatt\tools\dolphin\Dolphin.exe"
setx BLECK_SYMBOLS_DIR "W:\Repos\bleck\symbols"
```

### Symbol lists — required for code mods, not shipped

Compiling a script needs `spm.eu0.lst` from
[spm-headers](https://github.com/SeekyCt/spm-headers) (`linker/`). `bleck` does
not vendor it, deliberately — see "Licensing" below.

⚠️ **It currently exists only in a session scratch directory, which is
temporary.** Put a copy somewhere permanent — `symbols/` in the repo root is
what `BLECK_SYMBOLS_DIR` defaults to — or the next code-mod build will fail with
"no symbol list for 'eu0'".

Anchor to **eu0**. Coverage varies sharply: eu0 documents ~976 symbols, `kr0`
only 456.

⚠️ **There is a much better source** (D39): `spm-decomp/config/EU0/symbols.txt`
carries ~9,566 human-named symbols — **11x** the lst — with sizes and types, and
parses with one regex. Switching to it is on the next-steps list.

### Dolphin — the two silent traps

⚠️ **These may be avoidable entirely** (D39). `wstrt patch main.dol --add-sect
X.gct` bakes the Gecko code handler *into the disc*, which removes both traps
and works on real hardware. Untried here. Until then:

Both are already configured on this machine, and both fail *invisibly* if not:

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
| `roms/` | Disc images. Gitignored. Supply your own. |
| `extracted/eu0` | The PAL rev 0 base. Regenerate with `bleck extract`. |
| `mods/*/overlay/` | Gitignored — extracted game assets, and generated `mod.rel`. |
| `build/`, `out/` | Staging and images. Regenerable. |
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

0. **Bake the Gecko loader into the DOL** (D39) — the highest value-per-effort
   item on this list. `wstrt patch main.dol --add-sect X.gct` embeds the code
   handler *and* the codes into a new TEXT section at `0x80001800`. That deletes
   both silent setup traps at once: no `R8PP01.ini` under two sections, no
   `EnableCheats`. And it works on real hardware. `wstrt` is Wiimms SZS Toolset,
   a separate tool from `wit`, so it would be a new dependency.
1. **Emit `SETI` instead of refusing ambiguous literals** (D39). `SETI` (0x33)
   takes its argument raw, bypassing the zone decoder — confirmed from
   decompiled source. `var a = -30000000` is currently a compile error and need
   not be. Small, and removes a papercut the language shipped with.
2. **`peek`/`poke` for `SET_RAM`/`GET_RAM`.** The language reaches 39 of the
   VM's 120 opcodes. Raw memory access is the biggest single gap — it is what
   lets a script write an `EvtScriptCode *` into an NPC, door or item, which is
   how event mods are actually built. Roughly 30 lines.
3. **Switch to the decomp's symbol table** (D39).
   `spm-decomp/config/EU0/symbols.txt` has ~9,566 human-named symbols against
   the lst's 976 — **11×** — and carries sizes and types, so `user_func` targets
   can be validated rather than just resolved. One regex parses it.
4. **`switch`, `IF_FLAG`, detached `spawn`, `SET_PRI`/`SET_SPD`.** Unwritten,
   not blocked.
5. **Native hooks in `bleck mod build`** — a `code.sources` block for C/C++
   alongside `code.script`. Design in [`code-mods.md`](./code-mods.md);
   D38 proves the technique works.
6. **Multiple code mods — an unclaimed problem** (D39). Nobody in this scene
   has solved it: `chainrel` is a three-commit stub with its loader body wrapped
   in `#if 0`, and both major mod distributions tell users to enable one REL mod
   at a time. This is the clearest differentiator available to `bleck`.
   ⚠️ The known gotcha, from `relloader3/util.cpp`: allocate a second REL from
   the *tail* of `HEAP_MAIN` (negative alignment) so `relF.rel` does not shift.

---

## Things worth not rediscovering

- **`_prolog` runs far too early to touch game subsystems** (D38). It is fine
  for patching instructions and nothing else. Anything needing the game to be
  alive must hook `seq_data` and run later. Full timing table in
  [`hook-points.md`](./hook-points.md).
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
  which the game reads (D13). Now that booting works, this is directly testable.
- **The docs-site dev server has still never been started.** `bun run check`
  passed before the scripting pages were added; nothing has rendered visually.
