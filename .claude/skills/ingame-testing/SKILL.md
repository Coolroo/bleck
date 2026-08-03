---
name: ingame-testing
description: Use before debugging, confirming or doubting anything that happens inside the running game — a hook that may not have fired, a value you want to see, a map that may not load. Covers scripts/ingame.py (the unattended build/boot/read/shutdown rig), its flags, the log it always writes, and the four ways a run lies to you.
---

# In-game testing with `scripts/ingame.py`

The rig builds a mod, boots it in Dolphin, reads a report block out of the
running process with `dolphin-memory-engine`, and stops Dolphin — unattended,
including on failure and on Ctrl-C.

```bash
uv run python scripts/ingame.py my-mod --words 12 --watch-gw 30
```

**Reach for it before debugging anything in-game.** Three rounds of asking a
human to watch a screen produced two wrong conclusions (D38, D40); the rig has
settled seven questions since without one.

## The mod side

`docs/diagnostics/probe.h` — copy or include it, it depends on nothing.

```c
#include "probe.h"

void mod_prolog(void)
{
    probeReset();
    probeMark(PROBE_STAGE_LOADED);
    PROBE(4) = someInterestingPointerValue;
}
```

| | |
|---|---|
| `PROBE_BASE` | `0x80005000` — unused TRK interrupt vector table, same address in every region |
| word 0 | `PROBE_MAGIC` = `0x424C434B` (`'BLCK'`) |
| word 1 | stage bitmask: `PROBE_STAGE_LOADED` / `_HOOKED` / `_RAN` |
| words 2+ | `PROBE_FIRST_FREE` — yours |

⚠️ **Word 0 is the whole point.** Without a magic, "the mod never loaded" and
"the mod ran and reported zero" read identically — which is the ambiguity the
mechanism exists to remove. `probeReset()` clears 32 words first, so a previous
boot's values cannot be mistaken for this one's.

Only one mod can use the block at a time. That is fine: the Gecko loader runs
one module anyway.

## Flags that matter

| flag | default | what it is for |
|---|---|---|
| `--words N` | 8 | how many probe words to print |
| `--watch-gw N [N…]` | — | also read these `evt` global-work slots (`evtGetWork()` at `0x8050C990`, `gw[]` at `+0x04`) |
| `--seconds N` | 180 | how long to watch |
| `--probe ADDR` | `0x80005000` | if the mod parks its block elsewhere |
| `--map NAME\|ID` | — | boot straight to a map instead of the attract demo. ⛔ Incompatible with `--no-build` — it is built into the disc |
| `--npcs` | off | list live NPCs and which setup slot each came from, so "how many enemies spawned" is measured (D76) |
| `--no-build` | off | boot the existing `work/build/<mod>.wbfs` as-is |
| `--riivolution` | off | build and boot a Riivolution patch instead of a disc image |
| `--state PATH` | — | load a Dolphin save state instead of booting cold |
| `--slow` | off | normal speed; the default is unlimited, which boots faster |
| `--find HEX […]` / `--find-at S` | —, 80 | search MEM1/MEM2 for byte patterns once the game is up |
| `--log PATH` | `work/build/ingame.log` | where the transcript goes |
| `--allow-other-dolphins` | off | see below |
| `--press BUTTON […]` | — | **attended only**, Windows — see below |

## ⚠️ Read the log; never re-run to widen a query

Every run writes a complete transcript to `work/build/ingame.log` and it is
always flushed. A run costs **2–3 minutes**; re-reading the log costs nothing.

Asking for `--words 9` when the answer sat in word 10 has already cost a whole
repeat run. **Ask for more words than you think you need — they are free.**

See the `slow-command-discipline` skill for the price list of everything else.

## The seven ways a run lies

**1. ⛔ Controller input cannot be injected unattended (D48).** Anything behind
a button press needs a human at the keyboard. Gameplay is reached **~45 s** into
a cold boot, and the attract demo loads `aa4_01` then `ls4_12` — which is what
makes map hooks testable without one. `--map` reaches anywhere else (D52);
`example-mods/goto-map` is the worked example.

⚠️ **`--press` is the narrow exception, and it is attended.** `scripts/keys.py`
uses `SendInput` with hardware scan codes, which does reach Dolphin where the
`SendKeys`/`PostMessage` of D48 did not — but it needs Windows, an unlocked
session and Dolphin in the foreground. `--press 1+2` holds both. Everything
else in the rig works on a locked machine. `keys.py` lives in `scripts/` and
must stay there; `tests/test_boundaries.py` enforces that a modding toolkit
does not ship input synthesis.

**2. ⚠️ This host has the REL loader enabled as a Dolphin cheat (D86).**
`%APPDATA%\Dolphin Emulator\GameSettings\R8PP01.ini`, under `[Gecko_Enabled]`,
with `EnableCheats = True`. **A mod runs even when the DOL carries no loader at
all.** Before concluding that an embedded loader worked, move that file aside
and re-run.

**3. ⚠️ Another Dolphin already running poisons the read.**
`dolphin-memory-engine` attaches to *a* Dolphin, not necessarily the one this
launched; if it picks an idle one, every read reports nothing and that looks
exactly like a broken mod. The rig refuses to start and prints the
`Stop-Process -Id <pid> -Force` line. `--allow-other-dolphins` overrides it, and
you generally do not want to.

**4. ⚠️ Report the *effect*, not the setup (D51).** A map hook installed
perfectly by every mechanical check — valid pointer, right offset, original
preserved — and still froze the game. Only a probe value showing the script had
never run exposed it. "Installed: yes" would have read as success.

Related: **a probe must report the precondition it depends on**, not only the
value it went looking for. Dolphin exiting on its own is reported as a result,
not an inconvenience — it usually means the game crashed, and running out the
clock instead makes a hard crash look like a mod that did nothing.

**5. ⛔ `gw` is shared with the game's own scripts (D271).** The evt global work
slots are not yours. After the attract demo changed map to `ls4_12`, seven of
fourteen watched slots took **new values every sample** — `gw[0]` read 192, then
4,055,018,496, then 0, then 4,054,967,296 in nine seconds.

⚠️ **A `gw` reading is only trustworthy while it stays stable across samples.**
Take at least two and compare. D184's ten measurements survive because that run
never left `aa4_01`, which was luck rather than design.

🔶 **The probe block at `0x80005000` is not shared.** A probe that writes there
instead of into `gw` does not have this problem, and a new one should.

**6. ⚠️ `--words` and `--watch-gw` read different memory.** `--words` prints the
probe block; `--watch-gw` reads evt slots. A mod that writes `gw` shows
**nothing** under `--words`, and a screenful of zeroes from a block nothing ever
touched reads exactly like a script that never ran. It cost a whole run.

⚠️ `--watch-gw` takes a **list of slot numbers**, not a count. `--watch-gw 40`
watches slot 40 — not slots 0..39.

**7. ⛔ `--no-build` boots the last image `ingame.py` built, not the last one
*you* built.** `bleck mod build` writes `work/build/<mod>.iso`; `ingame.py`
builds and boots `work/build/<mod>.wbfs`. Edit a script, rebuild by hand, pass
`--no-build`, and you boot the **previous** run's disc.

⚠️ The tell in D271 was a progress marker stopping at a number the edited script
no longer contained. Without the marker it would have read as the removed call
still hanging. **Drop `--no-build` whenever the mod has changed.**

⚠️ This is the general trap, and it caught this project three times in one day
(D267, D271 twice): **an out-of-date artefact impersonates a bug in whatever
reads it.** Check the timestamp before you change the reader.

## ⚠️ `ingame.py` has no `--mods-dir`

It shells out to `uv run bleck mod build <mod> …` **without** passing one, so it
resolves against `BLECK_MODS_DIR`, which defaults to `mods/`. Every mod this
repo's docs name lives in `example-mods/` (D147). To run one through the rig:

```powershell
$env:BLECK_MODS_DIR = "example-mods"; uv run python scripts/ingame.py coin-tick --words 12
```

Write a *new* probe under `mods/` instead — that is what it is for, it is
git-ignored, and nothing needs cleaning up afterwards.

## The one-question variant: `scripts/check_binding.py`

```bash
uv run python scripts/check_binding.py warp-combo warp_home 4 0x8010D0F0
#                                      mod        script    idx expected
```

Reads back the address `elf2rel` actually bound a game function to. A
`USER_FUNC` target is filled in at link time, and bound wrongly **the script
still runs and silently does nothing** (D70). Memory reads only, `--seconds 90`,
works on a locked machine.

⚠️ Prefer the two-line test to the new tool. D71 built a whole script to read a
bound address, correctly, to answer a question that did not matter; one extra
`gw` write would have been more discriminating and taken minutes.

## Related

- `hunting-a-hang` — when the run ends in a freeze rather than a value
- `reading-the-game-live` — hooks, `mode: before/after/replace`, tracing calls
- `catalog-dumps` — the `dump_*.py` scripts that reuse this rig's `Session`
- `slow-command-discipline` — before spending a run at all
