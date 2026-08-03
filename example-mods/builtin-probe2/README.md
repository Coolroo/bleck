# builtin-probe2

**The second batch** (D271). Same instrument as [`builtin-probe`](../builtin-probe/),
which explains the sentinel and the progress marker; this records what the second
run added and the two traps it hit.

```bash
uv run python scripts/ingame.py builtin-probe2 \
    --watch-gw 31 29 0 1 2 3 4 5 6 8 9 10 11 12 --seconds 100
```

⚠️ **`--watch-gw` takes a list of slot numbers, not a count.** Passing it one
number watches one slot, and `--words` reads the probe block at `0x80005000`,
which this mod never writes. A whole run was spent showing 34 words of zeroes
from a block nothing had touched.

⚠️ **`--no-build` boots the existing `.wbfs`.** `bleck mod build` writes a
`.iso`, so editing the script, rebuilding by hand and then passing `--no-build`
boots the *previous* run's image. The tell was a progress marker stopping at a
number the edited script no longer contains.

## ⛔ The evt global work slots are shared with the game

The game's own scripts write `gw` too. After the attract demo changed map, seven
of the watched slots took new values every sample — one of them four different
values in nine seconds.

**A reading is only trustworthy while it stays stable across samples.** The two
that mattered here, `gw[8]` and `gw[9]`, held their values through every sample
of a 100-second run, which is why they are recorded and the drifting ones are
not.

## ⛔ A null name argument hangs the script

`evt_npc_get_max_hp(0, &out)` never returned: the marker stopped at its number
and stayed for 90 seconds. Its first argument is a `const char *` and `0` is a
null pointer. That is a fact about calling it wrongly, not about the builtin —
which is why it is recorded that way and the call was removed rather than
"fixed" with a guessed NPC name.
