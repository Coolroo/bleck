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
| 1 | `evtEntry` directly in `_prolog` | ⛔ No script ran. Established that #3 is too early |
| 2 | `seq_data[SEQ_GAME].init` | ⛔ Still no script ran |
| 3 | `seq_data[SEQ_GAME].main` | 🔶 under test |

Attempt 2 is the interesting failure, because the approach is right — it is what
the whole scene does — but **nobody in the scene hooks `.init`.** They all hook
`.main`. That may be convention, or it may be that `.init` runs before the evt
manager is re-initialised for the sequence; `evtmgrReInit` exists, which implies
evt state is torn down and rebuilt across transitions. If our entry is created
before that, it would be wiped.

⚠️ **This is a hypothesis, not a finding.** Attempt 3 tests it.

---

## The diagnostic method

Both cycles were resolved the same way, and it is worth naming as a technique:
**when a symptom cannot distinguish its causes, build one disc carrying several
independent signals, ordered so each depends on strictly more than the last.**

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

`evtGetWork()` is worth remembering: it returns the evt manager's work struct,
so a future diagnostic could check whether the manager is initialised *before*
calling `evtEntry`, rather than inferring it from a missing effect.

---

## Open questions

- 🔶 **Does `seq_data[SEQ_GAME].main` work?** Under test.
- 🔶 **Why does `.init` not?** The `evtmgrReInit` hypothesis above is untested.
- ❓ **Is `evtEntry`'s `(priority, flags)` of `(0, 0)` correct?** Taken from TTYD
  convention, never verified against SPM. If the script is being created but
  immediately filtered out by the scheduler, this is where to look —
  `EVT_FLAG_START_IMMEDIATE` exists in `evtmgr.h`.
- ❓ **Does a script survive a map change?** `evtmgrReInit` suggests not. If it
  does not, a script started once at `SEQ_GAME` would stop working after the
  first door, and re-arming on each entry becomes correct rather than a bug.

## See also

- [`decision-log.md`](./decision-log.md) — D38 (the first diagnostic), D39 (the
  scene survey that confirmed the `seq_data` technique is prior art)
- [`scripting.md`](./scripting.md) — the language, and what it cannot do
- [`code-mods.md`](./code-mods.md) — native hooks, the other half of the story
