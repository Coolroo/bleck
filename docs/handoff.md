# Handoff — picking this up fresh

Last updated 2026-07-27. The scripting language landed (D37) and now **runs**
(D43), after three failed entry points and an unattended memory-readback rig
that finally settled it. Also: an ecosystem survey (D39) and the setup file
format (D42).

This is the conversational context that is **not** already captured elsewhere.
For anything else:

- [`decision-log.md`](./decision-log.md) — why every choice was made (D1–D78)
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

✅ **And you are no longer limited to those two maps** (D52). A script attached
to `aa4_01` can call `evt_seq_mapchange("he1_01", 0)` and the game goes there —
so any of the 383 maps is reachable without a controller. `mods/goto-map` is a
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
| ✅ **Every disc names itself on screen** | `mod_loaded: <name>` on the title screen, confirmed by eye (D49) |
| ✅ **A script runs on arrival at a named map** | map-specific, verified by a frozen counter elsewhere (D51) |
| ⛔ **`MapData.initScript` cannot be patched** | installs fine, then deadlocks the map load (D51) |
| ✅ **`.env` is loaded automatically** | tool paths survive between shells; real env still wins |
| ⛔ `SEQ_TITLE` is never entered | zero frames unattended; there is no menu to hook (D47) |
| ⛔ Input cannot be injected | DirectInput plus a locked session (D48) |
| ✅ **The game reads the *embedded* setup copy** | control run: swapping markers left both addresses unchanged (D53) |
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

Anchor to **eu0**. Coverage varies sharply: eu0 documents ~976 symbols, `kr0`
only 456.

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
7. ✅ ~~**Settle D13**~~ — **Done** (D53). The game reads the copy **embedded
   in the map archive**; the standalone `files/setup/*.dat` is loaded but never
   used. Proven with a control run — swapping which copy carried which marker
   left both buffer addresses unchanged. `bleck` now names the copy to edit.
8. **A `setup` reader/writer — the clearest next feature.** The container is
   fully specified in [`disc-layout.md`](./disc-layout.md): a fixed 100-entry
   array with a version-dependent stride, and D53 settled which copy to write.
   Enemy placement is the most obviously moddable thing on the disc after
   textures, and no `bleck` code touches it yet.
   ⚠️ Individual entry *fields* are still undocumented beyond position and enemy
   ID; **that is the remaining work, not the container**. `he1_01` is a good
   subject: 3 used entries out of 100, and reachable unattended (D52).

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

---

## ✅ Closed: the enemy that did not spawn (D79)

**Answered, and both recorded hypotheses were wrong.**

`mods/hard-lineland` declared slots 0, 1 (cleared) and 2, and only the first
enemy appeared. The cause is neither the template nor the position:

> **The game stops reading `setup/*.dat` entries at the first empty one.**
> A cleared slot in the middle silently discards everything after it.

```
slot-check  slots 0, 1(clear), 2   npcs[1] slot0
slot-gap    slots 0,          2    npcs[3] slot0 slot1 slot2
```

Same enemy, same positions, one variable. ⛔ "Template 144 is refused here" and
⛔ "the position is off the visible plane" are both dead — an off-plane enemy
would still be *in the NPC list*, and this one never spawned at all.

✅ `bleck` now refuses an edit that would leave a gap, naming the slots it would
orphan. Refusing rather than compacting, because moving entries down would
change the slot numbers a manifest refers to.

### Why it took a day, and what fixed it

Every placement conclusion before this rested on someone saying what they saw,
which cannot tell "did not spawn" from "spawned somewhere I did not look".

`scripts/ingame.py --npcs` now lists live NPCs and the setup slot each came
from — `npcdrv_wp` (`0x805AE188`) to `NPCWork.entries`, filtered on `flag8 & 1`.
⚠️ `NPCWork.num` is the array's **capacity** (80), not a live count.

---

## Where things stand — end of 2026-07-27

Two features landed and are confirmed **in game, by eye**, not by inference:

✅ **Boot maps.** `bleck mod build <mod> --map he1_01`, or `"boot": "he1_01"`
under `code` in a manifest. The disc drives itself to any of the 383 maps
instead of playing the attract demo. Works on a mod with **no code block at
all** — a texture swap gets a small module generated for it (D64).

✅ **Button combinations.** `bleck.yml` names a combination, `mod.json` binds a
script to it, and the compiler injects the mask. Playing the disc by hand:
Lineland on its own, then **1+2** warps to Flipside (D77).

```yaml
# bleck.yml — committed, unlike .env
combos:
  start_map: [1, 2]
```
```json
"code": { "boot": "he1_01", "combos": { "start_map": "warp_home" } }
```

Both work **together**, which matters because four decision-log entries claimed
otherwise. See the retraction below.

### What the button work established

⚠️ **D48 does not say input is unavailable, and reading it that way cost weeks.**
It measured `SendKeys`/`PostMessage`, which post to a message queue Dolphin never
reads. It says nothing about the game reading its **own** controller, which it
does every frame and so can a mod (D66).

| Fact | Where |
|---|---|
| `wpadGetWork()` `0x8023697c`, `statuses` `+0x6C`, `buttonsHeld` `+0x00` | D67 |
| `a=0x0800 b=0x0400 1=0x0200 2=0x0100`, one press each | D68 |
| Bit 31 is **not** a button — test `(held & mask) == mask`, never equality | D67 |
| `plus`, `minus`, `home`, d-pad still 🔶 unverified | D68 |

`mods/button-probe` + `scripts/decode_buttons.py` settle the rest in one run.

---

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

## ✅ Done: compiling several mods into one REL

**Landed and verified in game** (D78). Design in
[`plan-merging.md`](./plan-merging.md), all seven steps marked.

```
[t+45s] seq=GAME  map=aa4_01  gw[28]=2  gw[29]=2
```

`merge-a` writes `gw[28]`, `merge-b` writes `gw[29]`, **both declare
`script main`**, and both ran to completion. Each slot is the other's
positive control — the rule D76 cost six runs to learn.

🔶 **One gap**: two mods that both ship `code.sources` would collide on
`mod_prolog` at link time. Scripts merge cleanly; C does not yet. The plan's
answer is to detect and refuse naming both.

<details><summary>The original plan text, for reference</summary>

The insight: the Gecko loader opens exactly one `/mod/mod.rel`, but **it does
not care how many mods went into it**. Merging at *compile* time produces one
REL, so `chainrel`'s unsolved runtime chaining (D39) is not on this path at all.
D39 calls this the clearest differentiator available to `bleck`.

### Step 1, and it is landable alone

**Parameterise the emitter's identifier prefix.** `_PREFIX = "bleck_"` is a
module constant and every generated identifier derives from it; two mods each
declaring `script main` would collide. Make it per-mod — `bleck_<slug>_` — with
single-mod output **byte-identical**, which the existing tests already assert.

⚠️ Some names are per-**disc**, not per-mod, and must not be prefixed:
`_prolog`, `_epilog`, `_unresolved`, `mod_prolog`, and the sequence-hook
machinery (`bleck_after_seq`, `bleck_seq0..5`, `bleck_hooks`,
`bleck_real_main`). Only per-program names get namespaced: `bleck_script_*`,
`bleck_string_*`, `bleck_map_name_*`, and the map/banner/boot/combo tables.

### Step 2 — a real latent bug to fix on the way

`bleck_map_pending` is a `u32` bitmask, one bit per map hook, so the 33rd hook
shifts past the end. Unreachable with one mod, **plausible once mods merge**,
and silent today. `bleck_combo_down` has the same shape and *is* already
guarded — `emit.MAX_COMBOS` refuses more than 32 with a clear error. Map hooks
need the same treatment.

### Then

- ✅ banner, boot map, map hooks and combos unioned; every mod's `main` started
- 🔶 `mod_prolog`: still the open gap, see above
- ✅ verified in game with two real mods (D78)

</details>

---

## Also open

- 🔶 **`plus`/`minus`/`home`/d-pad masks** — one `button-probe` run each
- 🔶 **The unfired-enemy question** (`mods/slot-check`) — untouched today, and
  worth re-reading in light of D76: it also rests on "nothing appeared"
- 🟢 **Licensing is deliberately deferred** (2026-07-27). It blocks sharing and
  nothing else, and nothing is being shared until the base app exists. Do not
  spend time on it before then — but it *does* have to be settled before the
  first release, since `docs-site` tells people to clone a repo that is
  all-rights-reserved by default.
- 🟡 **PyYAML is now the first runtime dependency**, against a comment in
  `pyproject.toml` that defended having none. Argued in
  [`plan-config.md`](./plan-config.md); reversible
- 🔶 **Diagnostic mods to prune**: `boot-combo` and `boot-observe` exist only to
  investigate the bug D76 retracted. `button-probe` and `mapchange-probe` are
  worth keeping
