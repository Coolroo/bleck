# Hook points — when custom code can safely run

**Living reference.** Two debugging cycles have now been spent on this, both
with the same shape: code that loads and executes correctly, but does nothing,
because it ran at a moment when the thing it talked to did not exist yet.

This document exists so a third cycle is not needed.

---

## The rule

> **`_prolog` patches bytes. A `seq_data` override touches the running game.**

This is not our invention — it is the convention every mod in the SPM scene
follows (`evtpatch`, `spm-practice-codes`, `SPM-RPG-Battles`, `spm-door-rando`).
In all of them, `_prolog` does memory patching *only*: `writeBranch`,
`hookFunction`, `evtpatch` edits to script bytecode reached by name via
`mapDataPtr()` or `getItemUseEvt()`. Nothing that reads or mutates live engine
state runs there.

We learned this the expensive way (D38). It is written down here as a rule
because the failure mode is silent: the call succeeds, returns, and has no
effect.

---

## The four known timings

Earliest to latest. Addresses are eu0.

| # | Where | Reached by | What is alive |
|---|---|---|---|
| 1 | `main + 0x6f8` — the `blr` of `spmarioInit` | `relloader3` | Almost nothing. Before `memInit`, so allocation must come from `OSGetMEM1ArenaHi()` |
| 2 | `relMain + 0x194` | `relloader3`'s legacy mode | Immediately after `relF.rel`'s prolog |
| 3 | `relMain + 0x1b8` = **`0x8023e5fc`** | **the Gecko loader we use** — this is where our `_prolog` runs | Heaps exist. ⛔ **The evt manager does not** |
| 4 | `seq_data[SEQ_*].{init,main}` | a pointer write into the table at `0x804287a8` | Fully live game |

**We run at 3 and hook into 4.** That is the entire architecture of a `bleck`
script module.

### What #3 can and cannot do

✅ Verified working from `_prolog` (D38): patching instructions. A branch written
over `marioGetGameSpeedScale` took effect and was visible on screen.

✅ **And it lasts.** A branch written into DOL text at `_prolog` was still in
place and still being taken 60,000 frames later, across two map changes — the
hook on `npcDispMain` fired 62,480 times (D94). So `_prolog` is early enough to
patch anything the game will call later, not only what it calls immediately.

⚠️ **The flush is what makes an instruction patch real** (D94). A store lands in
the *data* cache and the fetcher cannot see it: two identical patches in one run,
differing only in `dcbst`/`sync`/`icbi`/`isync`, read back the same word and
behaved differently — the unflushed one did nothing at all while looking
perfectly applied. Use `bleck_code_write` / `bleck_code_hook`, which every
generated module carries; see [`code-mods.md`](./code-mods.md).

✅ **A mod declares this rather than writing it** (D95). `code.hooks` installs
from `_prolog`, before `mod_prolog`, with a guard word `bleck` derived from the
base disc's `main.dol`:

```json
"hooks": [{ "function": "npcDispMain", "call": "count_npcs", "mode": "replace" }]
```

⚠️ **`replace` means the original never runs**, so the hooked function's whole
job moves into the mod. ✅ `before` and `after` keep it running (D97) — the
sentence here used to say they were refused at build time, which D95 was right
about and D97 superseded. Both return the *original's* value.

⛔ **Do not stub `effMain`** from a hook. Replacing it counts entries fine and
hangs the map-change sequence: the game sat in `SEQ_MAPCHANGE` for 90 s and never
reached gameplay (D94). 🔶 Something in the transition appears to wait on the
effect driver. `npcDispMain` is the safe hot function to use as a control — it is
a draw pass, so nothing gates on it.

⛔ Verified *not* working from `_prolog` (D38): `evtEntry()`. It returns, and no
script is ever scheduled. The evt manager has not been initialised, so there is
no entry table to allocate from.

⚠️ `evtmgrInit` is declared in `spm/evtmgr.h` but is **not** in
`spm.eu0.lst` — only `evtmgrReInit` (`800d8b2c`) and `evtEntry` (`800d8b88`).
Initialisation state cannot be queried directly, which is why this had to be
established by observation rather than by reading a flag.

### The sequence table

```c
typedef void (SeqFunc)(struct _SeqWork *);
typedef struct { SeqFunc *init, *main, *exit; } SeqDef;
extern SeqDef seq_data[SEQ_COUNT];      /* 0x804287a8, SEQ_COUNT == 6 */
```

Sequences (`spm/seqdrv.h`): `LOGO 0, TITLE 1, GAME 2, MAPCHANGE 3, GAMEOVER 4,
LOAD 5`.

Hooking it is a **data write** — no code patching, no instruction-cache flush,
no trampoline. `seq_data` is in the symbol list, so it resolves by name and no
address needs hardcoding.

⚠️ **Whatever you hook, unhook it.** `.main` runs every frame. `.init` runs on
every entry to the sequence, and gameplay is re-entered after *every map
change* — so a script started from an un-unhooked `.init` would be started again
at every door, compounding silently.

⚠️ **Save the original in `.data`, not `.bss`.** Initialise the pointer to a
non-zero value. The loader allocates the module's bss but nothing documents
whether it *zeroes* it.

---

## Observed results

| Attempt | Hook | Result |
|---|---|---|
| 1 | `evtEntry` directly in `_prolog` | ⛔ nothing — #3 is too early (D38) |
| 2 | `seq_data[SEQ_GAME].init` | ⛔ nothing (D40) |
| 3 | `seq_data[SEQ_TITLE].main` | ⛔ never called — **the sequence is never entered** (D43) |
| 4 | **`seq_data[SEQ_GAME].main`** | ✅ **works** (D43) |

⚠️ **`SEQ_TITLE` is never entered on an unattended boot.** Measured from inside
the game, per frame (D47): zero frames across 200 seconds. The code exists
(`seq_titleMain` at `8017b250`) and a hook installs correctly; it is simply
never called, so it is not a usable hook point.

The real order is **`LOGO -> MAPCHANGE -> GAME -> MAPCHANGE -> GAME`**, loading
`aa4_01` then `ls4_12` — ordinary maps, not menus. 🔶 Almost certainly the
attract demo: with no controller input the game plays the logos for ~2,100
frames and then runs gameplay. Reaching the title screen would need input,
which nothing here injects.

`GAMEOVER` and `LOAD` never ran either, so the generated scaffolding's re-arm
on those sequences is untested rather than wrong.

Gameplay arrives about **45 seconds after boot with no input**, which is what
makes unattended testing possible at all.

⛔ **A script does not survive a map change** (D43). evt state is torn down and
rebuilt, and a script started once stops permanently. So the generated module
does not start-and-unhook: every sequence other than gameplay re-arms a flag,
and gameplay starts the script whenever it is armed. All six `.main` entries are
hooked; only gameplay starts anything.

### Drawing from a `.main` hook

✅ **A `seq_data[].main` override is a legal place to draw text**, and it is
free. Measured on `SEQ_GAME` over 6,198 consecutive frames (D49): no crash, no
hang, and a locked 60 fps throughout — 180 frames per 3 seconds, unchanged from
an unmodded run.

The call sequence is `FontDrawStart` → styling → `FontGetMessageWidth` →
`FontDrawString`, **before** delegating to the real sequence main. That order
comes from `spm-rel-loader`, whose title-screen text is the only known-working
use of this API, and it is what the generated `mod_loaded` banner does.

✅ **`FontGetMessageWidth` works from this context too** — it returned a stable
`362` for a 24-character string, both on the first gameplay frame and 600 frames
later, so the font subsystem is fully up by the time gameplay starts. That
matters because right-aligning anything depends on it.

🔶 Screen space appears to be **centred with y increasing upward** — roughly
x −320..320, y −240..240 — inferred from `spm-rel-loader` centring a string at
`x = -(width * scale / 2)` and placing it near the top with `y = 200`. Nothing
here can see the screen, so exact placement stays unverified.

---

## The diagnostic method

Two techniques, and the second matters more.

**When a symptom cannot distinguish its causes, build one disc carrying several
independent signals, ordered so each depends on strictly more than the last.**

**And better: make the game report on itself.** `scripts/ingame.py` does this
for you — build a mod, boot it, read its report block, shut Dolphin down. The
mod side is `diagnostics/probe.h`.

```
uv run python scripts/ingame.py my-mod --words 10 --watch-gw 30
```
 `dolphin-memory-engine`
(`pip install dolphin-memory-engine`) attaches to the running Dolphin *process*
and reads the emulated address space from outside — no Dolphin configuration, no
fork, stock builds. A module that writes a stage bitmask and counters into a
fixed block turns "nothing happened" into "reached stage 3 of 5", and removes
the human from the loop entirely. That is what finally settled this (D43), after
three rounds of asking someone to watch a screen. Addresses in the table below.

The current diagnostic — [`diagnostics/entry-point-probe.c`](./diagnostics/entry-point-probe.c), kept in the repo because the first one was lost with a scratch directory — carries three:

| Signal | Mechanism | Depends on |
|---|---|---|
| **A** — double speed | instruction patch, applied *from inside the hook* | the hook firing at all |
| **B** — +100 coins once | `pouchAddCoin()` — a direct game function, no evt | the game being live and writable |
| **C** — +1 coin/sec | `evtEntry()` | evt scheduling |

Reading it:

- **A+B+C** — it works; promote the `.main` hook into the emitter
- **A+B, no C** — evt scheduling is still wrong even in a fully live `SEQ_GAME`
- **A, no B/C** — the hook fires but the game is not live yet
- **none** — the `seq_data` write is not taking effect at all

The key design point is that **A moved from `_prolog` into the hook**. In the
first diagnostic it was applied at `_prolog`, which could only prove "the module
ran" — it could not distinguish that from "the hook ran". Moving it inside is
what makes the test decisive.

---

## Useful direct functions

Bypassing evt entirely is often the cheapest way to test whether *anything*
works at a given moment. All resolve by name from the symbol list:

| Symbol | eu0 | Signature |
|---|---|---|
| `pouchAddCoin` | `8014d58c` | `void pouchAddCoin(s32 increase)` |
| `pouchGetCoin` | `8014d57c` | `s32 pouchGetCoin()` |
| `pouchSetCoin` | `8014d548` | `void pouchSetCoin(s32 coins)` |
| `evtEntry` | `800d8b88` | `EvtEntry *evtEntry(const EvtScriptCode *, u32 pri, u8 flags)` |
| `evtGetWork` | `800d87e4` | `EvtWork *evtGetWork()` |
| `evtmgrReInit` | `800d8b2c` | `void evtmgrReInit()` |
| `seqMain` | `8017bf6c` | the sequence dispatcher |
| `seq_data` | `804287a8` | `SeqDef[6]` |

### Addresses for reading the game from outside

| Address | What |
|---|---|
| `0x80512360` | `seqWork` — current sequence at +0x00, stage at +0x04 |
| `0x8050C990` | `evtGetWork()`'s return, a fixed global. `gw[]` at +0x04, so `gw[n]` at +4+4n |
| `0x80005000` | Free scratch for a probe block — unused TRK interrupt table, same address every region |

`evtGetWork()` is worth remembering: it returns the evt manager's work struct,
so a future diagnostic could check whether the manager is initialised *before*
calling `evtEntry`, rather than inferring it from a missing effect.

---

## A fifth timing: inside any function, by name

✅ D95, D96, D97. `code.hooks` writes a branch over a named function's first
instruction from `_prolog`, so a mod's own C runs **whenever the game calls that
function** — a hook point chosen by name rather than from the four fixed
timings above.

⚠️ This table used to read "Two shapes". Since D97 there are **three declarable
shapes** plus the hand-written instrument:

| | `replace` | `before` / `after` | hand-written trace |
|---|---|---|---|
| Original body | never runs | runs, every call | runs, every call |
| Return value | the mod invents one | **the original's** | the original's, recorded |
| Declared in `mod.json` | yes, `code.hooks` | yes, `code.hooks` | no — a pattern over one |
| Cost per call | none | two cache flushes | two cache flushes, 7–10 time-base ticks |
| Unmappable address | warns, installs unguarded | build **error** | n/a |

`before` and `after` are a generated PowerPC assembly wrapper (D97) over the same
mechanism as the trace: restore the original instruction, call the function
through its own symbol, re-install the branch — so both are available on
functions that `replace` breaks. ⛔ Stubbing `effMain` wedges `SEQ_MAPCHANGE`
(D94); **tracing** it ran through four map changes (D96). ⛔ There is still **no
trampoline**; that is what the two flushes buy.

Reach for the hand-written trace when the *instrument* is the point — it records
arguments and results into a report block. Reach for `before`/`after` when the
mod wants to run its own code and does not want to hand-write a detour.
⚠️ Neither can change what the caller receives, and ⛔ neither can intercept a
function taking more than eight integer arguments (D97).

⚠️ Safe timings still apply *inside* a hook. The hook fires whenever the game
calls the function, which may be long before evt is alive — so `evtEntry` from a
hook on something early is the same mistake as `evtEntry` from `_prolog`.

[`code-mods.md`](./code-mods.md#tracing-a-function-instead-of-replacing-it) has
the pattern and its hazards; [`function-behaviour.md`](./function-behaviour.md)
has what it has found.

---

## Open questions

- ✅ ~~Does `seq_data[SEQ_GAME].main` work?~~ Yes (D43).
- ✅ ~~Does a script survive a map change?~~ No — hence the re-arm design (D43).
- ✅ ~~Is `evtEntry(script, 0, 0)` correct?~~ Yes; it returns a valid entry (D43).
- 🔶 **Why does `.init` not work?** Still unexplained. The `evtmgrReInit`
  hypothesis is plausible and untested. It no longer blocks anything.
- 🔶 **Which sequences reset evt state?** `MAPCHANGE` certainly does. `GAMEOVER`
  and `LOAD` are assumed to and are re-armed defensively, but neither was
  observed.
- ❓ **Is `_prolog` safe for anything other than patching instructions?** Only
  instruction patching and `seq_data` writes have been exercised there.

## See also

- [`decision-log.md`](./decision-log.md) — D38 (the first diagnostic), D39 (the
  scene survey that confirmed the `seq_data` technique is prior art)
- [`scripting.md`](./scripting.md) — the language, and what it cannot do
- [`code-mods.md`](./code-mods.md) — native hooks, the other half of the story
- [`function-behaviour.md`](./function-behaviour.md) — what traced functions
  turned out to do
