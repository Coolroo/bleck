# effdata-probe

**Reading the effect system's work struct out of a running game** — and the
example of a probe whose guard earned its keep by *failing*.

```bash
uv run python scripts/ingame.py effdata-probe --words 52 --seconds 80 \
    --mods-dir example-mods
```

## What it was testing

D197 found the `effdata` loader inside `effSubMain` and saw it store a pointer
at **+0x0C** of a global reached as `r13-30492`. The symbol list names
`effsub_wp` at `0x805AE7E4`, and `0x805AE7E4 + 30492 = 0x805B5F00` — a clean
small-data base, which is what suggested they are the same global.

⚠️ **The inference was that +0x0C holds the parsed `effdata.dat`. It does not.**

## Why the guard mattered

The probe does not just dump the pointer, it checks two marks measured from the
file *on disc* (D190): the first word being `0x40`, and `EFDT` at offset `0x40`.
Neither can appear by coincidence.

`LOOKS_RIGHT` came back **0**. What +0x0C actually points at is a file handle
whose `+0x20` holds the string `./eff/effdata.tpl` — so the loader stores a
*request*, not a buffer, and it is the texture file rather than the data one.

⛔ Without that check the run would have produced 20 words of plausible-looking
memory and a confident wrong conclusion. Recording the refutation is the result
(D198).

## What it did establish

- ✅ `effsub_wp` is live and points at `0x8050B830`
- ✅ `effdrv_wp` points at `0x8050B820` — **16 bytes below it**, so the two work
  structs are adjacent
- ✅ +0x0C is a file handle with the path at +0x20
