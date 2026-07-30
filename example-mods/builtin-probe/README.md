# builtin-probe

**Finding out what a builtin actually does, instead of guessing from its name.**

The upstream headers give 443 builtins an argument list and nothing else — no
prose, for any of them. So "`evt_pouch_get_coins` takes one argument" is
recorded, but "that argument is where the coin count comes back" was an
inference until this mod called it and read the answer.

```bash
uv run python scripts/ingame.py builtin-probe \
    --watch-gw 31 29 0 1 2 3 4 5 6 7 8 9 10 11 --seconds 80
```

Results go in `bleck/script/measured.json`, which is the only route by which a
description reaches the published reference.

## Two things the script does that matter

⚠️ **Slots are pre-seeded with a sentinel (`12345`), never left at zero.**
Otherwise "returned 0" and "never wrote" look identical. `evt_mario_get_pos`
reads `0, 0, 0` in the attract demo — and it was the *missing* sentinel, not the
zeros, that proved the call worked.

⚠️ **A progress marker is set before each call, not after.** A builtin that
never returns then names itself instead of leaving silence. That is how
`evt_pouch_check_have_item` was caught: `gw[31]` stopped at its number and
stayed there for 60 seconds.

## What it found

✅ Nine getters confirmed, values in `measured.json` (D184).
⛔ `evt_pouch_check_have_item` does not return, reproduced twice.
⚠️ `spawn` does not detach — a blocking child blocks its parent, so the second
run's attempt to isolate the broken call did not isolate it.
